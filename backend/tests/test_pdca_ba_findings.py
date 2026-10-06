"""ペルソナ壁打ち監査（pdca）の backend 所見の回帰テスト。

- admin H-2: 運営はチャットを代理送信できない／運営の閲覧で依頼者の未読が消えない
- seller 高#5: メール登録者（LINE 未連携）への新着チャット・日程提示のメール通知
- 日時: 時差情報なしの日時は UTC（``Z`` つき）で返る
- vendor V-05: 長すぎる入力は理由つきの日本語（文字列 detail）の 422
- vendor V-03: 同額で並んだ入札が API で区別できる
- seller 中#7: 出品の取り下げ理由は任意
- admin H-5: 運営の操作履歴 API
- admin M-1: 口座の全桁表示で運営アラートが出る
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.contact_message import ContactMessage
from app.db.models.user import User
from app.services import notify, notify_dispatch
from tests.test_katadzuke_api import _application_payload
from tests.test_line_user_notify import (  # noqa: F401 -- fixture（autouse 含む）として使う
    _auth,
    _create_case,
    _make_admin,
    _reset_message_push_ledger,
    _signup_user,
    _verified_operator,
    client,
)

async def _setup_txn(
    client: AsyncClient, db_session: AsyncSession, tag: str
) -> tuple[str, str, str, str, str]:
    """成約を1件作り (txn_id, case_id, user_token, op_token, admin_token) を返す。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, f"{tag}_user@example.com")
    op_token, _ = await _verified_operator(client, admin_token, f"{tag}_op@example.com", "A社")
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 15000}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{r.json()['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], case["id"], user_token, op_token, admin_token


# ──────────────────────────── admin H-2 ────────────────────────────


async def test_admin_cannot_send_chat_message(client: AsyncClient, db_session: AsyncSession):
    txn_id, _case, _user, op_token, admin_token = await _setup_txn(client, db_session, "h2send")

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "運営からのお知らせです"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "運営はチャットを代理で送信できません。"

    # 業者側から見て、依頼者名義の発言は1件も保存されていない。
    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(op_token))
    assert r.status_code == 200
    assert [m for m in r.json() if m["kind"] == "text"] == []


async def test_admin_who_owns_the_case_can_still_send(
    client: AsyncClient, db_session: AsyncSession
):
    """運営アカウントが自分の案件の所有者として送る場合は「代理」ではないので送れる。"""
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, admin_token, "h2own_op@example.com", "A社")
    case = await _create_case(client, admin_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 15000}, headers=_auth(op_token)
    )
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{r.json()['id']}/select", headers=_auth(admin_token)
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/transactions/{r.json()['id']}/messages",
        json={"body": "自分の案件の発言"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 201, r.text


async def test_admin_read_does_not_clear_owner_unread(
    client: AsyncClient, db_session: AsyncSession
):
    txn_id, _case, user_token, op_token, admin_token = await _setup_txn(
        client, db_session, "h2read"
    )
    with patch(
        "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
        new=AsyncMock(),
    ):
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "訪問日のご相談です"},
            headers=_auth(op_token),
        )
        assert r.status_code == 201, r.text

    async def owner_unread() -> int:
        r = await client.get("/api/v1/transactions", headers=_auth(user_token))
        assert r.status_code == 200, r.text
        return r.json()[0]["unread_count"]

    assert await owner_unread() == 1
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert await owner_unread() == 1  # 運営の閲覧では消えない

    # 依頼者本人が読めば既読になる。
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(user_token)
    )
    assert r.status_code == 200, r.text
    assert await owner_unread() == 0


# ──────────────────────────── seller 高#5（メール通知） ────────────────────────────


