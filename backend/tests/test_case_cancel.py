"""出品取り下げ（POST /cases/{case_id}/cancel）機能の統合テスト。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_bid_withdrawn_legacy.py 等と同様、各テストファイルは自己完結
（ヘルパーをローカルに複製する既存スタイルを踏襲）。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import get_rate_limiter
from app.api.v1.router import api_router
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
)
from app.core.security import hash_password
from app.db.models.case import Case
from app.db.models.transaction import Cancellation
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


async def _signup_user(client: AsyncClient, email: str = "user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


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


def _cancel_url(case_id: str) -> str:
    return f"/api/v1/cases/{case_id}/cancel"


# ──────────────────────────── 正常系 ────────────────────────────


async def test_cancel_open_case_returns_200_and_status_cancelled(
    client: AsyncClient, db_session: AsyncSession
):
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)

    r = await client.post(
        _cancel_url(case["id"]), json={"reason": "気が変わった"}, headers=_auth(user_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    cancellations = (
        await db_session.scalars(
            select(Cancellation).where(Cancellation.case_id == uuid.UUID(case["id"]))
        )
    ).all()
    assert len(cancellations) == 1
    cancellation = cancellations[0]
    assert cancellation.cancelled_by == "user"
    assert cancellation.transaction_id is None
    assert cancellation.reason == "気が変わった"


async def test_cancel_bidding_case_rejects_pending_bids_and_notifies(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "op2@example.com", "B社")
    case = await _create_case(client, user_token)
    await _create_bid(client, case["id"], op1_token, amount=40000)
    await _create_bid(client, case["id"], op2_token, amount=50000)

    with patch(
        "app.api.v1.endpoints.cases.notify_dispatch.dispatch_bid_lost", new=AsyncMock()
    ) as dispatch_mock:
        r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert dispatch_mock.call_count == 2

    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(admin_token))
    assert r.status_code == 200
    statuses = [b["status"] for b in r.json()]
    assert statuses == ["rejected", "rejected"]


# ──────────────────────────── 認可 ────────────────────────────


async def test_cancel_other_users_case_403(client: AsyncClient, db_session: AsyncSession):
    owner_token = await _signup_user(client, "owner@example.com")
    other_token = await _signup_user(client, "other@example.com")
    case = await _create_case(client, owner_token)

    r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(other_token))
    assert r.status_code == 403


async def test_cancel_other_users_case_403_without_locking(
    client: AsyncClient, db_session: AsyncSession
):
    """他人の案件に対する cancel は Case 行ロック取得前に 403 で弾かれること
    （ロック争奪 DoS 対策の回帰テスト。select_bid 側の同種テストと対）。
    lock_case_row の関数名を変更する場合はこのテストも合わせて更新すること。
    """
    owner_token = await _signup_user(client, "owner@example.com")
    other_token = await _signup_user(client, "other@example.com")
    case = await _create_case(client, owner_token)

    with patch("app.api.v1.endpoints.cases.lock_case_row", new=AsyncMock()) as lock_mock:
        r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(other_token))
    assert r.status_code == 403
    lock_mock.assert_not_called()


async def test_cancel_unauthenticated_401(client: AsyncClient, db_session: AsyncSession):
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)

    r = await client.post(_cancel_url(case["id"]), json={})
    assert r.status_code == 401


async def test_cancel_as_operator_401_or_403(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)

    r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(op_token))
    assert r.status_code in (401, 403)


# ──────────────────────────── 状態ガード ────────────────────────────


async def test_cancel_draft_case_409(client: AsyncClient, db_session: AsyncSession):
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)
    case_obj = await db_session.get(Case, uuid.UUID(case["id"]))
    assert case_obj is not None
    case_obj.status = "draft"
    await db_session.commit()

    r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r.status_code == 409


async def test_cancel_closed_case_409_guides_to_transaction_cancel(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text

    r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r.status_code == 409
    assert "取引" in r.json()["detail"]


async def test_cancel_already_cancelled_case_409(client: AsyncClient, db_session: AsyncSession):
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)

    r1 = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r1.status_code == 200

    r2 = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r2.status_code == 409
    assert "既に取り下げ済み" in r2.json()["detail"]


# ──────────────────────────── リクエストボディ ────────────────────────────


async def test_cancel_without_reason_succeeds(client: AsyncClient, db_session: AsyncSession):
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)

    r = await client.post(_cancel_url(case["id"]), json={"reason": None}, headers=_auth(user_token))
    assert r.status_code == 200, r.text


async def test_cancel_reason_too_long_422(client: AsyncClient, db_session: AsyncSession):
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)

    r = await client.post(
        _cancel_url(case["id"]), json={"reason": "あ" * 2001}, headers=_auth(user_token)
    )
    assert r.status_code == 422


# ──────────────────────────── レート制限 ────────────────────────────


async def test_cancel_rate_limited_returns_429(db_session: AsyncSession):
    """cancel_case に追加した user_id 軸のレート制限（scope=case_cancel）が
    上限超過時に429を返すことを確認する（hit_account は所有権確認より前に
    呼ばれるため、上限到達後は対象caseの状態に関わらずブロックされる）。
    ``conftest.py`` の既定 ``RATE_LIMIT_ENABLED=false`` に依存せず、
    ``test_rate_limit_api.py`` と同じパターンでテスト専用の有効な
    ``RateLimiter`` を明示的に注入する。
    """
    test_app = create_test_app(db_session)
    limiter = RateLimiter(
        config=RateLimitConfig(
            enabled=True,
            login_account=RateLimitRule(5, 900),
            login_ip=RateLimitRule(20, 900),
            sensitive_account=RateLimitRule(1, 900),
            signup_ip=RateLimitRule(10, 3600),
            line_ip=RateLimitRule(20, 900),
            max_keys=10000,
        ),
        store=InMemoryRateLimitStore(),
    )
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        user_token = await _signup_user(client)
        case1 = await _create_case(client, user_token)
        case2 = await _create_case(client, user_token)

        r1 = await client.post(_cancel_url(case1["id"]), json={}, headers=_auth(user_token))
        assert r1.status_code == 200, r1.text

        # sensitive_account の上限(1)に既に到達しているため、2回目のリクエストは
        # 別案件であっても429になる（hit_accountの判定は所有権確認・状態検証
        # より前に行われるため）。
        r2 = await client.post(_cancel_url(case2["id"]), json={}, headers=_auth(user_token))
        assert r2.status_code == 429
        assert "Retry-After" in r2.headers


# ──────────────────────────── 業者一覧への非表示 ────────────────────────────


async def test_cancelled_case_hidden_from_operator_list(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)

    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200
    assert any(c["id"] == case["id"] for c in r.json())

    r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r.status_code == 200

    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200
    assert all(c["id"] != case["id"] for c in r.json())


# ──────────────────────────── bid_count集計（現行仕様どおり） ────────────────────────────


async def test_cancel_bid_count_includes_rejected_bids_per_current_behavior(
    client: AsyncClient, db_session: AsyncSession
):
    """_to_case_out の bid_count は withdrawn のみを除外する現行仕様のため、
    出品取り下げでrejectedに変わった入札はbid_countに含まれ続ける
    （cases.py の _to_case_out 参照）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    await _create_bid(client, case["id"], op_token)

    r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.status_code == 200
    assert r.json()["bid_count"] == 1


# ──────────────────────────── select_bidとの排他 ────────────────────────────


async def test_cancel_after_transaction_selected_409(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text

    r = await client.post(_cancel_url(case["id"]), json={}, headers=_auth(user_token))
    assert r.status_code == 409
