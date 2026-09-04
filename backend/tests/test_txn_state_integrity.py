"""成約まわりの状態整合（r6 監査 M-1〜M-6 / flow ADD-1・ADD-2・H-1・H-2・M-3）の回帰テスト。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_case_cancel.py 等と同様、各テストファイルは自己完結（ヘルパーを
ローカルに複製する既存スタイルを踏襲）。

同時実行そのもの（FOR UPDATE の効き）は SQLite の逐次実行では再現できないため、
ここでは「ロック取得後の再判定で二重適用が起きないこと」「DB制約が張られていること」
「状態ガードが409を返すこと」を検証する。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.bid import Bid
from app.db.models.operator import Operator
from app.db.models.transaction import Cancellation, ReductionRequest, Transaction
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


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="admin@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str = "user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _verified_operator(
    client: AsyncClient,
    admin_token: str,
    email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": company,
            "email": email,
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    op_id = data["operator"]["id"]
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    return data["access_token"], op_id


def _case_payload() -> dict:
    return {
        "purpose": "遺品整理",
        "prefecture": "東京都",
        "city": "世田谷区",
        "address_detail": "桜丘1-2-3 メゾン桜 101号室",
        "housing_type": "マンション",
        "floor_plan": "2LDK",
        "floor_number": 1,
        "has_elevator": False,
        "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0}],
    }


async def _create_case(client: AsyncClient, user_token: str) -> dict:
    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(user_token))
    assert r.status_code == 201, r.text
    return r.json()


async def _bid(client: AsyncClient, op_token: str, case_id: str, amount: int = 30000) -> dict:
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids", json={"amount": amount}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _create_transaction(
    client: AsyncClient, user_token: str, op_token: str, amount: int = 30000
) -> tuple[str, str]:
    """案件作成 → 入札 → 落札まで進め、(case_id, transaction_id) を返す。"""
    case = await _create_case(client, user_token)
    bid = await _bid(client, op_token, case["id"], amount)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return case["id"], r.json()["id"]


# ──────────────── 1. 減額申請のガード（flow ADD-2 / backend M-3） ────────────────


async def test_decide_reduction_rejected_after_completion(
    client: AsyncClient, db_session: AsyncSession
):
    """完了済み取引の減額申請には回答できない（確定額の事後書き換えを防ぐ）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "op1@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 20000, "reason": "想定より荷物が多かったため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    reduction_id = r.json()["id"]

    # pending が残っている間は完了できない（両方向のガードの片側）。
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 409, r.text
    assert "減額申請" in r.json()["detail"]

    # 却下してから完了する。
    r = await client.patch(
        f"/api/v1/transactions/{txn_id}/reduction/{reduction_id}",
        json={"action": "reject"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["final_amount"] == 30000

    # 完了後は（別の申請があっても）回答不可。既存 pending を直接作って検証する。
    stale = ReductionRequest(
        transaction_id=uuid.UUID(txn_id),
        operator_id=(await db_session.scalar(select(Operator.id))),
        original_amount=30000,
        requested_amount=15000,
        reason="完了後に残った未回答申請",
    )
    db_session.add(stale)
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/transactions/{txn_id}/reduction/{stale.id}",
        json={"action": "approve"},
        headers=_auth(user_token),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "回答できる状態ではありません。"

    txn = await db_session.get(Transaction, uuid.UUID(txn_id))
    await db_session.refresh(txn)
    assert txn.final_amount == 30000  # 事後の書き換えが起きていない


async def test_decide_reduction_rejected_after_cancel(
    client: AsyncClient, db_session: AsyncSession
):
    """キャンセル済み取引でも同様に回答できない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "op1@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 20000, "reason": "想定より荷物が多かったため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    reduction_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "都合により中止"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text

    r = await client.patch(
        f"/api/v1/transactions/{txn_id}/reduction/{reduction_id}",
        json={"action": "approve"},
        headers=_auth(user_token),
    )
    assert r.status_code == 409, r.text


# ──────────────── 2. 停止業者の選定禁止（flow ADD-1） ────────────────


async def test_select_bid_rejects_suspended_operator(
    client: AsyncClient, db_session: AsyncSession
):
    """停止中業者の入札は選択できず、入札一覧では operator_suspended=true になる。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _bid(client, op_token, case["id"])

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/suspend",
        json={"suspended": True, "reason": "規約違反の疑い"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    # 依頼者の入札一覧: 除外はせず旗を立てる（web が非表示/選択不可にする契約）。
    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]["operator_suspended"] is True

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 409, r.text
    assert "利用停止中" in r.json()["detail"]

    # 成約は生まれていない（＝操作不能な取引を作らない）。
    assert await db_session.scalar(select(func.count()).select_from(Transaction)) == 0


async def test_select_bid_rejects_deapproved_operator(
    client: AsyncClient, db_session: AsyncSession
):
    """承認取消（vendor_status != active）業者の入札も選択できない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _bid(client, op_token, case["id"])

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    operator.vendor_status = "limited"
    await db_session.commit()

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 409, r.text
    assert await db_session.scalar(select(func.count()).select_from(Transaction)) == 0


# ──────────────── 4. キャンセルの冪等（M-2） ────────────────


async def test_cancel_transaction_twice_is_rejected_without_double_record(
    client: AsyncClient, db_session: AsyncSession
):
    """二重キャンセルは409。Cancellation は1行、cancel_count も1回だけ加算される。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "op1@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    with patch(
        "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_transaction_cancelled",
        new=AsyncMock(),
    ):
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/cancel",
            json={"reason": "訪問できなくなったため"},
            headers=_auth(op_token),
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/cancel",
            json={"reason": "訪問できなくなったため"},
            headers=_auth(op_token),
        )
        assert r.status_code == 409, r.text

    count = await db_session.scalar(
        select(func.count())
        .select_from(Cancellation)
        .where(Cancellation.transaction_id == uuid.UUID(txn_id))
    )
    assert count == 1
    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.cancel_count == 1