class TestMessageReceivedEmail:
    async def test_email_when_no_line_and_opted_in(self, monkeypatch):
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        await notify_dispatch.dispatch_message_received(
            None, "txn-m1", "user", email="owner@example.com", email_notify_opt_in=True
        )
        send.assert_awaited_once_with("owner@example.com", "txn-m1", "user")

    async def test_email_is_debounced_per_transaction(self, monkeypatch):
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        for _ in range(3):
            await notify_dispatch.dispatch_message_received(
                None, "txn-m2", "user", email="owner@example.com"
            )
        assert send.await_count == 1

    async def test_failed_email_does_not_hold_debounce(self, monkeypatch):
        send = AsyncMock(return_value=False)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        for _ in range(2):
            await notify_dispatch.dispatch_message_received(
                None, "txn-m3", "user", email="owner@example.com"
            )
        assert send.await_count == 2

    async def test_opt_out_sends_nothing(self, monkeypatch):
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        await notify_dispatch.dispatch_message_received(
            None, "txn-m4", "user", email="owner@example.com", email_notify_opt_in=False
        )
        send.assert_not_awaited()

    async def test_opt_out_keeps_line(self, monkeypatch):
        push = AsyncMock(return_value=True)
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        await notify_dispatch.dispatch_message_received(
            "U1", "txn-m5", "user", email="owner@example.com", email_notify_opt_in=False
        )
        push.assert_awaited_once()
        send.assert_not_awaited()

    async def test_line_success_does_not_also_email(self, monkeypatch):
        push = AsyncMock(return_value=True)
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        await notify_dispatch.dispatch_message_received(
            "U1", "txn-m6", "user", email="owner@example.com"
        )
        send.assert_not_awaited()

    async def test_line_failure_falls_back_to_email(self, monkeypatch):
        push = AsyncMock(return_value=False)
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        await notify_dispatch.dispatch_message_received(
            "U1", "txn-m7", "user", email="owner@example.com"
        )
        send.assert_awaited_once()

    @pytest.mark.parametrize("address", ["x@line.katazuke.internal", "x@deleted.katazuke.internal", None, ""])
    async def test_placeholder_or_missing_email_sends_nothing(self, monkeypatch, address):
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.notify.send_message_received", send)
        assert not address or notify.is_placeholder_email(address)
        await notify_dispatch.dispatch_message_received(
            None, "txn-m8", "user", email=address
        )
        send.assert_not_awaited()

    async def test_email_body_has_no_message_text_or_pii(self, monkeypatch):
        captured: dict[str, str] = {}

        async def fake_send(to_email: str, subject: str, html: str) -> bool:
            captured["subject"], captured["html"] = subject, html
            return True

        monkeypatch.setattr("app.services.notify._send", fake_send)
        assert await notify.send_message_received("owner@example.com", "txn-body", "user")
        assert "/chat/txn-body" in captured["html"]
        assert "新しいメッセージがあります" in captured["html"]
        assert "owner@example.com" not in captured["html"]

    async def test_endpoint_passes_owner_email_and_opt_in(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        txn_id, _case, _user, op_token, _admin = await _setup_txn(client, db_session, "mailep")
        await db_session.execute(
            User.__table__.update()
            .where(User.email == "mailep_user@example.com")
            .values(email_notify_opt_in=False)
        )
        await db_session.commit()
        with patch(
            "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
            new=AsyncMock(),
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "日程のご相談です"},
                headers=_auth(op_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_called_once_with(
            None,
            txn_id,
            "user",
            email="mailep_user@example.com",
            email_notify_opt_in=False,
            unread_pending=False,
        )

    async def test_endpoint_skips_email_for_deleted_or_suspended_owner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        txn_id, _case, _user, op_token, _admin = await _setup_txn(client, db_session, "maildel")
        await db_session.execute(
            User.__table__.update()
            .where(User.email == "maildel_user@example.com")
            .values(is_suspended=True)
        )
        await db_session.commit()
        with patch(
            "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
            new=AsyncMock(),
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "日程のご相談です"},
                headers=_auth(op_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_not_called()

    async def test_send_failure_does_not_fail_chat_post(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        txn_id, _case, _user, op_token, _admin = await _setup_txn(client, db_session, "mailerr")
        monkeypatch.setattr(
            "app.services.notify.send_message_received",
            AsyncMock(side_effect=RuntimeError("brevo down")),
        )
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "日程のご相談です"},
            headers=_auth(op_token),
        )
        assert r.status_code == 201, r.text

    async def test_schedule_proposed_respects_opt_out(self, monkeypatch):
        send = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.notify.send_schedule_proposed", send)
        await notify_dispatch.dispatch_schedule_proposed(
            None, "owner@example.com", "txn-s1", False
        )
        send.assert_not_awaited()
        await notify_dispatch.dispatch_schedule_proposed(
            None, "owner@example.com", "txn-s1", True
        )
        send.assert_awaited_once()


# ──────────────────────────── 日時の Z ────────────────────────────


async def test_naive_datetime_is_returned_as_utc_with_z(
    client: AsyncClient, db_session: AsyncSession
):
    txn_id, _case, user_token, _op, _admin = await _setup_txn(client, db_session, "utcz")
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "こんにちは"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["created_at"].endswith("Z")


def test_utc_datetime_leaves_aware_values_unchanged():
    from pydantic import BaseModel

    from app.schemas_katadzuke import UtcDatetime

    class M(BaseModel):
        at: UtcDatetime

    from datetime import timedelta

    jst = timezone(timedelta(hours=9))
    aware = datetime(2026, 10, 6, 9, 0, tzinfo=jst)
    assert M(at=aware).at == aware
    assert M(at=aware).at.utcoffset() == timedelta(hours=9)
    assert M(at=datetime(2026, 10, 6, 0, 0)).at.tzinfo == timezone.utc


# ──────────────────────────── V-05 ────────────────────────────


@pytest.fixture
async def real_client(db_session: AsyncSession):
    """本番と同じ例外ハンドラ（app.main の RequestValidationError）を持つクライアント。"""
    from httpx import ASGITransport

    from app.db.session import get_session
    from app.main import create_app

    app = create_app()

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_too_long_chat_message_is_422_with_japanese_reason(
    real_client: AsyncClient, db_session: AsyncSession
):
    txn_id, _case, user_token, _op, _admin = await _setup_txn(real_client, db_session, "long1")
    r = await real_client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "あ" * 2001},
        headers=_auth(user_token),
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "メッセージは2,000文字以内で入力してください。"


async def test_too_long_bid_message_is_422_with_japanese_reason(
    real_client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(real_client, db_session)
    user_token = await _signup_user(real_client, "long2_user@example.com")
    op_token, _ = await _verified_operator(real_client, admin_token, "long2_op@example.com", "A社")
    case = await _create_case(real_client, user_token)
    r = await real_client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 15000, "message": "い" * 2001},
        headers=_auth(op_token),
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "入札メッセージは2,000文字以内で入力してください。"


async def test_other_validation_errors_keep_array_shape(
    real_client: AsyncClient, db_session: AsyncSession
):
    txn_id, _case, user_token, _op, _admin = await _setup_txn(real_client, db_session, "long3")
    r = await real_client.post(
        f"/api/v1/transactions/{txn_id}/messages", json={"body": ""}, headers=_auth(user_token)
    )
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


# ──────────────────────────── V-03 / seller 中#7 ────────────────────────────


async def test_tied_top_bid_is_flagged(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "tie_user@example.com")
    op_a, _ = await _verified_operator(client, admin_token, "tie_a@example.com", "A社")
    op_b, _ = await _verified_operator(client, admin_token, "tie_b@example.com", "B社")
    case = await _create_case(client, user_token)

    async def bid(token: str, amount: int) -> None:
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids", json={"amount": amount}, headers=_auth(token)
        )
        assert r.status_code == 201, r.text

    async def view(token: str) -> dict:
        r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(token))
        assert r.status_code == 200, r.text
        return r.json()

    await bid(op_a, 40000)
    solo = await view(op_a)
    assert solo["is_top_bidder"] is True and solo["is_tied_for_top"] is False

    await bid(op_b, 40000)
    for token in (op_a, op_b):
        tied = await view(token)
        assert tied["is_top_bidder"] is True
        assert tied["is_tied_for_top"] is True

    r = await client.patch(
        f"/api/v1/cases/{case['id']}/bids/me", json={"amount": 41000}, headers=_auth(op_a)
    )
    assert r.status_code == 200, r.text
    assert (await view(op_a))["is_tied_for_top"] is False
    behind = await view(op_b)
    assert behind["is_top_bidder"] is False and behind["is_tied_for_top"] is False


