"""``入札取り下げ``（業者による POST /bids/{id}/withdraw）機能は廃止済み。

本ファイルは、廃止後も本番DBに残存する過去データ（status='withdrawn' の bids
行・bid_withdrawals 監査行）との表示・集計整合性を守るための回帰テストのみを
保持する（設計指示に基づく。エンドポイント自体の存在を前提にしたテストは
全て削除済み）。withdrawn 行は POST エンドポイント経由ではなく、DB に
直接 INSERT（``session.add`` で status='withdrawn' の ``Bid`` を作成）して
再現する。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_katadzuke_api.py / test_case_items.py と同様、各テストファイルは
自己完結（ヘルパーをローカルに複製する既存スタイルを踏襲）。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.bid import BID_STATUS_WITHDRAWN, Bid, BidWithdrawal
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


async def _signup_user(client: AsyncClient, email: str = "user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    from app.db.models.user import User

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
    assert r.status_code == 200
    return r.json()["access_token"]


async def _invite_code(client: AsyncClient, admin_token: str) -> str:
    r = await client.post(
        "/api/v1/admin/invites", json={}, headers=_auth(admin_token)
    )
    assert r.status_code == 201
    return r.json()["code"]


async def _verified_operator(
    client: AsyncClient, db_session: AsyncSession, admin_token: str, email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    code = await _invite_code(client, admin_token)
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
    token, op_id = data["access_token"], data["operator"]["id"]
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    return token, op_id


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
        "photos": [
            {"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0},
            {"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 1},
        ],
    }


async def _create_case(client: AsyncClient, user_token: str) -> dict:
    r = await client.post(
        "/api/v1/cases", json=_case_payload(), headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _create_bid(
    client: AsyncClient, case_id: str, op_token: str, amount: int = 50000
) -> dict:
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": amount},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _mark_withdrawn(db_session: AsyncSession, bid_id: str) -> None:
    """POST /withdraw エンドポイントが廃止されたため、過去データを模して
    DBに直接 status='withdrawn' を書き込む（本番に残存するレガシー行の再現）。
    """
    bid = await db_session.get(Bid, uuid.UUID(bid_id))
    assert bid is not None
    bid.status = BID_STATUS_WITHDRAWN
    await db_session.commit()


# ──────────────────────────── 集計（bid_count / top_bid_amount からの除外） ────────────────────────────


async def test_withdrawn_bid_excluded_from_bid_count_and_top_bid_amount(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "op2@example.com", "B社")
    case = await _create_case(client, user_token)
    await _create_bid(client, case["id"], op1_token, amount=40000)
    bid2 = await _create_bid(client, case["id"], op2_token, amount=55000)

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.json()["bid_count"] == 2

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(op1_token))
    assert r.json()["top_bid_amount"] == 55000

    # 最高額(55000)を提示していたop2の入札が過去にwithdrawnになっているケースを再現。
    await _mark_withdrawn(db_session, bid2["id"])

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.status_code == 200
    body = r.json()
    assert body["bid_count"] == 1

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(op1_token))
    assert r.status_code == 200
    body = r.json()
    assert body["top_bid_amount"] == 40000
    assert body["bid_count"] == 1


# ──────────────────────────── 再入札拒否 ────────────────────────────


async def test_rebid_after_bid_withdrawn_rejected_409(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)
    await _mark_withdrawn(db_session, bid["id"])

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 60000},
        headers=_auth(op_token),
    )
    assert r.status_code == 409
    assert "取り下げ済み" in r.json()["detail"]


# ──────────────────────────── select連携 ────────────────────────────


async def test_select_withdrawn_bid_409(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "op2@example.com", "B社")
    case = await _create_case(client, user_token)
    bid1 = await _create_bid(client, case["id"], op1_token, amount=40000)
    await _create_bid(client, case["id"], op2_token, amount=50000)
    await _mark_withdrawn(db_session, bid1["id"])

    # op2がpendingで残っているため案件はbiddingのまま。withdrawn済みbidを選ぼうとすると409。
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid1['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 409


# ──────────────────────────── スキーマ整合性 ────────────────────────────


async def test_bid_status_check_constraint_rejects_bogus_value(
    client: AsyncClient, db_session: AsyncSession
):
    """ORMの CheckConstraint（ck_bids_status）がテスト環境（SQLite）でも
    有効であることを確認する。DB側のCHECK制約（alembic 0018）とORMメタデータが
    乖離すると、この検知が働かなくなる（bid.py の __table_args__ 参照）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)

    bogus_bid = Bid(
        case_id=uuid.UUID(case["id"]),
        operator_id=uuid.UUID(op_id),
        amount=10000,
        status="bogus",
    )
    db_session.add(bogus_bid)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ──────────────────────────── 監査証跡（一意制約） ────────────────────────────