async def test_cancellations_unique_per_transaction_at_db_level(
    client: AsyncClient, db_session: AsyncSession
):
    """uq_cancellations_transaction_id が張られている（アプリ層を迂回しても2行入らない）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "op1@example.com")
    case_id, txn_id = await _create_transaction(client, user_token, op_token)

    db_session.add(
        Cancellation(
            case_id=uuid.UUID(case_id),
            transaction_id=uuid.UUID(txn_id),
            cancelled_by="user",
            reason="1件目",
        )
    )
    await db_session.commit()
    db_session.add(
        Cancellation(
            case_id=uuid.UUID(case_id),
            transaction_id=uuid.UUID(txn_id),
            cancelled_by="admin",
            reason="2件目（重複）",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ──────────────── 5. 減額 pending の一意制約（M-4） ────────────────


async def test_reduction_pending_unique_index(client: AsyncClient, db_session: AsyncSession):
    """pending は取引あたり1件（部分一意索引）。回答済みになれば次を作れる。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "op1@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 20000, "reason": "想定より荷物が多かったため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    first_id = r.json()["id"]

    # アプリ層の in-memory 判定（同一セッションのテストではこちらが先に効く）。
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 19000, "reason": "さらに減額したいため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text

    # DB制約（アプリ層を迂回しても2行目の pending は入らない）。
    db_session.add(
        ReductionRequest(
            transaction_id=uuid.UUID(txn_id),
            operator_id=uuid.UUID(op_id),
            original_amount=30000,
            requested_amount=18000,
            reason="制約検証用の2件目",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 回答済み（rejected）になれば次の申請を作れる＝業者が恒久ブロックされない。
    r = await client.patch(
        f"/api/v1/transactions/{txn_id}/reduction/{first_id}",
        json={"action": "reject"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 19000, "reason": "再度の減額申請を行います"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text


# ──────────────── 7. GET /transactions の limit/offset（ADD-2） ────────────────


async def test_list_transactions_limit_offset(client: AsyncClient, db_session: AsyncSession):
    """応答形状は配列のまま。limit/offset が効き、上限超過は422で弾かれる。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "op1@example.com")
    for _ in range(3):
        await _create_transaction(client, user_token, op_token)

    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3

    r = await client.get("/api/v1/transactions?limit=2", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    page1 = r.json()
    assert len(page1) == 2
    r = await client.get("/api/v1/transactions?limit=2&offset=2", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    page2 = r.json()
    assert len(page2) == 1
    assert {t["id"] for t in page1}.isdisjoint({t["id"] for t in page2})

    r = await client.get("/api/v1/transactions?limit=999", headers=_auth(user_token))
    assert r.status_code == 422, r.text


# ──────────────── 9・10. operator_suspended / unread_count ────────────────


async def test_transaction_detail_exposes_operator_suspended(
    client: AsyncClient, db_session: AsyncSession
):
    """成約後に業者が停止されたら、依頼者の取引詳細に operator_suspended=true が出る。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "op1@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["operator_suspended"] is False

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/suspend",
        json={"suspended": True, "reason": "規約違反の疑い"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["operator_suspended"] is True


async def test_list_transactions_unread_count(client: AsyncClient, db_session: AsyncSession):
    """一覧に未読数が入り、既読化すると 0 に戻る（相手の発言のみ数える）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "op1@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    with patch(
        "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
        new=AsyncMock(),
    ):
        for body in ("到着時刻のご相談です", "ご都合はいかがでしょうか"):
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": body},
                headers=_auth(op_token),
            )
            assert r.status_code == 201, r.text

    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()[0]["unread_count"] == 2

    # 送信者自身（業者）から見た未読は 0。
    r = await client.get("/api/v1/transactions", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.json()[0]["unread_count"] == 0

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(user_token)
    )
    assert r.status_code == 200, r.text
    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()[0]["unread_count"] == 0


# ──────────────── 8. 退会時の暗黙キャンセル（flow H-1） ────────────────


async def test_withdrawal_cancels_open_case_like_cancel_case(
    client: AsyncClient, db_session: AsyncSession
):
    """退会でも pending 入札の却下・Cancellation 記録・落選通知が行われる。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    await _bid(client, op_token, case["id"])

    dispatch = AsyncMock()
    with patch(
        "app.api.v1.endpoints.users.notify_dispatch.dispatch_bid_lost", new=dispatch
    ):
        r = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"confirm": True, "password": "password123"},
            headers=_auth(user_token),
        )
        assert r.status_code == 200, r.text

    bid_row = await db_session.scalar(select(Bid).where(Bid.case_id == uuid.UUID(case["id"])))
    await db_session.refresh(bid_row)
    assert bid_row.status == "rejected"

    cancellation = await db_session.scalar(
        select(Cancellation).where(Cancellation.case_id == uuid.UUID(case["id"]))
    )
    assert cancellation is not None
    assert cancellation.cancelled_by == "user"
    assert cancellation.transaction_id is None

    dispatch.assert_awaited_once()
    assert dispatch.await_args.args[2] == case["id"]
