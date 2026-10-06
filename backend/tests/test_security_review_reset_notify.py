"""security review（パスワード再設定の追加修正）の回帰テスト — 再設定以外の経路。

- L-5: 運営は依頼者名義で取引をキャンセルできない（強制終了を使う）。
- L-6: 口座の全桁開示の応答はキャッシュさせない。

パスワード再設定そのもの（並存・送信回数・管理者・完了通知・L-1）は tests/test_password_reset.py。
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.transaction import Cancellation, Transaction
from tests.test_katadzuke_api import _application_payload
from tests.test_line_user_notify import (  # noqa: F401 -- fixture（autouse 含む）として使う
    _auth,
    _reset_message_push_ledger,
    client,
)
from tests.test_pdca_ba_findings import _setup_txn

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