async def test_bid_withdrawal_unique_per_bid_rejected_by_db(
    client: AsyncClient, db_session: AsyncSession
):
    """「1入札につき取り下げ監査行は1回」をDB側の一意制約
    （uq_bid_withdrawals_bid_id）でも保証することを確認する（多層防御。
    エンドポイント廃止後も過去データに対する制約自体は維持する）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token, amount=73000)
    await _mark_withdrawn(db_session, bid["id"])

    db_session.add(
        BidWithdrawal(
            bid_id=uuid.UUID(bid["id"]),
            case_id=uuid.UUID(case["id"]),
            operator_id=uuid.UUID(op_id),
            company_name="テスト片付け株式会社",
            amount=73000,
        )
    )
    await db_session.commit()

    db_session.add(
        BidWithdrawal(
            bid_id=uuid.UUID(bid["id"]),
            case_id=uuid.UUID(case["id"]),
            operator_id=uuid.UUID(op_id),
            company_name="テスト片付け株式会社",
            amount=73000,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ──────────────────────────── list_bidsの依頼者向けフィルタ ────────────────────────────


async def test_list_bids_excludes_withdrawn_for_case_owner(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "op2@example.com", "B社")
    case = await _create_case(client, user_token)
    bid1 = await _create_bid(client, case["id"], op1_token, amount=40000)
    await _create_bid(client, case["id"], op2_token, amount=50000)
    await _mark_withdrawn(db_session, bid1["id"])

    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(user_token))
    assert r.status_code == 200
    statuses = [b["status"] for b in r.json()]
    assert "withdrawn" not in statuses
    assert len(statuses) == 1


async def test_list_bids_admin_includes_withdrawn(
    client: AsyncClient, db_session: AsyncSession
):
    """依頼者本人ではなくadminが他人の案件を閲覧する場合は、監査・自社確認用途の
    ため取り下げ済み入札も含め全件返す（依頼者本人向けフィルタとは区別する）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)
    await _mark_withdrawn(db_session, bid["id"])

    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(admin_token))
    assert r.status_code == 200
    statuses = [b["status"] for b in r.json()]
    assert statuses == ["withdrawn"]


# ──────────────────────────── Case行ロック共有（create_bid / select_bid 回帰） ────────────────────────────


async def test_create_bid_for_nonexistent_case_still_404(
    client: AsyncClient, db_session: AsyncSession
):
    """create_bid が select_bid / cancel_case と同じ ``lock_case_row``
    （app.services.case_lock）に参加していても、存在しない案件に対しては
    通常どおり404を返すことを確認する（共有ロックによるリグレッション防止。
    存在しないPKに対する SELECT ... FOR UPDATE は0行ロックとしてエラーに
    ならず、後続の _get_case が404を送出する想定）。
    """
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    random_case_id = uuid.uuid4()

    r = await client.post(
        f"/api/v1/cases/{random_case_id}/bids",
        json={"amount": 10000},
        headers=_auth(op_token),
    )
    assert r.status_code == 404


async def test_select_other_users_case_403_without_locking(
    client: AsyncClient, db_session: AsyncSession
):
    """select_bid は認可判定（案件の所有権確認）より前にCase行の排他ロックを
    取得してはならない（他人のcase_idを大量に送りつけるロック争奪DoSを防ぐ
    ため）。他人の案件への select 試行が403になることに加え、
    ``app.services.case_lock.lock_case_row``（旧 bids.py 内 private
    ``_lock_case_row``。cancel_case 新設に伴い共有モジュールへ移設済み）が
    一切呼ばれていないことを確認する。
    """
    admin_token = await _make_admin(client, db_session)
    owner_token = await _signup_user(client, "owner@example.com")
    other_token = await _signup_user(client, "other@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, owner_token)
    bid = await _create_bid(client, case["id"], op_token)

    with patch(
        "app.api.v1.endpoints.bids.lock_case_row", new=AsyncMock()
    ) as lock_mock:
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
            headers=_auth(other_token),
        )
    assert r.status_code == 403
    lock_mock.assert_not_called()
