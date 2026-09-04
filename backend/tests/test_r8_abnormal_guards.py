"""r8（異常系・中断系）監査で確定した不備の回帰テスト。

対象: H3（終了取引のガード）/ H2（キャンセルの可視化）/ M3（減額申請の回数制限）/
M4（依頼者停止の業者側可視化）/ M1（cancel_count の読み出し）/ M5（運営の強制終了）/
M6（業者の退会）。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_txn_state_integrity.py と同様、ヘルパーはこのファイル内に自己完結で複製する
（既存スタイルの踏襲）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import get_rate_limiter
from app.api.v1.router import api_router
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimitRule,
    RateLimiter,
)
from app.core.security import hash_password
from app.db.models.bid import Bid
from app.db.models.operator import Operator
from app.db.models.transaction import Cancellation, Transaction
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
        email="r8admin@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "r8admin@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_user(
    client: AsyncClient, email: str = "r8user1@example.com"
) -> tuple[str, str]:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    return data["access_token"], data["user"]["id"]


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


# ──────────────── H3: 終了取引のチャット・日程ガード ────────────────


@pytest.mark.parametrize("terminal", ["cancelled", "completed"])
async def test_message_and_schedule_blocked_on_closed_transaction(
    client: AsyncClient, db_session: AsyncSession, terminal: str
):
    """キャンセル済み・完了済みの取引には発言も日程候補提示もできない（409・r8-H3）。

    既読ポインタ更新（messages/read）は「過去ログを読んだ」記録のため許容のまま。
    """
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op1@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    if terminal == "cancelled":
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/cancel",
            json={"reason": "急用のため中止します"},
            headers=_auth(user_token),
        )
    else:
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
        )
    assert r.status_code == 200, r.text

    for token in (user_token, op_token):
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "終了後の発言"},
            headers=_auth(token),
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == {
            "code": "transaction_closed",
            "message": "この取引は終了しています。",
        }

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["9月7日（日）10:00〜12:00"]},
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "transaction_closed"

    # 既読更新は終了後も許容（契約）。
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(user_token)
    )
    assert r.status_code == 200, r.text

    count = await db_session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.status == terminal)
    )
    assert count == 1


# ──────────────── H2: キャンセルの可視化 ────────────────


async def test_cancellation_visible_to_both_parties_and_admin(
    client: AsyncClient, db_session: AsyncSession
):
    """業者キャンセルの「誰が・なぜ・いつ」が当事者双方の詳細と admin 一覧に出る（r8-H2）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op2@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "当日の作業員が確保できなくなったため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 200, r.text

    for token in (user_token, op_token):
        r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(token))
        assert r.status_code == 200, r.text
        cancellation = r.json()["cancellation"]
        assert cancellation["cancelled_by"] == "operator"
        assert cancellation["reason"] == "当日の作業員が確保できなくなったため"
        assert cancellation["cancelled_at"] is not None

    r = await client.get("/api/v1/admin/transactions", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["id"] == txn_id)
    assert item["status"] == "cancelled"
    assert item["cancelled_by"] == "operator"


async def test_cancellation_is_null_while_active(
    client: AsyncClient, db_session: AsyncSession
):
    """キャンセルされていない取引の cancellation は None（誤表示防止）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op3@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["cancellation"] is None


# ──────────────── M3: 減額申請の回数制限 ────────────────


async def test_reduction_request_limited_to_two_per_transaction(
    client: AsyncClient, db_session: AsyncSession
):
    """減額申請は1取引につき2回まで（却下後の再申請は1回だけ・r8-M3）。

    無制限だと、業者が却下のたびに再申請するだけで依頼者の「完了確定」を
    恒久的に 409 に閉じ込められる（ループ可能）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op4@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    for attempt in range(2):
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/reduction",
            json={
                "requested_amount": 20000 - attempt,
                "reason": "想定より荷物が多かったため",
            },
            headers=_auth(op_token),
        )
        assert r.status_code == 201, r.text
        reduction_id = r.json()["id"]
        r = await client.patch(
            f"/api/v1/transactions/{txn_id}/reduction/{reduction_id}",
            json={"action": "reject"},
            headers=_auth(user_token),
        )
        assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 18000, "reason": "3回目の申請は拒否されるべき"},
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "減額申請は1つの取引につき2回までです。"

    # 上限に達しても依頼者は完了確定できる（pending が残らないため）。
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200, r.text


