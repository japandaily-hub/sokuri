"""入札の引き上げ（``PATCH /cases/{case_id}/bids/me``）の統合テスト。

対象:
- 1案件1業者1入札の一意制約（uq_bids_case_operator）と封印入札は維持したまま、
  自社の入札額を現在額より高い金額へ何度でも引き上げられること（下げ・同額は409）。
- 引き上げの都度 bid_amount_history に1行追加され、bids.revision_count が加算されること。
- 依頼者への通知（notify_dispatch.dispatch_bid_updated）が
  (line_user_id, email, case_id, company_name, old_amount, new_amount) で呼ばれること。
- 未入札/終端状態(selected/withdrawn)/案件closed/連絡先混入メッセージ/認可（依頼者トークン・
  未承認業者）が期待通り拒否されること。

フィクスチャの作法は tests/test_r12_backend_fixes.py と同じ
（in-memory SQLite + ASGITransport をローカルに複製する）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import create_access_token, hash_password
from app.db.models.bid import (
    BID_STATUS_PENDING,
    BID_STATUS_SELECTED,
    BID_STATUS_WITHDRAWN,
    Bid,
    BidAmountHistory,
)
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session


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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(db_session: AsyncSession, email: str) -> tuple[User, str]:
    user = User(email=email, password_hash=hash_password("userpass123"), name="依頼者")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, create_access_token(user.id, "user", "user")


async def _make_operator(
    db_session: AsyncSession,
    email: str,
    *,
    vendor_status: str = "active",
    company: str = "A社",
) -> tuple[Operator, str]:
    operator = Operator(
        company_name=company,
        contact_email=email,
        password_hash=hash_password("operatorpass1"),
        vendor_status=vendor_status,
    )
    db_session.add(operator)
    await db_session.commit()
    await db_session.refresh(operator)
    return operator, create_access_token(operator.id, "operator", "operator")


async def _make_case(db_session: AsyncSession, user: User, *, status: str = "bidding") -> Case:
    case = Case(
        user_id=user.id,
        purpose="遺品整理",
        status=status,
        prefecture="東京都",
        city="世田谷区",
        address_detail="桜丘1-2-3",
    )
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)
    return case


async def _make_bid(
    db_session: AsyncSession,
    case: Case,
    operator: Operator,
    *,
    amount: int = 30000,
    status: str = BID_STATUS_PENDING,
    message: str | None = None,
) -> Bid:
    bid = Bid(
        case_id=case.id, operator_id=operator.id, amount=amount, status=status, message=message
    )
    db_session.add(bid)
    await db_session.commit()
    await db_session.refresh(bid)
    return bid


# ──────────────────────────── 引き上げ成功 ────────────────────────────


async def test_raise_bid_updates_amount_and_notifies_owner(
    client: AsyncClient, db_session: AsyncSession
):
    user, _ = await _make_user(db_session, "raise_owner@example.com")
    operator, op_token = await _make_operator(db_session, "raise_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    with patch(
        "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_updated", new=AsyncMock()
    ) as dispatch_mock:
        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": 40000, "message": "上乗せいたします"},
            headers=_auth(op_token),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 40000
    assert body["message"] == "上乗せいたします"
    assert body["revision_count"] == 1
    assert body["status"] == "pending"

    dispatch_mock.assert_awaited_once_with(
        user.line_user_id, user.email, str(case.id), operator.company_name, 30000, 40000
    )

    rows = (
        (await db_session.execute(select(BidAmountHistory)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].old_amount == 30000
    assert rows[0].new_amount == 40000


async def test_raise_bid_twice_accumulates_history_and_revision_count(
    client: AsyncClient, db_session: AsyncSession
):
    user, _ = await _make_user(db_session, "raise2_owner@example.com")
    operator, op_token = await _make_operator(db_session, "raise2_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=10000)

    with patch(
        "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_updated", new=AsyncMock()
    ):
        r1 = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": 20000},
            headers=_auth(op_token),
        )
        assert r1.status_code == 200, r1.text
        r2 = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": 25000},
            headers=_auth(op_token),
        )
        assert r2.status_code == 200, r2.text

    assert r2.json()["revision_count"] == 2
    rows = (await db_session.execute(select(BidAmountHistory))).scalars().all()
    assert len(rows) == 2


# ──────────────────────────── 拒否系 ────────────────────────────


async def test_raise_bid_same_amount_rejected_409(client: AsyncClient, db_session: AsyncSession):
    user, _ = await _make_user(db_session, "same_owner@example.com")
    operator, op_token = await _make_operator(db_session, "same_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 30000},
        headers=_auth(op_token),
    )
    assert r.status_code == 409
    assert "30,000" in r.json()["detail"]


async def test_raise_bid_lower_amount_rejected_409(client: AsyncClient, db_session: AsyncSession):
    user, _ = await _make_user(db_session, "lower_owner@example.com")
    operator, op_token = await _make_operator(db_session, "lower_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 29999},
        headers=_auth(op_token),
    )
    assert r.status_code == 409


async def test_raise_bid_below_min_step_rejected_409(
    client: AsyncClient, db_session: AsyncSession
):
    """security review High指摘対応: 最小引き上げ幅（1,000円）未満は409。"""
    user, _ = await _make_user(db_session, "minstep_owner@example.com")
    operator, op_token = await _make_operator(db_session, "minstep_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 30500},
        headers=_auth(op_token),
    )
    assert r.status_code == 409
    assert "1,000円以上高い金額を指定してください" in r.json()["detail"]

    # ちょうど最小幅（+1,000円）は成功する。
    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 31000},
        headers=_auth(op_token),
    )
    assert r.status_code == 200, r.text


async def test_raise_bid_revision_limit_rejected_409(
    client: AsyncClient, db_session: AsyncSession
):
    """security review High指摘対応: 引き上げ回数の上限（20回）到達で409。"""
    user, _ = await _make_user(db_session, "revlimit_owner@example.com")
    operator, op_token = await _make_operator(db_session, "revlimit_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=10000)

    amount = 10000
    with patch(
        "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_updated", new=AsyncMock()
    ):
        for _ in range(20):
            amount += 1000
            r = await client.patch(
                f"/api/v1/cases/{case.id}/bids/me",
                json={"amount": amount},
                headers=_auth(op_token),
            )
            assert r.status_code == 200, r.text
        assert r.json()["revision_count"] == 20

        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": amount + 1000},
            headers=_auth(op_token),
        )
    assert r.status_code == 409
    assert "上限（20回）に達しました" in r.json()["detail"]


async def test_raise_bid_message_omitted_preserves_existing_message(
    client: AsyncClient, db_session: AsyncSession
):
    """security review Medium指摘対応: message を省略した場合は既存メッセージを維持する。"""
    user, _ = await _make_user(db_session, "msgkeep_owner@example.com")
    operator, op_token = await _make_operator(db_session, "msgkeep_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000, message="既存メッセージ")

    with patch(
        "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_updated", new=AsyncMock()
    ):
        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": 40000},
            headers=_auth(op_token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "既存メッセージ"

    rows = (await db_session.execute(select(BidAmountHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].new_message == "既存メッセージ"


async def test_raise_bid_message_null_clears_existing_message(
    client: AsyncClient, db_session: AsyncSession
):
    """security review Medium指摘対応: message を null で明示すればクリアされる。"""
    user, _ = await _make_user(db_session, "msgclear_owner@example.com")
    operator, op_token = await _make_operator(db_session, "msgclear_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000, message="既存メッセージ")

    with patch(
        "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_updated", new=AsyncMock()
    ):
        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": 40000, "message": None},
            headers=_auth(op_token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["message"] is None



async def test_raise_bid_without_existing_bid_404(client: AsyncClient, db_session: AsyncSession):
    user, _ = await _make_user(db_session, "nobid_owner@example.com")
    _, op_token = await _make_operator(db_session, "nobid_op@example.com")
    case = await _make_case(db_session, user)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 10000},
        headers=_auth(op_token),
    )
    assert r.status_code == 404


async def test_raise_selected_bid_rejected_409(client: AsyncClient, db_session: AsyncSession):
    user, _ = await _make_user(db_session, "selected_owner@example.com")
    operator, op_token = await _make_operator(db_session, "selected_op@example.com")
    case = await _make_case(db_session, user, status="closed")
    await _make_bid(db_session, case, operator, amount=30000, status=BID_STATUS_SELECTED)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 40000},
        headers=_auth(op_token),
    )
    assert r.status_code == 409


async def test_raise_withdrawn_bid_rejected_409_with_specific_message(
    client: AsyncClient, db_session: AsyncSession
):
    user, _ = await _make_user(db_session, "withdrawn_owner@example.com")
    operator, op_token = await _make_operator(db_session, "withdrawn_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000, status=BID_STATUS_WITHDRAWN)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 40000},
        headers=_auth(op_token),
    )
    assert r.status_code == 409
    assert "取り下げ済み" in r.json()["detail"]


async def test_raise_bid_on_closed_case_rejected_409(
    client: AsyncClient, db_session: AsyncSession
):
    user, _ = await _make_user(db_session, "closedcase_owner@example.com")
    operator, op_token = await _make_operator(db_session, "closedcase_op@example.com")
    case = await _make_case(db_session, user, status="closed")
    await _make_bid(db_session, case, operator, amount=30000, status=BID_STATUS_PENDING)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 40000},
        headers=_auth(op_token),
    )
    assert r.status_code == 409
    assert "受け付けていません" in r.json()["detail"]


async def test_raise_bid_with_contact_info_message_rejected_422(
    client: AsyncClient, db_session: AsyncSession
):
    user, _ = await _make_user(db_session, "contact_owner@example.com")
    operator, op_token = await _make_operator(db_session, "contact_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 40000, "message": "090-1234-5678までご連絡ください"},
        headers=_auth(op_token),
    )
    assert r.status_code == 422
    assert "連絡先" in r.json()["detail"]

    # 422時にDB副作用が残らないこと（金額・revision_countが据え置き）の回帰保証。
    rows = (await db_session.execute(select(Bid).where(Bid.case_id == case.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].amount == 30000
    assert rows[0].revision_count == 0


async def test_raise_bid_rejects_user_token_401_and_unapproved_operator_403(
    client: AsyncClient, db_session: AsyncSession
):
    user, user_token = await _make_user(db_session, "authcheck_owner@example.com")
    operator, _ = await _make_operator(db_session, "authcheck_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    # 依頼者（userロール）のトークンでは業者専用エンドポイントの認証に失敗する。
    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 40000},
        headers=_auth(user_token),
    )
    assert r.status_code == 401

    # 未承認業者（vendor_status=pending）は 403。
    pending_operator, pending_token = await _make_operator(
        db_session, "authcheck_pending_op@example.com", vendor_status="pending", company="B社"
    )
    await _make_bid(db_session, case, pending_operator, amount=25000)
    r = await client.patch(
        f"/api/v1/cases/{case.id}/bids/me",
        json={"amount": 26000},
        headers=_auth(pending_token),
    )
    assert r.status_code == 403


# ──────────── security review Low指摘対応: 停止処理との競合の再検証 ────────────
#
# get_verified_operator は依存性解決時点のスナップショットでしか is_suspended /
# deleted_at を判定できないため、update_my_bid 本体は Case行ロックの直後に自社
# Operator行を再ロック・再検証する。単一セッションの同期テストでは真の
# 同時実行レースを再現できないため、``lock_operator_row`` をモックして
# 「ロック取得の瞬間に停止／退会が確定した」状況を再現する（本文コードの
# 再検証ロジック自体が確かに機能することの検証に閉じる）。


async def test_raise_bid_rechecks_suspension_after_lock_403(
    client: AsyncClient, db_session: AsyncSession
):
    """Case行ロック後に停止が確定していた場合、SUSPENDED_ACCOUNT_DETAIL 形式の403。"""
    user, _ = await _make_user(db_session, "racecheck_susp_owner@example.com")
    operator, op_token = await _make_operator(db_session, "racecheck_susp_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    async def _fake_lock_operator_row(session, operator_id):
        # ロック取得の瞬間に運営の停止処理が完了していた状況を模す。
        operator.is_suspended = True
        await session.commit()
        return None

    with patch(
        "app.api.v1.endpoints.bids.lock_operator_row", side_effect=_fake_lock_operator_row
    ):
        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": 40000},
            headers=_auth(op_token),
        )
    assert r.status_code == 403
    assert r.json()["detail"] == {
        "code": "account_suspended",
        "message": "このアカウントは利用停止中です。お問い合わせ窓口までご連絡ください。",
    }

    # 副作用（金額・revision_count）が残らないこと。
    rows = (await db_session.execute(select(Bid).where(Bid.case_id == case.id))).scalars().all()
    assert rows[0].amount == 30000
    assert rows[0].revision_count == 0


async def test_raise_bid_rechecks_deletion_after_lock_401(
    client: AsyncClient, db_session: AsyncSession
):
    """Case行ロック後に退会が確定していた場合、401（get_current_operatorと同一契約）。"""
    user, _ = await _make_user(db_session, "racecheck_del_owner@example.com")
    operator, op_token = await _make_operator(db_session, "racecheck_del_op@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)

    with patch(
        "app.api.v1.endpoints.bids.lock_operator_row",
        new=AsyncMock(return_value=datetime.now(timezone.utc)),
    ):
        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me",
            json={"amount": 40000},
            headers=_auth(op_token),
        )
    assert r.status_code == 401


async def test_create_bid_duplicate_error_message_mentions_raise_flow(
    client: AsyncClient, db_session: AsyncSession
):
    """既存入札への重複POSTは、引き上げ導線への案内文言を含む409になる（r13対応）。"""
    user, _ = await _make_user(db_session, "dup_owner@example.com")
    operator, op_token = await _make_operator(db_session, "dup_op@example.com")
    case = await _make_case(db_session, user, status="open")
    await _make_bid(db_session, case, operator, amount=30000)

    r = await client.post(
        f"/api/v1/cases/{case.id}/bids",
        json={"amount": 40000},
        headers=_auth(op_token),
    )
    assert r.status_code == 409
    assert "引き上げ" in r.json()["detail"]


# ──────────────────────────── 通知は「首位になった時だけ」（QA M4） ────────────────────────────


async def test_raise_notifies_owner_only_when_bid_becomes_top(
    client: AsyncClient, db_session: AsyncSession
):
    """他社が 50,000 の案件で 30,000→40,000（首位に届かない）は通知しない。
    40,000→60,000（首位になる）は通知する。60,000→70,000（首位のまま上乗せ）は通知しない。"""
    user, _ = await _make_user(db_session, "top_owner@example.com")
    operator, op_token = await _make_operator(db_session, "top_op@example.com")
    rival, _ = await _make_operator(db_session, "top_rival@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=30000)
    await _make_bid(db_session, case, rival, amount=50000)

    with patch(
        "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_updated", new=AsyncMock()
    ) as dispatch_mock:
        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me", json={"amount": 40000}, headers=_auth(op_token)
        )
        assert r.status_code == 200, r.text
        assert dispatch_mock.await_count == 0

        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me", json={"amount": 60000}, headers=_auth(op_token)
        )
        assert r.status_code == 200, r.text
        assert dispatch_mock.await_count == 1
        assert dispatch_mock.await_args.args[4:] == (40000, 60000)

        r = await client.patch(
            f"/api/v1/cases/{case.id}/bids/me", json={"amount": 70000}, headers=_auth(op_token)
        )
        assert r.status_code == 200, r.text
        assert dispatch_mock.await_count == 1

    # 履歴は通知の有無に関わらず全件残る
    rows = (await db_session.execute(select(BidAmountHistory))).scalars().all()
    assert [(h.old_amount, h.new_amount) for h in rows] == [
        (30000, 40000),
        (40000, 60000),
        (60000, 70000),
    ]


async def test_withdrawn_own_bid_is_not_treated_as_top_bidder(
    client: AsyncClient, db_session: AsyncSession
):
    """取り下げ済みの自社入札（高額）が残っていても is_top_bidder は None（QA M3）。"""
    user, _ = await _make_user(db_session, "wd_owner@example.com")
    operator, op_token = await _make_operator(db_session, "wd_op@example.com")
    rival, _ = await _make_operator(db_session, "wd_rival@example.com")
    case = await _make_case(db_session, user)
    await _make_bid(db_session, case, operator, amount=90000, status="withdrawn")
    await _make_bid(db_session, case, rival, amount=50000)

    r = await client.get(f"/api/v1/cases/{case.id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["top_bid_amount"] == 50000
    assert body["is_top_bidder"] is None
    assert body["my_bid"]["status"] == "withdrawn"
