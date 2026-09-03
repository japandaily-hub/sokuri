"""入札取り下げ（withdraw）機能の統合テスト。

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

from app.api.rate_limit_deps import get_rate_limiter
from app.api.v1.router import api_router
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
)
from app.core.security import create_access_token, hash_password
from app.db.models.bid import Bid
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


def _withdraw_url(case_id: str, bid_id: str) -> str:
    return f"/api/v1/cases/{case_id}/bids/{bid_id}/withdraw"


# ──────────────────────────── 正常系 ────────────────────────────


async def test_withdraw_pending_bid_returns_200_and_status_withdrawn(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "withdrawn"


# ──────────────────────────── 認可 ────────────────────────────


async def test_withdraw_other_operators_bid_404(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "op2@example.com", "B社")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op1_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op2_token))
    assert r.status_code == 404


async def test_withdraw_as_user_403(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(user_token))
    assert r.status_code == 403


async def test_withdraw_unauthenticated_401(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]))
    assert r.status_code == 401


# ──────────────────────────── 状態ガード ────────────────────────────


async def test_withdraw_selected_bid_409(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 409
    assert "成約のキャンセル" in r.json()["detail"]


async def test_withdraw_rejected_bid_409(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "op2@example.com", "B社")
    case = await _create_case(client, user_token)
    bid1 = await _create_bid(client, case["id"], op1_token, amount=40000)
    bid2 = await _create_bid(client, case["id"], op2_token, amount=50000)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid1['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text

    r = await client.post(_withdraw_url(case["id"], bid2["id"]), headers=_auth(op2_token))
    assert r.status_code == 409
    assert r.json()["detail"] == "この入札は取り下げできません。"


async def test_withdraw_twice_returns_409_not_idempotent_200(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r1 = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r1.status_code == 200

    r2 = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r2.status_code == 409


# ──────────────────────────── case.status への波及 ────────────────────────────


async def test_withdraw_only_pending_bid_reopens_case(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.json()["status"] == "bidding"

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.status_code == 200
    assert r.json()["status"] == "open"


async def test_withdraw_one_of_multiple_pending_keeps_bidding(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "op2@example.com", "B社")
    case = await _create_case(client, user_token)
    bid1 = await _create_bid(client, case["id"], op1_token, amount=40000)
    await _create_bid(client, case["id"], op2_token, amount=50000)

    r = await client.post(_withdraw_url(case["id"], bid1["id"]), headers=_auth(op1_token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.status_code == 200
    assert r.json()["status"] == "bidding"


# ──────────────────────────── 集計 ────────────────────────────


async def test_withdraw_reduces_bid_count_and_recomputes_top_bid_amount(
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

    # 最高額(55000)を提示していたop2が取り下げる
    r = await client.post(_withdraw_url(case["id"], bid2["id"]), headers=_auth(op2_token))
    assert r.status_code == 200

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


async def test_rebid_after_withdraw_rejected_409(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200

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

    r = await client.post(_withdraw_url(case["id"], bid1["id"]), headers=_auth(op1_token))
    assert r.status_code == 200

    # op2がpendingで残っているため案件はbiddingのまま。op1の取り下げ済みbidを選ぼうとすると409。
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid1['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 409


# ──────────────────────────── 通知 ────────────────────────────


async def test_withdraw_sends_notification_to_owner(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "withdraw_notify_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "withdraw_notify_op@example.com", "通知テスト社")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    with patch(
        "app.api.v1.endpoints.bids.notify.send_bid_withdrawn", new=AsyncMock()
    ) as send_mock:
        r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200, r.text
    send_mock.assert_called_once()
    args = send_mock.call_args.args
    assert args[0] == "withdraw_notify_user@example.com"
    assert args[1] == case["id"]
    assert args[2] == "通知テスト社"


async def test_withdraw_skips_notification_for_placeholder_email(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "withdraw_placeholder_op@example.com")

    # LINE専用ユーザー（実メール未設定）を直接作成する（LINE連携フローの
    # モックを避けるため。auth.py の line_exchange と同じ仮メール形式を使う）。
    line_only_user = User(
        email="line-Uwithdrawplaceholder@line.katazuke.internal",
        name="LINE専用ユーザー",
    )
    db_session.add(line_only_user)
    await db_session.commit()
    await db_session.refresh(line_only_user)
    user_token = create_access_token(line_only_user.id, "user", "user")

    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    with patch(
        "app.api.v1.endpoints.bids.notify.send_bid_withdrawn", new=AsyncMock()
    ) as send_mock:
        r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200, r.text
    send_mock.assert_not_called()


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


# ──────────────────────────── vendor_status非activeでも取り下げ可（QA Medium-1） ────────────────────────────


async def test_withdraw_by_unverified_operator_succeeds(
    client: AsyncClient, db_session: AsyncSession
):
    """vendor_statusがactiveでなくなった業者でも、自社のpending入札は取り下げ
    できる意図的な設計（de-escalating操作のため get_verified_operator ではなく
    get_current_actor を使う。bids.py の withdraw_bid 冒頭コメント参照）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    assert operator is not None
    operator.vendor_status = "pending"
    await db_session.commit()

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "withdrawn"


