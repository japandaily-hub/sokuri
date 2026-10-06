"""security review（パスワード再設定の追加修正）の回帰テスト — 再設定以外の経路。

- M-1③: チャット新着メールは、受信者が既読にするまで（または24時間経つまで）再送しない。
- L-5: 運営は依頼者名義で取引をキャンセルできない（強制終了を使う）。
- L-6: 口座の全桁開示の応答はキャッシュさせない。
- M-1④: メール送信の日次総量の警告ログ（総量だけ・宛先を出さない）。

パスワード再設定そのもの（並存・送信回数・管理者・完了通知・L-1）は tests/test_password_reset.py。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.message import Message
from app.db.models.transaction import Cancellation, Transaction
from app.services import notify, notify_dispatch
from tests.test_katadzuke_api import _application_payload
from tests.test_line_user_notify import (  # noqa: F401 -- fixture（autouse 含む）として使う
    _auth,
    _reset_message_push_ledger,
    client,
)
from tests.test_pdca_ba_findings import _setup_txn

_DISPATCH = "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received"


async def _post_message(client: AsyncClient, txn_id: str, token: str, body: str = "日程のご相談です"):
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages", json={"body": body}, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return r


# ──────────────────────────── M-1③: チャット新着メールの再送抑止 ────────────────────────────


async def test_chat_email_not_resent_until_recipient_reads(client: AsyncClient, db_session: AsyncSession):
    txn_id, _case, user_token, op_token, _admin = await _setup_txn(client, db_session, "unread1")
    with patch(_DISPATCH, new=AsyncMock()) as dispatch_mock:
        await _post_message(client, txn_id, op_token, "1通目")
        await _post_message(client, txn_id, op_token, "2通目（未読のまま）")
        r = await client.post(f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(user_token))
        assert r.status_code == 200, r.text
        await _post_message(client, txn_id, op_token, "3通目（既読の後）")
    flags = [call.kwargs["unread_pending"] for call in dispatch_mock.call_args_list]
    assert flags == [False, True, False]


async def test_chat_email_resent_after_24_hours_even_if_unread(client: AsyncClient, db_session: AsyncSession):
    txn_id, _case, _user, op_token, _admin = await _setup_txn(client, db_session, "unread2")
    with patch(_DISPATCH, new=AsyncMock()) as dispatch_mock:
        await _post_message(client, txn_id, op_token, "1通目")
        await db_session.execute(
            update(Message)
            .where(Message.kind == "text")
            .values(created_at=datetime.now(timezone.utc) - timedelta(hours=25))
        )
        await db_session.commit()
        await _post_message(client, txn_id, op_token, "翌日の発言")
    assert [c.kwargs["unread_pending"] for c in dispatch_mock.call_args_list] == [False, False]


async def test_admin_read_does_not_reopen_chat_email(client: AsyncClient, db_session: AsyncSession):
    """運営の閲覧は既読にしない（pdca admin H-2）ため、運営が開いても再送は解禁されない。"""
    txn_id, _case, _user, op_token, admin_token = await _setup_txn(client, db_session, "unread3")
    with patch(_DISPATCH, new=AsyncMock()) as dispatch_mock:
        await _post_message(client, txn_id, op_token, "1通目")
        await client.post(f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(admin_token))
        await _post_message(client, txn_id, op_token, "2通目")
    assert [c.kwargs["unread_pending"] for c in dispatch_mock.call_args_list] == [False, True]


async def test_dispatch_skips_email_when_unread_pending_but_keeps_line(monkeypatch):
    send = AsyncMock(return_value=True)
    push = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.notify.send_message_received", send)
    monkeypatch.setattr("app.services.line_notify.push_message_received", push)
    await notify_dispatch.dispatch_message_received(
        None, "txn-unread-a", "user", email="owner@example.com", unread_pending=True
    )
    send.assert_not_awaited()
    await notify_dispatch.dispatch_message_received(
        "U1", "txn-unread-b", "user", email="owner@example.com", unread_pending=True
    )
    push.assert_awaited_once()
    # LINE が失敗しても、未読がある間はメールへフォールバックしない。
    push.return_value = False
    await notify_dispatch.dispatch_message_received(
        "U1", "txn-unread-c", "user", email="owner@example.com", unread_pending=True
    )
    send.assert_not_awaited()
    # 未読が無ければ従来どおりメールが出る（陽性対照）。
    await notify_dispatch.dispatch_message_received(
        None, "txn-unread-d", "user", email="owner@example.com", unread_pending=False
    )
    send.assert_awaited_once()


# ──────────────────────────── L-5: 運営の依頼者名義キャンセルの拒否 ────────────────────────────


async def test_admin_cannot_cancel_transaction_on_behalf_of_user(client: AsyncClient, db_session: AsyncSession):
    txn_id, _case, _user, _op, admin_token = await _setup_txn(client, db_session, "l5cancel")
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "運営による代理のキャンセル"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "運営はこの操作を代理で行えません。強制終了を使ってください。"
    db_session.expire_all()
    txn = await db_session.scalar(select(Transaction).where(Transaction.id == uuid.UUID(txn_id)))
    assert txn.status != "cancelled"
    assert (await db_session.scalars(select(Cancellation))).all() == []


async def test_owner_can_still_cancel_transaction(client: AsyncClient, db_session: AsyncSession):
    txn_id, _case, user_token, _op, _admin = await _setup_txn(client, db_session, "l5owner")
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "急用のため中止します"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"


# ──────────────────────────── L-6: 口座の全桁開示はキャッシュさせない ────────────────────────────


async def test_bank_account_reveal_response_is_not_cacheable(client: AsyncClient, db_session: AsyncSession):
    _txn, _case, _user, _op, admin_token = await _setup_txn(client, db_session, "l6reveal")
    r = await client.post("/api/v1/operator-applications", json=_application_payload("l6reveal@example.com"))
    assert r.status_code == 201, r.text
    application_id = r.json()["application_id"]
    r = await client.post(
        f"/api/v1/admin/operator-applications/{application_id}/reveal-bank-account",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["pragma"] == "no-cache"


# ──────────────────────────── M-1④: 日次の送信総量の警告 ────────────────────────────


def test_daily_send_counter_warns_with_total_only(monkeypatch, caplog):
    monkeypatch.setattr(notify, "_daily_send_date", None)
    monkeypatch.setattr(notify, "_daily_send_count", 0)
    caplog.set_level(logging.WARNING, logger="app.services.notify")
    for _ in range(150):
        notify._record_daily_send()
    warnings = [r for r in caplog.records if "メール送信数" in r.getMessage()]
    assert len(warnings) == 1
    assert "150 通" in warnings[0].getMessage()
    assert "@" not in warnings[0].getMessage()
    # 日付が変われば数え直す。
    monkeypatch.setattr(notify, "_daily_send_date", datetime(2000, 1, 1, tzinfo=timezone.utc).date())
    notify._record_daily_send()
    assert notify._daily_send_count == 1