async def test_case_cancel_reason_is_optional(client: AsyncClient, db_session: AsyncSession):
    user_token = await _signup_user(client, "cancelreason@example.com")
    case = await _create_case(client, user_token)
    r = await client.post(f"/api/v1/cases/{case['id']}/cancel", json={}, headers=_auth(user_token))
    assert r.status_code == 200, r.text


# ──────────────────────────── H-5 / M-1 ────────────────────────────


async def test_admin_activity_lists_masked_entries_and_requires_admin(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    admin = (
        await db_session.execute(
            User.__table__.select().where(User.email == "admin_usernotify@katadzuke.jp")
        )
    ).one()
    contact_id = uuid.uuid4()
    db_session.add(
        ContactMessage(
            id=contact_id,
            name="山田",
            email="inquirer@example.com",
            category="other",
            message="テスト",
            handled_at=datetime.now(timezone.utc),
            handled_by_admin_id=admin.id,
        )
    )
    await db_session.commit()

    r = await client.get("/api/v1/admin/activity", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    entry = next(i for i in body["items"] if i["action"] == "contact_handle")
    assert entry["target_id"] == str(contact_id)
    assert entry["admin_email_masked"] == "a***@katadzuke.jp"
    assert entry["at"].endswith("Z")
    # 個人情報（問い合わせ者のメール・本文）は含まない。
    assert "inquirer@example.com" not in r.text and "テスト" not in r.text

    user_token = await _signup_user(client, "notadmin_act@example.com")
    assert (
        await client.get("/api/v1/admin/activity", headers=_auth(user_token))
    ).status_code == 403
    assert (await client.get("/api/v1/admin/activity")).status_code in (401, 403)
    assert (
        await client.get("/api/v1/admin/activity?limit=101", headers=_auth(admin_token))
    ).status_code == 422


async def test_admin_activity_paging_limit(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    now = datetime.now(timezone.utc)
    for _ in range(3):
        db_session.add(
            ContactMessage(
                name="a", email="a@example.com", category="other", message="m", handled_at=now
            )
        )
    await db_session.commit()
    r = await client.get("/api/v1/admin/activity?limit=2", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 2
    assert r.json()["next_before"] is not None


async def test_reveal_bank_account_fires_admin_alert_without_account_number(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    r = await client.post(
        "/api/v1/operator-applications", json=_application_payload(email="m1_reveal@example.com")
    )
    application_id = r.json()["application_id"]

    with patch("app.api.v1.endpoints.admin.alerts.send_alert", new=AsyncMock()) as alert_mock:
        r = await client.post(
            f"/api/v1/admin/operator-applications/{application_id}/reveal-bank-account",
            headers=_auth(admin_token),
        )
        await asyncio.sleep(0)
    assert r.status_code == 200, r.text
    alert_mock.assert_awaited_once()
    args, kwargs = alert_mock.call_args
    text = " ".join(str(a) for a in args) + str(kwargs)
    assert application_id in text
    assert "1234567" not in text