# ──────────────────────────── 案件cancelled時のwithdraw（QA Medium-2） ────────────────────────────


async def test_withdraw_when_case_cancelled_409(client: AsyncClient, db_session: AsyncSession):
    """依頼者の退会処理等で案件がcancelledになった後、pending入札が残っていても
    withdrawは409になることを確認する（users.py の delete_my_account が
    トランザクション未成立の案件を cancelled にする経路を再現する）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    case_obj = await db_session.get(Case, uuid.UUID(case["id"]))
    assert case_obj is not None
    case_obj.status = "cancelled"
    await db_session.commit()

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 409
    assert r.json()["detail"] == "この案件は入札を受け付けていません。"


# ──────────────────────────── create_bidのCase行ロック参加（Security Medium-1） ────────────────────────────


async def test_create_bid_for_nonexistent_case_still_404(
    client: AsyncClient, db_session: AsyncSession
):
    """create_bid が withdraw/select と同じ _lock_case_row に参加した後も、
    存在しない案件に対しては通常どおり404を返すことを確認する（ロック追加に
    よるリグレッション防止。存在しないPKに対する SELECT ... FOR UPDATE は
    0行ロックとしてエラーにならず、後続の _get_case が404を送出する想定）。
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


# ──────────────────────────── withdrawの所有権事前チェック・404統一（Security Medium-2/Low-1） ────────────────────────────


async def test_withdraw_nonexistent_case_returns_404_with_unified_message(
    client: AsyncClient, db_session: AsyncSession
):
    """withdraw_bid は所有権の事前照会（ロック無し）で先に404を判定するため、
    案件自体が存在しない場合も「入札が見つかりません。」に統一される
    （旧実装は _get_case を先に呼んでいたため「案件が見つかりません。」を返し、
    case_id の存在有無を推測できてしまっていた。security review 指摘対応）。
    """
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    random_case_id = uuid.uuid4()
    random_bid_id = uuid.uuid4()

    r = await client.post(
        _withdraw_url(str(random_case_id), str(random_bid_id)), headers=_auth(op_token)
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "入札が見つかりません。"


async def test_withdraw_rate_limited_returns_429(db_session: AsyncSession):
    """withdraw_bid に追加した operator_id 軸のレート制限（scope=bid_withdraw）が
    上限超過時に429を返すことを確認する（hit_account は所有権確認より前に
    呼ばれるため、上限到達後は対象bidの状態に関わらずブロックされる）。
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
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client)
        op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
        case = await _create_case(client, user_token)
        bid = await _create_bid(client, case["id"], op_token)

        r1 = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
        assert r1.status_code == 200, r1.text

        # sensitive_account の上限(1)に既に到達しているため、2回目のリクエストは
        # 429になる（対象bidは既にwithdrawn済みだが、hit_accountの判定は
        # 所有権確認・状態検証より前に行われるため、409ではなく429が返る）。
        r2 = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
        assert r2.status_code == 429
        assert "Retry-After" in r2.headers


# ──────────────────────────── list_bidsの依頼者向けフィルタ（Security Low-2） ────────────────────────────


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

    r = await client.post(_withdraw_url(case["id"], bid1["id"]), headers=_auth(op1_token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(user_token))
    assert r.status_code == 200
    statuses = [b["status"] for b in r.json()]
    assert "withdrawn" not in statuses
    assert len(statuses) == 1


async def test_list_bids_admin_includes_withdrawn(
    client: AsyncClient, db_session: AsyncSession
):
    """依頼者本人ではなくadminが他人の案件を閲覧する場合は、監査・自社確認用途の
    ため取り下げ済み入札も含め全件返す（依頼者本人向けフィルタとは区別する。
    security review 指摘対応）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(admin_token))
    assert r.status_code == 200
    statuses = [b["status"] for b in r.json()]
    assert statuses == ["withdrawn"]