async def test_reduction_pending_message_takes_precedence(
    client: AsyncClient, db_session: AsyncSession
):
    """未回答が残っている間は従来どおり「未回答の減額申請があります。」（文言の後退防止）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op5@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 20000, "reason": "想定より荷物が多かったため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 19000, "reason": "未回答のまま重ねて申請する"},
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "未回答の減額申請があります。回答をお待ちください。"


# ──────────────── M4 / M1: 依頼者停止の可視化・cancel_count ────────────────


async def test_user_suspension_visible_to_operator(
    client: AsyncClient, db_session: AsyncSession
):
    """依頼者を停止すると業者側の取引詳細・一覧に user_suspended が立つ（r8-M4）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, user_id = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op6@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.json()["user_suspended"] is False

    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": True, "reason": "調査中"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.json()["user_suspended"] is True

    r = await client.get("/api/v1/transactions", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert [t["user_suspended"] for t in r.json()] == [True]


async def test_admin_operator_list_exposes_cancel_count(
    client: AsyncClient, db_session: AsyncSession
):
    """業者キャンセルの累計が admin の業者一覧から読める（r8-M1）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "r8op7@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    item = next(o for o in r.json()["items"] if o["id"] == op_id)
    assert item["cancel_count"] == 0

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "作業員を確保できないため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    item = next(o for o in r.json()["items"] if o["id"] == op_id)
    assert item["cancel_count"] == 1


# ──────────────── M5: 運営による強制終了 ────────────────


async def test_admin_cancel_transaction(client: AsyncClient, db_session: AsyncSession):
    """運営が固まった取引を終了できる。cancel_count は加算しない（r8-M5）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, user_id = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "r8op8@example.com")
    case_id, txn_id = await _create_transaction(client, user_token, op_token)

    # 依頼者を停止して「固まった取引」を作る（当事者操作では動かせない状態）。
    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": True, "reason": "本人確認が取れないため"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    r = await client.patch(
        f"/api/v1/admin/transactions/{txn_id}/cancel",
        json={"reason": "依頼者と連絡が取れないため運営判断で終了"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"id": txn_id, "status": "cancelled"}

    cancellation = await db_session.scalar(
        select(Cancellation).where(Cancellation.transaction_id == uuid.UUID(txn_id))
    )
    assert cancellation is not None
    assert cancellation.cancelled_by == "admin"
    assert cancellation.reason == "依頼者と連絡が取れないため運営判断で終了"

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.cancel_count == 0  # 運営判断は業者の責に帰さない

    # 案件も既存のキャンセル時と同じ扱い（cancelled）になる。
    r = await client.get("/api/v1/admin/cases", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert next(c for c in r.json()["items"] if c["id"] == case_id)["status"] == "cancelled"

    # 業者側の詳細で理由が読める。
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.json()["cancellation"]["cancelled_by"] == "admin"

    # 二重実行は409（Cancellation の2行目を積まない）。
    r = await client.patch(
        f"/api/v1/admin/transactions/{txn_id}/cancel",
        json={"reason": "二度目"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409, r.text
    rows = await db_session.scalar(
        select(func.count())
        .select_from(Cancellation)
        .where(Cancellation.transaction_id == uuid.UUID(txn_id))
    )
    assert rows == 1


async def test_admin_cancel_transaction_requires_admin(
    client: AsyncClient, db_session: AsyncSession
):
    """当事者・業者は運営の強制終了 API を叩けない。理由は必須（422）。

    既存の admin 認可契約（tests/test_admin_authz_negative.py）に合わせ、
    一般ユーザーは 403・業者トークンは 401（typ 不一致）を許容する。
    """
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op9@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    for token in (user_token, op_token):
        r = await client.patch(
            f"/api/v1/admin/transactions/{txn_id}/cancel",
            json={"reason": "権限のない終了"},
            headers=_auth(token),
        )
        assert r.status_code in (401, 403), r.text

    r = await client.patch(
        f"/api/v1/admin/transactions/{txn_id}/cancel",
        json={"reason": ""},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422, r.text

    r = await client.patch(
        f"/api/v1/admin/transactions/{uuid.uuid4()}/cancel",
        json={"reason": "存在しない成約"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 404, r.text


# ──────────────── M6: 業者の退会 ────────────────


async def test_operator_withdraw_blocked_by_active_transaction(
    client: AsyncClient, db_session: AsyncSession
):
    """進行中取引があるうちは業者は退会できない（409・r8-M6）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op10@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.request(
        "DELETE",
        "/api/v1/operator/me",
        json={"password": "operatorpass1"},
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == (
        "進行中の取引があるため退会できません。取引の完了またはキャンセル後に再度お試しください。"
    )

    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200, r.text

    r = await client.request(
        "DELETE",
        "/api/v1/operator/me",
        json={"password": "operatorpass1"},
        headers=_auth(op_token),
    )
    assert r.status_code == 204, r.text


async def test_operator_withdraw_requires_correct_password(
    client: AsyncClient, db_session: AsyncSession
):
    """退会には現在のパスワードの再照合が必須（誤りは403・r8-review H-4）。"""
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(client, admin_token, "r8op10b@example.com")

    r = await client.request(
        "DELETE",
        "/api/v1/operator/me",
        json={"password": "wrong-password"},
        headers=_auth(op_token),
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "パスワードが正しくありません。"

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.deleted_at is None

    r = await client.request(
        "DELETE",
        "/api/v1/operator/me",
        json={"password": "operatorpass1"},
        headers=_auth(op_token),
    )
    assert r.status_code == 204, r.text


async def test_operator_withdraw_anonymizes_and_revokes(
    client: AsyncClient, db_session: AsyncSession
):
    """退会で匿名化・未決入札の取り下げ・旧トークン失効・公開一覧からの除外が起きる。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "r8op11@example.com")
    case = await _create_case(client, user_token)
    bid = await _bid(client, op_token, case["id"])

    r = await client.get("/api/v1/vendors")
    assert r.status_code == 200, r.text
    assert any(v["operator_id"] == op_id for v in r.json())

    r = await client.request(
        "DELETE",
        "/api/v1/operator/me",
        json={"password": "operatorpass1"},
        headers=_auth(op_token),
    )
    assert r.status_code == 204, r.text

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.deleted_at is not None
    assert operator.contact_email == f"deleted-{op_id}@deleted.katazuke.internal"
    assert operator.password_hash is None
    assert operator.line_user_id is None

    withdrawn_bid = await db_session.get(Bid, uuid.UUID(bid["id"]))
    await db_session.refresh(withdrawn_bid)
    assert withdrawn_bid.status == "rejected"

    # 旧トークンは即時失効（401）。
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 401, r.text

    # 公開一覧・公開プロフィールから消える。
    r = await client.get("/api/v1/vendors")
    assert r.status_code == 200, r.text
    assert all(v["operator_id"] != op_id for v in r.json())
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 404, r.text

    # 旧メールでのログインも通らない。
    r = await client.post(
        "/api/v1/auth/operator/login",
        json={"email": "r8op11@example.com", "password": "operatorpass1"},
    )
    assert r.status_code == 401, r.text


async def test_select_bid_rejects_deleted_operator(client: AsyncClient, db_session: AsyncSession):
    """退会済み業者の入札は select_bid で409（r8-review H-1・多層防御）。

    運用上は operator_profile.delete_my_operator_account が退会時に本人の
    pending入札を一括rejected化するため、ここまで到達するのは「rejected化と
    select_bidの競合をロックが完全には防げなかった」想定シナリオを再現した
    場合のみ（SQLiteではFOR UPDATEがno-opのため実競合はテストできない。r8-review
    未解決2）。ここでは pending 入札を残したまま operator.deleted_at のみを
    直接付与し、select_bid 側の409ガードそのものを固定化する。
    """
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "r8op12@example.com")
    case = await _create_case(client, user_token)
    bid = await _bid(client, op_token, case["id"])

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    operator.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 409, r.text
    assert "退会済み" in r.json()["detail"]

    # list_bids でも operator_suspended と同じ旗が立ち、選べない理由が伝わる。
    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert next(b for b in r.json() if b["id"] == bid["id"])["operator_suspended"] is True


async def test_select_bid_after_withdraw_commit_returns_409(
    client: AsyncClient, db_session: AsyncSession
):
    """退会が **commit された後**に走る落札は必ず409（r8-verify-fix H-1 残窓）。

    退会と落札の競合窓（退会側の一括rejected化〜commit の間）で新規INSERTされた
    入札は、退会側の行ロックの対象外だった。現在は双方が Operator 行を
    ``SELECT ... FOR UPDATE``（services/case_lock.lock_operator_row）で掴むため、
    退会commit後にロックを取る落札側は必ずコミット済みの ``deleted_at`` を読む。
    ここではその窓で入り込んだ pending 入札を「退会後に status を pending へ戻す」
    ことで再現し、select_bid が ORM の identity map ではなく**再読込した値**で
    409 を返すことを固定する（SQLiteでは FOR UPDATE が no-op のため、実際の
    直列化そのものは PostgreSQL 本番でのみ有効。r8-review 未解決2）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "r8op13@example.com")
    case = await _create_case(client, user_token)
    bid = await _bid(client, op_token, case["id"])

    r = await client.request(
        "DELETE",
        "/api/v1/operator/me",
        json={"password": "operatorpass1"},
        headers=_auth(op_token),
    )
    assert r.status_code == 204, r.text

    # 競合窓で入った新規入札の再現（退会側の一括UPDATEに掴まれなかった行）。
    raced_bid = await db_session.get(Bid, uuid.UUID(bid["id"]))
    raced_bid.status = "pending"
    await db_session.commit()

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 409, r.text
    assert "退会済み" in r.json()["detail"]

    # 成約は1件も作られていない（退会済み業者の進行中取引が生まれない）。
    txn_count = await db_session.scalar(
        select(func.count()).select_from(Transaction).join(Bid, Transaction.bid_id == Bid.id).where(
            Bid.operator_id == uuid.UUID(op_id)
        )
    )
    assert txn_count == 0


async def test_operator_withdraw_rate_limited_returns_429(db_session: AsyncSession):
    """誤パスワード連打で scope=account_delete のアカウント軸が429を返す（r8-verify-fix）。

    ``RateLimitGuard("account_delete")`` は ip_rule=None / count_all=False のため、
    ハンドラが ``ctx.check_account()`` / ``record_failure()`` を呼ばない限り**何も
    しない**（これが H-4 の原因そのもの）。呼び忘れの再発を捕まえるため、429 到達を
    実証する。conftest の既定（RATE_LIMIT_ENABLED=false）に依存せず、
    test_user_profile_ext.py と同じパターンでテスト専用の RateLimiter を注入する。
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
    ) as rl_client:
        admin_token = await _make_admin(rl_client, db_session)
        op_token, op_id = await _verified_operator(
            rl_client, admin_token, "r8op14@example.com"
        )

        r1 = await rl_client.request(
            "DELETE",
            "/api/v1/operator/me",
            json={"password": "wrong-password"},
            headers=_auth(op_token),
        )
        assert r1.status_code == 403, r1.text

        # 上限（sensitive_account=1）超過。正しいパスワードでも 429 が先に返る
        # （＝総当たりでの退会強行を止められる）。
        r2 = await rl_client.request(
            "DELETE",
            "/api/v1/operator/me",
            json={"password": "operatorpass1"},
            headers=_auth(op_token),
        )
        assert r2.status_code == 429, r2.text
        assert "Retry-After" in r2.headers

        operator = await db_session.get(Operator, uuid.UUID(op_id))
        await db_session.refresh(operator)
        assert operator.deleted_at is None


# ──────────────── r8-review Medium の回帰 ────────────────


async def test_admin_cancel_records_executing_admin(
    client: AsyncClient, db_session: AsyncSession
):
    """強制終了の実行者（admin.id）が cancellations に残る（r8-review M-1）。

    API 応答には含めない（当事者に運営個人を開示しない）ことも併せて固定する。
    """
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, _ = await _verified_operator(client, admin_token, "r8op15@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.patch(
        f"/api/v1/admin/transactions/{txn_id}/cancel",
        json={"reason": "当事者双方が長期無応答のため運営判断で終了"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    admin_id = await db_session.scalar(
        select(User.id).where(User.email == "r8admin@katadzuke.jp")
    )
    cancellation = await db_session.scalar(
        select(Cancellation).where(Cancellation.transaction_id == uuid.UUID(txn_id))
    )
    assert cancellation is not None
    assert cancellation.cancelled_by == "admin"
    assert cancellation.cancelled_by_admin_id == admin_id

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert "cancelled_by_admin_id" not in r.json()["cancellation"]


async def test_transaction_detail_exposes_operator_deleted(
    client: AsyncClient, db_session: AsyncSession
):
    """退会済み業者の成約は依頼者側に operator_deleted=true で伝わる（r8-review M-5）。

    停止（operator_suspended）と違い退会は復帰しないため、web が「待つ」ではなく
    「キャンセルして出し直す」導線を出せるよう独立した旗にしている。
    """
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "r8op16@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["operator_deleted"] is False
    assert r.json()["operator_suspended"] is False

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    operator.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["operator_deleted"] is True
    # 停止とは独立（退会しただけで停止扱いにはしない）。
    assert r.json()["operator_suspended"] is False


async def test_reduction_unknown_transaction_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    """減額申請の行ロック追加（r8-review M-6）後も、存在しない成約は404のまま。

    ``lock_transaction_rows`` を認可判定より前に呼ぶ順序変更で、404 が 500 や
    403 に化けないことを固定する（上限判定そのものは
    test_reduction_request_limited_to_two_per_transaction が担保）。
    """
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, admin_token, "r8op17@example.com")

    r = await client.post(
        f"/api/v1/transactions/{uuid.uuid4()}/reduction",
        json={"requested_amount": 10000, "reason": "追加作業が不要になったため"},
        headers=_auth(op_token),
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "成約情報が見つかりません。"
