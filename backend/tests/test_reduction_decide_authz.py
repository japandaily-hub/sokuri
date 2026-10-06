"""減額申請の承認・却下の認可と行ロック（最終レビュー security M-1）。

固定する契約:
- 運営（所有者でない管理者）は依頼者名義で承認・却下できない（403・申請は pending のまま・
  final_amount も変わらない・業者への通知も出ない）。
- 依頼者本人以外の利用者は従来どおり 403「この成約への権限がありません。」。
- 依頼者本人は承認できる。承認・却下は Case → Transaction の行ロックの下で行う
  （complete / cancel と同じ lock_transaction_rows を通る）。
- 存在しない取引は 404。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import reductions as reductions_module
from app.db.models.transaction import ReductionRequest, Transaction
from tests.test_txn_state_integrity import (
    _auth,
    _create_transaction,
    _make_admin,
    _signup_user,
    _verified_operator,
    create_test_app,
)

_ADMIN_DETAIL = "運営は依頼者に代わって減額の可否を決められません。依頼者本人が操作してください。"


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_test_app(db_session)), base_url="http://test"
    ) as ac:
        yield ac


async def _setup(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "op_red@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 20000, "reason": "想定より荷物が多かったため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    return admin_token, user_token, txn_id, r.json()["id"]


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_admin_cannot_decide_reduction_on_behalf_of_owner(
    client: AsyncClient, db_session: AsyncSession, action: str
):
    admin_token, _, txn_id, reduction_id = await _setup(client, db_session)
    with patch.object(
        reductions_module.notify_dispatch, "dispatch_reduction_decided", new=AsyncMock()
    ) as notify_mock:
        r = await client.patch(
            f"/api/v1/transactions/{txn_id}/reduction/{reduction_id}",
            json={"action": action},
            headers=_auth(admin_token),
        )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == _ADMIN_DETAIL
    notify_mock.assert_not_called()

    db_session.expire_all()
    reduction = await db_session.get(ReductionRequest, uuid.UUID(reduction_id))
    assert reduction.status == "pending"
    txn = await db_session.get(Transaction, uuid.UUID(txn_id))
    assert txn.final_amount is None or txn.final_amount == 30000


async def test_other_user_cannot_decide_reduction(client: AsyncClient, db_session: AsyncSession):
    _, _, txn_id, reduction_id = await _setup(client, db_session)
    stranger_token = await _signup_user(client, email="stranger@example.com")
    r = await client.patch(
        f"/api/v1/transactions/{txn_id}/reduction/{reduction_id}",
        json={"action": "approve"},
        headers=_auth(stranger_token),
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "この成約への権限がありません。"


async def test_owner_decides_under_transaction_row_lock(
    client: AsyncClient, db_session: AsyncSession
):
    _, user_token, txn_id, reduction_id = await _setup(client, db_session)
    real_lock = reductions_module.lock_transaction_rows
    lock_spy = AsyncMock(side_effect=real_lock)
    with patch.object(reductions_module, "lock_transaction_rows", new=lock_spy):
        r = await client.patch(
            f"/api/v1/transactions/{txn_id}/reduction/{reduction_id}",
            json={"action": "approve"},
            headers=_auth(user_token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    lock_spy.assert_awaited_once()
    assert lock_spy.await_args.args[1] == uuid.UUID(txn_id)

    db_session.expire_all()
    txn = await db_session.get(Transaction, uuid.UUID(txn_id))
    assert txn.final_amount == 20000


async def test_decide_reduction_unknown_transaction_is_404(
    client: AsyncClient, db_session: AsyncSession
):
    _, user_token, _, reduction_id = await _setup(client, db_session)
    r = await client.patch(
        f"/api/v1/transactions/{uuid.uuid4()}/reduction/{reduction_id}",
        json={"action": "approve"},
        headers=_auth(user_token),
    )
    assert r.status_code == 404, r.text
