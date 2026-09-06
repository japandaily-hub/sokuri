"""自動運用（r13）: 運営ジョブの機械認証と新ジョブ3本のテスト。

対象:
- ``get_ops_or_admin``: ``X-Ops-Token`` 一致で通る／不一致・未設定はヘッダ経路が無効で
  管理者 JWT が無ければ 403／管理者 JWT では従来どおり。
- ``POST /admin/jobs/admin-audit``: ADMIN_EMAILS の登録・role・停止の照合と critical アラート。
- ``POST /admin/jobs/contacts/handle-probes``: プローブ差出人の未対応行だけを対応済みにする。
- ``POST /admin/jobs/mail-probe``: Brevo の messageId を集めて返す／キー未設定は sent=false。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import admin as admin_endpoint
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.models.contact_message import ContactMessage
from app.db.models.user import User
from app.db.session import get_session
from app.services import notify

#: 本番想定は ``secrets.token_urlsafe(32)``（43文字）。最小長 32 を満たす固定値。
OPS_TOKEN = "ops-test-token-0123456789-abcdefghijklmnop"


def create_test_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    test_app = create_test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def ops_token(monkeypatch) -> str:
    monkeypatch.setattr(get_settings(), "ops_job_token", OPS_TOKEN)
    return OPS_TOKEN


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ops(token: str = OPS_TOKEN) -> dict[str, str]:
    return {"X-Ops-Token": token}


async def _make_user(
    db_session: AsyncSession,
    email: str,
    *,
    role: str = "user",
    suspended: bool = False,
    deleted: bool = False,
) -> tuple[User, str]:
    user = User(
        email=email,
        password_hash=hash_password("userpass123"),
        name="依頼者",
        role=role,
        is_suspended=suspended,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, create_access_token(user.id, "user", role)


async def _make_contact(
    db_session: AsyncSession,
    email: str,
    *,
    handled: bool = False,
    name: str = "カタヅケ運営（自動確認）",
    age: timedelta | None = None,
) -> ContactMessage:
    contact = ContactMessage(
        name=name,
        email=email,
        category="other",
        message="本文",
        handled_at=datetime.now(timezone.utc) if handled else None,
    )
    if age is not None:
        contact.created_at = datetime.now(timezone.utc) - age
    db_session.add(contact)
    await db_session.commit()
    await db_session.refresh(contact)
    return contact


# ──────────────────────────── 認可 ────────────────────────────


async def test_ops_token_header_allows_jobs(client: AsyncClient, ops_token: str):
    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", new_callable=AsyncMock
    ), patch(
        "app.services.notify_dispatch.dispatch_no_bid_reminder", new_callable=AsyncMock
    ):
        r = await client.post("/api/v1/admin/jobs/reminders", headers=_ops())
    assert r.status_code == 200, r.text
    assert r.json() == {"overdue": 0, "no_bid": 0}


async def test_ops_token_mismatch_is_rejected(client: AsyncClient, ops_token: str):
    r = await client.post("/api/v1/admin/jobs/reminders", headers=_ops("wrong-token"))
    assert r.status_code == 403
    # 不一致でも JWT が管理者ならフォールバックで通る（人の運用を邪魔しない）
    # → 別テストで確認。ここでは JWT 無しの 403 だけ見る。


async def test_ops_token_header_is_disabled_when_unset(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(get_settings(), "ops_job_token", "")
    r = await client.post("/api/v1/admin/jobs/reminders", headers=_ops(""))
    assert r.status_code == 403
    r = await client.post("/api/v1/admin/jobs/reminders", headers=_ops(OPS_TOKEN))
    assert r.status_code == 403


async def test_ops_token_shorter_than_minimum_is_treated_as_unset(
    client: AsyncClient, monkeypatch
):
    """弱い（短い）トークンを設定しても機械経路は開かない。"""
    monkeypatch.setattr(get_settings(), "ops_job_token", "short-token")
    r = await client.post("/api/v1/admin/jobs/reminders", headers=_ops("short-token"))
    assert r.status_code == 403


async def test_admin_jwt_still_works_and_user_jwt_is_rejected(
    client: AsyncClient, db_session: AsyncSession, ops_token: str
):
    _, user_token = await _make_user(db_session, "ops_user@example.com")
    _, admin_token = await _make_user(db_session, "ops_admin@example.com", role="admin")
    assert (
        await client.post("/api/v1/admin/jobs/reminders", headers=_auth(user_token))
    ).status_code == 403
    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", new_callable=AsyncMock
    ), patch(
        "app.services.notify_dispatch.dispatch_no_bid_reminder", new_callable=AsyncMock
    ):
        r = await client.post("/api/v1/admin/jobs/reminders", headers=_auth(admin_token))
    assert r.status_code == 200, r.text


async def test_ops_token_mismatches_alert_after_threshold(
    client: AsyncClient, ops_token: str, monkeypatch
):
    """不一致が閾値に達したら運営へ warning（値は本文に載せない）。"""
    from app.api import deps

    monkeypatch.setattr(deps, "_ops_token_mismatch_count", 0)
    fired: list = []

    def _capture(coro) -> None:
        fired.append(coro)
        coro.close()

    with patch("app.services.alerts.fire_and_forget", side_effect=_capture), patch(
        "app.services.alerts.send_alert", new_callable=AsyncMock
    ) as send:
        for _ in range(deps.OPS_JOB_TOKEN_MISMATCH_ALERT_THRESHOLD):
            r = await client.post(
                "/api/v1/admin/jobs/reminders",
                headers=_ops("wrong-token-wrong-token-wrong-token"),
            )
            assert r.status_code == 403
    assert len(fired) == 1
    assert send.call_args.kwargs["key"] == "ops_token_mismatch"
    assert "wrong-token" not in send.call_args.args[1]


async def test_key_fingerprint_returns_digest_not_key(
    client: AsyncClient, ops_token: str, monkeypatch
):
    import hashlib

    settings = get_settings()
    monkeypatch.setattr(settings, "app_encryption_key", "fake-key-value-for-test")
    r = await client.post("/api/v1/admin/jobs/key-fingerprint", headers=_ops())
    assert r.status_code == 200, r.text
    assert r.json() == {
        "configured": True,
        "sha256": hashlib.sha256(b"fake-key-value-for-test").hexdigest(),
    }
    assert "fake-key-value" not in r.text
    monkeypatch.setattr(settings, "app_encryption_key", "")
    r = await client.post("/api/v1/admin/jobs/key-fingerprint", headers=_ops())
    assert r.json() == {"configured": False, "sha256": None}


async def test_ops_token_does_not_open_other_admin_endpoints(
    client: AsyncClient, ops_token: str
):
    """共有トークンは冪等ジョブ専用。一覧閲覧・個別操作には効かない。"""
    assert (await client.get("/api/v1/admin/users", headers=_ops())).status_code in (401, 403)
    assert (await client.get("/api/v1/admin/contacts", headers=_ops())).status_code in (401, 403)


# ──────────────────────────── admin-audit ────────────────────────────


async def test_admin_audit_ok_when_all_registered_admins(
    client: AsyncClient, db_session: AsyncSession, ops_token: str, monkeypatch
):
    await _make_user(db_session, "Boss@example.com", role="admin")
    await _make_user(db_session, "second@example.com", role="admin")
    monkeypatch.setattr(
        get_settings(), "admin_emails_raw", "boss@example.com, second@example.com"
    )
    with patch("app.services.alerts.send_alert", new_callable=AsyncMock) as alert:
        r = await client.post("/api/v1/admin/jobs/admin-audit", headers=_ops())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["active_admin_count"] == 2
    assert [e["email"] for e in body["entries"]] == ["boss@example.com", "second@example.com"]
    assert all(e["ok"] and e["registered"] and e["role"] == "admin" for e in body["entries"])
    assert alert.await_count == 0


async def test_admin_audit_flags_unregistered_non_admin_and_suspended(
    client: AsyncClient, db_session: AsyncSession, ops_token: str, monkeypatch
):
    await _make_user(db_session, "boss@example.com", role="admin")
    await _make_user(db_session, "plain@example.com", role="user")
    await _make_user(db_session, "stopped@example.com", role="admin", suspended=True)
    await _make_user(db_session, "gone@example.com", role="admin", deleted=True)
    monkeypatch.setattr(
        get_settings(),
        "admin_emails_raw",
        "boss@example.com,plain@example.com,stopped@example.com,gone@example.com,nobody@example.com",
    )
    with patch("app.services.alerts.send_alert", new_callable=AsyncMock) as alert:
        r = await client.post("/api/v1/admin/jobs/admin-audit", headers=_ops())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["active_admin_count"] == 1
    by_email = {e["email"]: e for e in body["entries"]}
    assert by_email["boss@example.com"]["ok"] is True
    assert by_email["plain@example.com"] == {
        "email": "plain@example.com",
        "registered": True,
        "role": "user",
        "suspended": False,
        "ok": False,
    }
    assert by_email["stopped@example.com"]["suspended"] is True
    assert by_email["stopped@example.com"]["ok"] is False
    assert by_email["gone@example.com"]["registered"] is False
    assert by_email["nobody@example.com"]["registered"] is False
    assert alert.await_count == 1
    assert alert.await_args.kwargs["severity"] == "critical"
    assert alert.await_args.kwargs["key"] == "admin_audit_failed"
    # アラート本文にメールアドレスを載せない（通知経路に PII を流さない）
    assert "example.com" not in alert.await_args.args[1]


async def test_alerts_resolve_only_after_active_alert(monkeypatch):
    """resolve_alert は同じ key の異常を発報した後だけ復旧（info）を送る。"""
    from app.services import alerts

    alerts.reset_state_for_tests()
    sent: list[tuple] = []

    async def _capture(title, body, *, severity="critical", key=None):
        sent.append((severity, key))
        return True

    # 発報していない状態では復旧を送らない
    assert await alerts.resolve_alert("k1", "復旧", "本文") is False
    assert alerts.is_active("k1") is False

    # 異常を発報（通知チャネル未設定でも「発報中」として記録される）
    await alerts.send_alert("異常", "本文", severity="warning", key="k1")
    assert alerts.is_active("k1") is True
    # クールダウン中の再発報でも発報中は維持される
    await alerts.send_alert("異常", "本文", severity="warning", key="k1")
    assert alerts.is_active("k1") is True

    monkeypatch.setattr(alerts, "send_alert", _capture)
    assert await alerts.resolve_alert("k1", "復旧", "本文") is True
    assert sent == [("info", "k1:recovered")]
    assert alerts.is_active("k1") is False
    # 2回目は送らない（復旧は1回だけ）
    assert await alerts.resolve_alert("k1", "復旧", "本文") is False
    assert len(sent) == 1
    alerts.reset_state_for_tests()


async def test_admin_audit_sends_recovery_after_previous_failure(
    client: AsyncClient, db_session: AsyncSession, ops_token: str, monkeypatch
):
    """不整合→是正の順で実行すると、是正後に1回だけ復旧通知が出る。"""
    from app.services import alerts

    alerts.reset_state_for_tests()
    await _make_user(db_session, "boss2@example.com", role="admin")
    monkeypatch.setattr(get_settings(), "admin_emails_raw", "boss2@example.com,ghost@example.com")
    with patch("app.services.alerts._send_line", new_callable=AsyncMock, return_value=True), patch(
        "app.services.alerts._send_webhook", new_callable=AsyncMock, return_value=False
    ), patch("app.services.alerts._send_email", new_callable=AsyncMock, return_value=False):
        r = await client.post("/api/v1/admin/jobs/admin-audit", headers=_ops())
        assert r.json()["ok"] is False
        assert alerts.is_active("admin_audit_failed") is True

        # 是正: 未登録アドレスを外す
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "boss2@example.com")
        with patch("app.services.alerts.send_alert", new_callable=AsyncMock) as send:
            r = await client.post("/api/v1/admin/jobs/admin-audit", headers=_ops())
            assert r.json()["ok"] is True
            assert send.await_count == 1
            assert send.await_args.kwargs == {"severity": "info", "key": "admin_audit_failed:recovered"}
            assert "正常に戻りました" in send.await_args.args[0]
            # 続けて正常でも復旧は再送しない
            r = await client.post("/api/v1/admin/jobs/admin-audit", headers=_ops())
            assert send.await_count == 1
    alerts.reset_state_for_tests()


async def test_mail_send_success_resolves_previous_send_failure(monkeypatch):
    """Brevo 送信失敗の warning を出した後に送信が成功したら、復旧通知を1回スケジュールする。"""
    from app.services import alerts

    alerts.reset_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    _FakeClient.calls = []
    monkeypatch.setattr(notify.httpx, "AsyncClient", _FakeClient)
    fired: list = []

    def _capture(coro) -> None:
        fired.append(coro)
        coro.close()

    with patch("app.services.alerts.fire_and_forget", side_effect=_capture):
        # 発報していない状態の成功では何もしない
        assert await notify._send("x@example.com", "件名", "<p>本文</p>") is True
        assert fired == []
        # 失敗を発報した状態にしてから成功させる
        await alerts.send_alert("失敗", "本文", severity="warning", key=notify._BREVO_SEND_FAILED_KEY)
        assert await notify._send("x@example.com", "件名", "<p>本文</p>") is True
        assert len(fired) == 1
    alerts.reset_state_for_tests()


async def test_admin_audit_fails_when_admin_emails_empty(
    client: AsyncClient, ops_token: str, monkeypatch
):
    monkeypatch.setattr(get_settings(), "admin_emails_raw", "")
    with patch("app.services.alerts.send_alert", new_callable=AsyncMock) as alert:
        r = await client.post("/api/v1/admin/jobs/admin-audit", headers=_ops())
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["entries"] == []
    assert alert.await_count == 1


# ──────────────────────────── contacts/handle-probes ────────────────────────────


async def test_handle_probes_marks_only_probe_sender(
    client: AsyncClient, db_session: AsyncSession, ops_token: str, monkeypatch
):
    monkeypatch.setattr(get_settings(), "ops_probe_contact_email", "Probe@example.com")
    probe1 = await _make_contact(db_session, "probe@example.com")
    probe2 = await _make_contact(db_session, "PROBE@example.com")
    already = await _make_contact(db_session, "probe@example.com", handled=True)
    customer = await _make_contact(db_session, "customer@example.com")
    # 同じアドレスでも氏名が完全一致しなければ実際の相談として残す（部分一致も不可）
    same_addr_real = await _make_contact(db_session, "probe@example.com", name="山田 太郎")
    same_addr_partial = await _make_contact(db_session, "probe@example.com", name="運営（自動確認）")
    # 7 日より古い行は触らない
    too_old = await _make_contact(db_session, "probe@example.com", age=timedelta(days=8))
    before = already.handled_at

    r = await client.post("/api/v1/admin/jobs/contacts/handle-probes", headers=_ops())
    assert r.status_code == 200, r.text
    assert r.json() == {"handled": 2, "probe_email": "probe@example.com"}

    db_session.expire_all()
    rows = {
        c.id: c
        for c in (await db_session.execute(select(ContactMessage))).scalars().all()
    }
    assert rows[probe1.id].handled_at is not None
    assert rows[probe1.id].handled_by_admin_id is None
    assert rows[probe2.id].handled_at is not None
    assert rows[customer.id].handled_at is None
    assert rows[same_addr_real.id].handled_at is None
    assert rows[same_addr_partial.id].handled_at is None
    assert rows[too_old.id].handled_at is None
    assert rows[already.id].handled_at == before

    # 冪等: 2回目は 0 件
    r = await client.post("/api/v1/admin/jobs/contacts/handle-probes", headers=_ops())
    assert r.json()["handled"] == 0


async def test_handle_probes_noop_when_unset(
    client: AsyncClient, db_session: AsyncSession, ops_token: str, monkeypatch
):
    monkeypatch.setattr(get_settings(), "ops_probe_contact_email", "")
    contact = await _make_contact(db_session, "anyone@example.com")
    r = await client.post("/api/v1/admin/jobs/contacts/handle-probes", headers=_ops())
    assert r.status_code == 200
    assert r.json() == {"handled": 0, "probe_email": None}
    await db_session.refresh(contact)
    assert contact.handled_at is None


# ──────────────────────────── mail-probe ────────────────────────────


class _FakeResponse:
    def __init__(self, message_id: str):
        self._message_id = message_id

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"messageId": self._message_id}


class _FakeClient:
    """httpx.AsyncClient の最小スタブ（POST ごとに連番の messageId を返す）。"""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeClient.calls.append(json)
        return _FakeResponse(f"<msg-{len(_FakeClient.calls)}@test>")


async def test_mail_probe_returns_message_ids_and_throttles_repeat(
    client: AsyncClient, ops_token: str, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    monkeypatch.setattr(settings, "admin_emails_raw", "a@example.com,b@example.com")
    monkeypatch.setattr(admin_endpoint, "_mail_probe_last_sent_at", None)
    _FakeClient.calls = []
    monkeypatch.setattr(notify.httpx, "AsyncClient", _FakeClient)

    r = await client.post("/api/v1/admin/jobs/mail-probe", headers=_ops())
    assert r.status_code == 200, r.text
    assert r.json() == {
        "sent": True,
        "message_ids": ["<msg-1@test>", "<msg-2@test>"],
        "recipients": 2,
        "throttled": False,
    }
    assert [c["to"][0]["email"] for c in _FakeClient.calls] == ["a@example.com", "b@example.com"]
    assert all("到達プローブ" in c["subject"] for c in _FakeClient.calls)

    # 連打しても 20 時間以内は送らない（無料枠の食い潰し防止）
    r = await client.post("/api/v1/admin/jobs/mail-probe", headers=_ops())
    assert r.status_code == 200
    assert r.json() == {"sent": False, "message_ids": [], "recipients": 2, "throttled": True}
    assert len(_FakeClient.calls) == 2


async def test_mail_probe_without_brevo_key_reports_not_sent(
    client: AsyncClient, ops_token: str, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "")
    monkeypatch.setattr(settings, "admin_emails_raw", "a@example.com")
    monkeypatch.setattr(admin_endpoint, "_mail_probe_last_sent_at", None)
    monkeypatch.setattr(notify, "_brevo_missing_key_alerted", True)
    r = await client.post("/api/v1/admin/jobs/mail-probe", headers=_ops())
    assert r.status_code == 200
    assert r.json() == {"sent": False, "message_ids": [], "recipients": 1, "throttled": False}


async def test_send_returns_bool_and_send_raw_returns_id(monkeypatch):
    """既存の ``_send`` 互換（bool）と、新設 ``_send_raw`` の messageId を同時に確認。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    _FakeClient.calls = []
    monkeypatch.setattr(notify.httpx, "AsyncClient", _FakeClient)
    assert await notify._send("x@example.com", "件名", "<p>本文</p>") is True
    assert await notify._send_raw("x@example.com", "件名", "<p>本文</p>") == "<msg-2@test>"
