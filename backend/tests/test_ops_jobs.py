"""自動運用（r13）: 運営ジョブの機械認証と新ジョブ3本のテスト。

対象:
- ``get_ops_or_admin``: ``X-Ops-Token`` 一致で通る／不一致・未設定はヘッダ経路が無効で
  管理者 JWT が無ければ 403／管理者 JWT では従来どおり。
- ``POST /admin/jobs/admin-audit``: ADMIN_EMAILS の登録・role・停止の照合と critical アラート。
- ``POST /admin/jobs/contacts/handle-probes``: プローブ差出人の未対応行だけを対応済みにする。
- ``POST /admin/jobs/mail-probe``: Brevo の messageId を集めて返す／キー未設定は sent=false。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.models.contact_message import ContactMessage
from app.db.models.user import User
from app.db.session import get_session
from app.services import notify

OPS_TOKEN = "ops-test-token-0123456789"


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
    db_session: AsyncSession, email: str, *, handled: bool = False
) -> ContactMessage:
    contact = ContactMessage(
        name="テスト",
        email=email,
        category="other",
        message="本文",
        handled_at=datetime.now(timezone.utc) if handled else None,
    )
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


async def test_mail_probe_returns_message_ids(
    client: AsyncClient, ops_token: str, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    monkeypatch.setattr(settings, "admin_emails_raw", "a@example.com,b@example.com")
    _FakeClient.calls = []
    monkeypatch.setattr(notify.httpx, "AsyncClient", _FakeClient)

    r = await client.post("/api/v1/admin/jobs/mail-probe", headers=_ops())
    assert r.status_code == 200, r.text
    assert r.json() == {
        "sent": True,
        "message_ids": ["<msg-1@test>", "<msg-2@test>"],
        "recipients": 2,
    }
    assert [c["to"][0]["email"] for c in _FakeClient.calls] == ["a@example.com", "b@example.com"]
    assert all("到達プローブ" in c["subject"] for c in _FakeClient.calls)


async def test_mail_probe_without_brevo_key_reports_not_sent(
    client: AsyncClient, ops_token: str, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "")
    monkeypatch.setattr(settings, "admin_emails_raw", "a@example.com")
    monkeypatch.setattr(notify, "_brevo_missing_key_alerted", True)
    r = await client.post("/api/v1/admin/jobs/mail-probe", headers=_ops())
    assert r.status_code == 200
    assert r.json() == {"sent": False, "message_ids": [], "recipients": 1}


async def test_send_returns_bool_and_send_raw_returns_id(monkeypatch):
    """既存の ``_send`` 互換（bool）と、新設 ``_send_raw`` の messageId を同時に確認。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-key")
    _FakeClient.calls = []
    monkeypatch.setattr(notify.httpx, "AsyncClient", _FakeClient)
    assert await notify._send("x@example.com", "件名", "<p>本文</p>") is True
    assert await notify._send_raw("x@example.com", "件名", "<p>本文</p>") == "<msg-2@test>"