# ──────────────────────────── 監査証跡（Security Medium-3） ────────────────────────────


async def test_withdraw_creates_bid_withdrawal_audit_record(
    client: AsyncClient, db_session: AsyncSession
):
    from sqlalchemy import select

    from app.db.models.bid import BidWithdrawal

    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200

    audit = (
        await db_session.scalars(
            select(BidWithdrawal).where(BidWithdrawal.bid_id == uuid.UUID(bid["id"]))
        )
    ).one()
    assert audit.case_id == uuid.UUID(case["id"])
    assert audit.operator_id == uuid.UUID(op_id)
    assert audit.created_at is not None


async def test_withdraw_audit_record_snapshots_company_name_and_amount(
    client: AsyncClient, db_session: AsyncSession
):
    """bid_withdrawals のFKをCASCADE→RESTRICTへ変更したことに伴い追加した
    非正規化スナップショット列（company_name/amount）が、取り下げ時点の値で
    正しく記録されることを確認する（security review 2周目 Medium指摘対応）。
    """
    from sqlalchemy import select

    from app.db.models.bid import BidWithdrawal

    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "op1@example.com", "スナップショット片付け株式会社"
    )
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token, amount=73000)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200

    audit = (
        await db_session.scalars(
            select(BidWithdrawal).where(BidWithdrawal.bid_id == uuid.UUID(bid["id"]))
        )
    ).one()
    assert audit.operator_id == uuid.UUID(op_id)
    assert audit.company_name == "スナップショット片付け株式会社"
    assert audit.amount == 73000


async def test_bid_withdrawal_unique_per_bid_rejected_by_db(
    client: AsyncClient, db_session: AsyncSession
):
    """「1入札につき取り下げは1回」をDB側の一意制約（uq_bid_withdrawals_bid_id）
    でも保証する（QA review Medium指摘対応・多層防御）。アプリ層の条件付き
    UPDATE を迂回して同一 bid_id の監査行を二重INSERTしても IntegrityError で拒否される。
    """
    from sqlalchemy import select

    from app.db.models.bid import BidWithdrawal

    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, user_token)
    bid = await _create_bid(client, case["id"], op_token)

    r = await client.post(_withdraw_url(case["id"], bid["id"]), headers=_auth(op_token))
    assert r.status_code == 200

    existing = (
        await db_session.scalars(
            select(BidWithdrawal).where(BidWithdrawal.bid_id == uuid.UUID(bid["id"]))
        )
    ).one()
    db_session.add(
        BidWithdrawal(
            bid_id=existing.bid_id,
            case_id=existing.case_id,
            operator_id=existing.operator_id,
            company_name=existing.company_name,
            amount=existing.amount,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ──────────────────────────── select_bidの所有権事前照会（Security 2周目 Medium指摘） ────────────────────────────


async def test_select_other_users_case_403_without_locking(
    client: AsyncClient, db_session: AsyncSession
):
    """select_bid は withdraw_bid と同じく、認可判定（案件の所有権確認）より
    前にCase行の排他ロックを取得してはならない（他人のcase_idを大量に送り
    つけるロック争奪DoSを防ぐため）。他人の案件への select 試行が403になる
    ことに加え、``_lock_case_row`` が一切呼ばれていないことを確認する
    （security review 2周目 Medium指摘対応）。
    """
    admin_token = await _make_admin(client, db_session)
    owner_token = await _signup_user(client, "owner@example.com")
    other_token = await _signup_user(client, "other@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op1@example.com")
    case = await _create_case(client, owner_token)
    bid = await _create_bid(client, case["id"], op_token)

    with patch(
        "app.api.v1.endpoints.bids._lock_case_row", new=AsyncMock()
    ) as lock_mock:
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
            headers=_auth(other_token),
        )
    assert r.status_code == 403
    lock_mock.assert_not_called()
