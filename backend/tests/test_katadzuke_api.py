"""カタヅケ API の統合テスト — 認証 / 案件 / 入札 / 成約 / 減額 / レビュー / 管理。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。
AI（Gemini）・メール（Brevo）には接続しない（写真ファイル不在時は
summary がフォールバック文を返し、Brevo はキー未設定でスキップされる）。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import CURRENT_OPERATOR_TERMS_VERSION


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


@pytest.fixture
def tmp_storage(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return tmp_path


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
    assert r.status_code == 200
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str = "user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201
    return r.json()["access_token"]


async def _invite_code(client: AsyncClient, admin_token: str) -> str:
    r = await client.post(
        "/api/v1/admin/invites", json={}, headers=_auth(admin_token)
    )
    assert r.status_code == 201
    return r.json()["code"]


async def _signup_operator(
    client: AsyncClient, code: str, email: str, company: str = "テスト片付け株式会社"
) -> tuple[str, str]:
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
    assert r.status_code == 201
    data = r.json()
    return data["access_token"], data["operator"]["id"]


async def _verified_operator(
    client: AsyncClient, db_session: AsyncSession, admin_token: str, email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    code = await _invite_code(client, admin_token)
    token, op_id = await _signup_operator(client, code, email, company)
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


# ──────────────────────────── 認証 ────────────────────────────


async def test_signup_login_me(client: AsyncClient):
    token = await _signup_user(client)
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "user1@example.com"
    assert r.json()["account_type"] == "user"


async def test_signup_duplicate_email_409(client: AsyncClient):
    await _signup_user(client)
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": "user1@example.com", "password": "password123"},
    )
    assert r.status_code == 409


async def test_login_wrong_password_401(client: AsyncClient):
    await _signup_user(client)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "user1@example.com", "password": "wrongpassword"},
    )
    assert r.status_code == 401


async def test_operator_signup_requires_agreement_422(client: AsyncClient):
    """agreed=False（利用規約・プライバシーポリシー未同意）は422で拒否される。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "未同意テスト業者",
            "email": "no_agree_op@example.com",
            "password": "operatorpass1",
            "agreed": False,
        },
    )
    assert r.status_code == 422


async def test_operator_signup_missing_agreed_key_422(client: AsyncClient):
    """agreed キー自体を省略した場合も（必須フィールド欠落として）422で拒否される。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "agreedキー省略テスト業者",
            "email": "no_agreed_key_op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
        },
    )
    assert r.status_code == 422


async def test_operator_signup_records_agreement(
    client: AsyncClient, db_session: AsyncSession
):
    """agreed=True で登録成功し、同意日時・規約バージョンがDBに保存される。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "同意記録テスト業者",
            "email": "agree_op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    op_id = r.json()["operator"]["id"]

    operator = await db_session.scalar(
        select(Operator).where(Operator.id == uuid.UUID(op_id))
    )
    assert operator is not None
    assert operator.agreed_terms_version == CURRENT_OPERATOR_TERMS_VERSION
    assert operator.agreed_at is not None


async def test_operator_signup_requires_valid_invite(client: AsyncClient):
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": "KDZ-NOTEXIST",
            "company_name": "X社",
            "email": "op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 403


async def test_invite_single_use(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    code = await _invite_code(client, admin_token)
    await _signup_operator(client, code, "op1@example.com")
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "二重利用社",
            "email": "op2@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 403


async def test_admin_endpoints_require_admin_role(client: AsyncClient):
    token = await _signup_user(client)
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(token))
    assert r.status_code == 403


async def test_endpoints_require_auth_401(client: AsyncClient):
    assert (await client.get("/api/v1/cases")).status_code == 401
    assert (await client.post("/api/v1/cases", json=_case_payload())).status_code == 401
    assert (await client.post("/api/v1/upload/presign", json={})).status_code == 401


# ──────────────────────────── 案件 + マスキング ────────────────────────────


async def test_create_case_has_ai_summary_and_photos(client: AsyncClient):
    token = await _signup_user(client)
    case = await _create_case(client, token)
    assert case["status"] == "open"
    assert case["ai_summary"]
    assert len(case["photos"]) == 2
    assert case["address_detail"] == "桜丘1-2-3 メゾン桜 101号室"


async def test_unverified_operator_can_list_cases_but_not_bid(
    client: AsyncClient, db_session: AsyncSession
):
    """vendor_status=pending の業者は案件一覧の閲覧は可能（200）。
    入札不可は別途 test_pending_operator_cannot_bid で検証する。
    """
    from app.core.security import create_access_token
    from app.db.models.operator import Operator
    import uuid as _uuid

    pending_op = Operator(
        id=_uuid.uuid4(),
        company_name="ペンディング業者",
        contact_email="pending_op@example.com",
        password_hash=hash_password("password123"),
        vendor_status="pending",
    )
    db_session.add(pending_op)
    await db_session.commit()
    await db_session.refresh(pending_op)

    op_token = create_access_token(pending_op.id, "operator", "operator")
    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200


async def test_operator_case_view_masks_address(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "op1@example.com"
    )

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(op_token))
    assert r.status_code == 200
    body = r.json()
    assert "address_detail" not in body
    assert body["prefecture"] == "東京都"
    assert body["city"] == "世田谷区"

    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200
    assert all("address_detail" not in c for c in r.json())


async def test_user_cannot_view_others_case(client: AsyncClient):
    token_a = await _signup_user(client, "a@example.com")
    token_b = await _signup_user(client, "b@example.com")
    case = await _create_case(client, token_a)
    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(token_b))
    assert r.status_code == 403


# ──────────────────────────── フルフロー ────────────────────────────


async def test_full_flow_bid_select_reduction_complete_review(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, op1_id = await _verified_operator(
        client, db_session, admin_token, "op1@example.com", "片付けA社"
    )
    op2_token, op2_id = await _verified_operator(
        client, db_session, admin_token, "op2@example.com", "片付けB社"
    )
    case = await _create_case(client, user_token)
    case_id = case["id"]

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 50000, "message": "丁寧に対応します"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 201
    bid1 = r.json()
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 65000},
        headers=_auth(op2_token),
    )
    assert r.status_code == 201

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 70000},
        headers=_auth(op1_token),
    )
    assert r.status_code == 409

    r = await client.get(f"/api/v1/cases/{case_id}/bids", headers=_auth(user_token))
    assert r.status_code == 200
    bids = r.json()
    assert len(bids) == 2
    assert all(b["operator"]["company_name"] for b in bids)

    r = await client.get(f"/api/v1/cases/{case_id}/bids", headers=_auth(op1_token))
    assert len(r.json()) == 1

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid1['id']}/select", headers=_auth(op1_token)
    )
    assert r.status_code in (401, 403)

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid1['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201
    txn = r.json()
    assert txn["initial_amount"] == 50000
    txn_id = txn["id"]

    r = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(user_token))
    assert r.json()["status"] == "closed"
    r = await client.get(f"/api/v1/cases/{case_id}/bids", headers=_auth(user_token))
    statuses = {b["operator"]["id"]: b["status"] for b in r.json()}
    assert statuses[op1_id] == "selected"
    assert statuses[op2_id] == "rejected"

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op1_token))
    assert r.status_code == 200
    detail = r.json()
    assert detail["address"]["address_detail"] == "桜丘1-2-3 メゾン桜 101号室"
    assert detail["contact_email"] == "user1@example.com"

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op2_token))
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 40000, "reason": "短い"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 60000, "reason": "実際の物量が想定より多かったため"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={
            "requested_amount": 42000,
            "reason": "現地確認の結果、家電 2 点に破損があり再販価値が下がるため",
        },
        headers=_auth(op1_token),
    )
    assert r.status_code == 201
    reduction = r.json()
    assert reduction["status"] == "pending"

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 41000, "reason": "さらに追加の破損が見つかったため"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 409

    r = await client.patch(
        f"/api/v1/transactions/{txn_id}/reduction/{reduction['id']}",
        json={"action": "approve"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.json()["final_amount"] == 42000

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(op1_token)
    )
    assert r.status_code == 403
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["final_amount"] == 42000

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "rating": 5, "comment": "迅速で丁寧でした"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "rating": 4},
        headers=_auth(user_token),
    )
    assert r.status_code == 409

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "rating": 4, "comment": "スムーズでした"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 201

    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    op1 = next(o for o in r.json() if o["id"] == op1_id)
    assert op1["rating"] == 5.0


async def test_transaction_list_has_review_reflects_user_review(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /transactions の has_review は、成約完了直後は false、
    ユーザーレビュー投稿後は true に切り替わる（通知の恒久残存防止用フラグ）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "op_has_review@example.com"
    )
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(op_token),
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
        headers=_auth(user_token),
    )
    txn_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
    )
    assert r.status_code == 200

    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200
    txn_item = next(t for t in r.json() if t["id"] == txn_id)
    assert txn_item["has_review"] is False

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "rating": 5, "comment": "とても良かったです"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201

    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200
    txn_item = next(t for t in r.json() if t["id"] == txn_id)
    assert txn_item["has_review"] is True


async def test_cancel_flow_by_operator(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "op1@example.com"
    )
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(op_token),
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
        headers=_auth(user_token),
    )
    txn_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "繁忙期のため対応不可になりました"},
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.json()["status"] == "cancelled"

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.json()["address"] is None

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
    )
    assert r.status_code == 409


async def test_reviews_only_after_completed(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "op1@example.com"
    )
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 10000}, headers=_auth(op_token)
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    txn_id = r.json()["id"]
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "rating": 5},
        headers=_auth(user_token),
    )
    assert r.status_code == 409


# ──────────────────────────── 写真アップロード ────────────────────────────


async def test_upload_roundtrip(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    r = await client.post(
        "/api/v1/upload/presign",
        json={"filename": "room.jpg", "content_type": "image/jpeg"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    presign = r.json()

    r = await client.put(
        presign["upload_url"],
        content=b"\xff\xd8\xff\xe0fakejpegbytes",
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 204

    r = await client.get(presign["public_url"])
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff\xe0fakejpegbytes"


async def test_upload_rejects_invalid_key(client: AsyncClient, tmp_storage):
    r = await client.put(
        "/api/v1/upload/..%2F..%2Fevil.sh",
        content=b"x",
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code in (404, 422)


async def test_case_create_rejects_invalid_storage_key(client: AsyncClient):
    token = await _signup_user(client)
    payload = _case_payload()
    payload["photos"] = [{"storage_key": "../../etc/passwd", "sort_order": 0}]
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


# ──────────────────────────── TASK-2: オープン登録 / vendor_status ────────────────────────────


async def test_open_operator_registration(client: AsyncClient, db_session: AsyncSession):
    """招待コードなしでオープン登録 → vendor_status=pending → 案件閲覧は可・入札は403。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "オープン登録業者テスト",
            "email": "open_op@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["operator"]["vendor_status"] == "pending"
    op_token = data["access_token"]

    user_token = await _signup_user(client, "open_user@example.com")
    case = await _create_case(client, user_token)

    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 25000},
        headers=_auth(op_token),
    )
    assert r.status_code == 403


async def test_invited_operator_gets_active(client: AsyncClient, db_session: AsyncSession):
    """招待コードありで登録 → vendor_status=active。"""
    admin_token = await _make_admin(client, db_session)
    code = await _invite_code(client, admin_token)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "招待登録業者テスト",
            "email": "invited_op@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["operator"]["vendor_status"] == "active"


async def test_pending_operator_cannot_bid(client: AsyncClient, db_session: AsyncSession):
    """pending業者（未承認）は案件閲覧は可能だが入札は403でブロックされる。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "未承認テスト業者",
            "email": "pending_bid_op@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    pending_op_token = r.json()["access_token"]
    assert r.json()["operator"]["vendor_status"] == "pending"

    user_token = await _signup_user(client, "user_for_pending@example.com")
    case = await _create_case(client, user_token)

    # 閲覧は許可される
    r = await client.get("/api/v1/cases", headers=_auth(pending_op_token))
    assert r.status_code == 200
    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(pending_op_token))
    assert r.status_code == 200

    # 入札はブロックされる
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(pending_op_token),
    )
    assert r.status_code == 403


async def test_deapproved_operator_address_hidden(
    client: AsyncClient, db_session: AsyncSession
):
    """承認済み(active)業者が落札した後、admin取り消しでpendingに戻った場合は
    住所情報が非開示になりawaiting_approval=Trueになる（安全側の経過措置ケース）。
    """
    admin_token = await _make_admin(client, db_session)

    # 1. 招待コードで登録 → active（審査済み前提）
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "deapprove_op@example.com", "取消テスト業者"
    )

    user_token = await _signup_user(client, "user_for_deapprove@example.com")
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(op_token),
    )
    assert r.status_code == 201
    bid_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid_id}/select",
        headers=_auth(user_token),
    )
    assert r.status_code == 201
    txn_id = r.json()["id"]

    # 落札直後（active）は住所開示される
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["address"] is not None

    # 2. admin が承認を取り消す（active → pending）
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["vendor_status"] == "pending"

    # 3. 承認取り消し後は住所非開示・awaiting_approval=True になる
    r = await client.get(
        f"/api/v1/transactions/{txn_id}",
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    txn_data = r.json()
    assert txn_data["address"] is None
    assert txn_data.get("awaiting_approval") is True


async def test_admin_approve_sets_active(client: AsyncClient, db_session: AsyncSession):
    """admin approveでvendor_status=active + verified_atが設定されること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "承認テスト業者",
            "email": "approve_test@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    op_id = r.json()["operator"]["id"]
    assert r.json()["operator"]["vendor_status"] == "pending"

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["vendor_status"] == "active"
    assert data["verified_at"] is not None

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["vendor_status"] == "pending"
    assert data["verified_at"] is None


async def test_bulk_invite_creation(client: AsyncClient, db_session: AsyncSession):
    """バルク発行: 10件のコードが発行され、lot_nameが設定されること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/admin/invites/bulk",
        json={"count": 10, "lot_name": "テストロット"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["count"] == 10
    assert len(data["codes"]) == 10
    assert data["lot_name"] == "テストロット"
    assert len(set(data["codes"])) == 10
    for code in data["codes"]:
        assert code.startswith("KDZ-")


# ──────────────────────────── 業者事前申込 (/operator-applications) ────────────────────────────


def _application_payload(email: str = "biz@example.com", company: str = "申込テスト株式会社") -> dict:
    return {
        "company_name": company,
        "representative_name": "代表 太郎",
        "registered_address": "東京都千代田区丸の内1-1-1",
        "contact_name": "担当 花子",
        "email": email,
        "phone": "03-1234-5678",
        "business_type": "corp",
        "service_area": "東京都",
        "categories": "家電,家具",
        "message": "よろしくお願いします。",
        "license_number": "第123456789012号",
        "invoice_number": "T1234567890123",
        "bank_account": {
            "bank_name": "みずほ銀行",
            "branch_name": "東京営業部",
            "account_type": "ordinary",
            "account_number": "1234567",
            "account_holder": "シンセイテストカブシキガイシャ",
        },
        "agreed": True,
    }


async def test_operator_application_create_public_201(client: AsyncClient):
    """認証不要で申込でき、201・status=receivedが返る。"""
    r = await client.post(
        "/api/v1/operator-applications", json=_application_payload()
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "received"
    assert "application_id" in data


async def test_operator_application_missing_required_field_422(client: AsyncClient):
    """必須項目（company_name）欠落は422で拒否される。"""
    payload = _application_payload()
    del payload["company_name"]
    r = await client.post("/api/v1/operator-applications", json=payload)
    assert r.status_code == 422


async def test_operator_application_missing_license_number_422(client: AsyncClient):
    """古物商許可番号の欠落は422で拒否される。"""
    payload = _application_payload()
    del payload["license_number"]
    r = await client.post("/api/v1/operator-applications", json=payload)
    assert r.status_code == 422


async def test_operator_application_not_agreed_422(client: AsyncClient):
    """agreed=Falseは422で拒否される。"""
    payload = _application_payload()
    payload["agreed"] = False
    r = await client.post("/api/v1/operator-applications", json=payload)
    assert r.status_code == 422


async def test_operator_application_rate_limit_429(client: AsyncClient):
    """同一IPから制限件数（5件/時間）を超えて申込むと429になる（security review Critical指摘対応）。"""
    ip = "203.0.113.10"
    for i in range(5):
        r = await client.post(
            "/api/v1/operator-applications",
            json=_application_payload(email=f"rate_limit_{i}@example.com"),
            headers={"X-Forwarded-For": ip},
        )
        assert r.status_code == 201

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="rate_limit_over@example.com"),
        headers={"X-Forwarded-For": ip},
    )
    assert r.status_code == 429

    # 別IPからは引き続き申込可能であること（IP単位の絞り込みであることの確認）
    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="rate_limit_other_ip@example.com"),
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert r.status_code == 201


async def test_operator_application_bank_account_not_stored_plaintext(
    client: AsyncClient, db_session: AsyncSession
):
    """口座情報がDB上で平文で保存されていないこと（暗号化されていること）を検証する。"""
    from app.db.models.operator_application import OperatorApplication

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="encrypt_check@example.com"),
    )
    assert r.status_code == 201
    application_id = r.json()["application_id"]

    application = await db_session.get(
        OperatorApplication, uuid.UUID(application_id)
    )
    assert application is not None
    assert application.bank_account_enc is not None
    # 平文の口座番号・口座名義がそのまま暗号文に含まれていないこと
    assert "1234567" not in application.bank_account_enc
    assert "シンセイテストカブシキガイシャ" not in application.bank_account_enc

    # 復号すれば元の値が正しく取り出せること
    from app.core.crypto import decrypt_json

    decrypted = decrypt_json(application.bank_account_enc)
    assert decrypted["account_number"] == "1234567"
    assert decrypted["account_holder"] == "シンセイテストカブシキガイシャ"


async def test_admin_list_operator_applications_masks_bank_account(
    client: AsyncClient, db_session: AsyncSession
):
    """admin一覧が口座情報を下4桁マスクで返すこと。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="mask_check@example.com"),
    )
    assert r.status_code == 201

    r = await client.get(
        "/api/v1/admin/operator-applications", headers=_auth(admin_token)
    )
    assert r.status_code == 200
    applications = r.json()
    target = next(a for a in applications if a["contact_email"] == "mask_check@example.com")
    assert target["bank_account"]["account_number_masked"] == "***4567"
    assert "1234567" not in str(target["bank_account"])


async def test_admin_operator_applications_require_admin_role(client: AsyncClient):
    """admin以外は業者申込一覧にアクセスできない（403）。"""
    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="no_admin_access@example.com"),
    )
    assert r.status_code == 201

    user_token = await _signup_user(client, "not_admin@example.com")
    r = await client.get(
        "/api/v1/admin/operator-applications", headers=_auth(user_token)
    )
    assert r.status_code == 403


async def test_admin_reveal_bank_account_returns_full_number(
    client: AsyncClient, db_session: AsyncSession
):
    """admin限定の復号エンドポイントは口座番号全桁を返す。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="reveal_check@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.post(
        f"/api/v1/admin/operator-applications/{application_id}/reveal-bank-account",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["account_number"] == "1234567"
    assert data["account_holder"] == "シンセイテストカブシキガイシャ"


async def test_admin_approve_operator_application_issues_invite(
    client: AsyncClient, db_session: AsyncSession
):
    """承認フローでInviteが発行され、申込がapprovedになること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="approve_flow@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["application"]["status"] == "approved"
    assert data["invite_code"].startswith("KDZ-")

    # 発行されたInviteコードで実際に業者登録できること（申込時のemailと同一である必要がある）
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": data["invite_code"],
            "company_name": "申込テスト株式会社",
            "email": "approve_flow@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["operator"]["vendor_status"] == "active"

    # 承認済み申込を再承認しようとすると409
    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


async def test_operator_signup_invite_email_mismatch_403(
    client: AsyncClient, db_session: AsyncSession
):
    """承認発行された招待コード（emailに紐付け済み）を別emailで使おうとすると403になる。

    招待コード漏洩時に第三者が無審査でactive業者アカウントを作成できてしまう
    バイパスを防ぐための照合（security review High指摘対応）。
    """
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="mismatch_owner@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    invite_code = r.json()["invite_code"]

    # 招待コードの発行先とは異なるemailでsignupを試みる → 403
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": invite_code,
            "company_name": "なりすまし株式会社",
            "email": "attacker@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 403

    # Inviteが消費されていない（未使用のまま）ことも確認する
    from sqlalchemy import select as sa_select

    from app.db.models.invite import Invite

    invite = await db_session.scalar(sa_select(Invite).where(Invite.code == invite_code))
    assert invite is not None
    assert invite.used_at is None


async def test_operator_signup_invite_without_email_allows_any_email(
    client: AsyncClient, db_session: AsyncSession
):
    """emailに紐付いていない招待コード（admin/invitesの通常発行分）は従来通り任意emailで使える（回帰確認）。"""
    admin_token = await _make_admin(client, db_session)
    code = await _invite_code(client, admin_token)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "オープン招待株式会社",
            "email": "anyone_can_use@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["operator"]["vendor_status"] == "active"


async def test_admin_reject_operator_application(
    client: AsyncClient, db_session: AsyncSession
):
    """却下フローでstatus=rejected・reject_reasonが記録されること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="reject_flow@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/reject",
        json={"reject_reason": "古物商許可番号の記載内容に不備があるため"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "rejected"
    assert data["reject_reason"] == "古物商許可番号の記載内容に不備があるため"


# ──────────────────────────── チャット・日程調整・プロフィール・最高入札額 ────────────────────────────


async def _create_transaction(
    client: AsyncClient,
    user_token: str,
    op_token: str,
    amount: int = 30000,
) -> tuple[str, str]:
    """案件作成 → 入札 → 落札まで進め、(case_id, transaction_id) を返す。"""
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": amount},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    return case["id"], r.json()["id"]


async def _pending_operator_token(
    client: AsyncClient, db_session: AsyncSession, email: str, company: str = "承認待ち業者"
) -> tuple[str, str]:
    """招待コードなしでオープン登録し、vendor_status=pending のトークンを返す。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": company,
            "email": email,
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["operator"]["vendor_status"] == "pending"
    return data["access_token"], data["operator"]["id"]


async def _force_select_bid_for_pending_operator(
    db_session: AsyncSession, case_id: str, op_id: str, amount: int = 20000
) -> str:
    """pending 業者を落札業者として成約を強制生成する（入札API自体は403でブロックされるため
    DB直接操作でテスト用に成約状態を作る）。承認待ち業者でもチャット可能かを検証する目的。
    """
    from app.db.models.bid import Bid
    from app.db.models.case import Case
    from app.db.models.transaction import Transaction

    case = await db_session.get(Case, uuid.UUID(case_id))
    bid = Bid(
        case_id=case.id,
        operator_id=uuid.UUID(op_id),
        amount=amount,
        status="selected",
    )
    db_session.add(bid)
    case.status = "closed"
    await db_session.commit()
    await db_session.refresh(bid)

    txn = Transaction(
        case_id=case.id,
        bid_id=bid.id,
        initial_amount=amount,
        fee_amount=0,
        status="pending",
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)
    return str(txn.id)


# ── メッセージ ──


async def test_messages_non_party_forbidden(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "msg_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "msg_op@example.com")
    other_user_token = await _signup_user(client, "msg_other@example.com")
    other_op_token, _ = await _verified_operator(
        client, db_session, admin_token, "msg_other_op@example.com", "無関係業者"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(other_user_token))
    assert r.status_code == 403
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "なりすまし"},
        headers=_auth(other_op_token),
    )
    assert r.status_code == 403


async def test_messages_send_and_after_diff(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "msg_diff_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "msg_diff_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "訪問可能日はいつですか？"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    msg1 = r.json()
    assert msg1["mine"] is True
    assert msg1["sender_type"] == "user"

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(op_token))
    assert r.status_code == 200
    msgs = r.json()
    assert len(msgs) == 1
    assert msgs[0]["mine"] is False

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "来週火曜はいかがですか"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201

    # SQLite（テスト用インメモリDB）は created_at が秒精度のため、同一トランザクション内の
    # 連続送信では msg1/msg2 が同一タイムスタンプになり得る。after 差分取得の境界挙動
    # （strictly greater than）を確実に検証するため、msg1 の created_at を明示的に
    # 1秒巻き戻してから after クエリを実行する。
    from datetime import timedelta

    from app.db.models.message import Message

    msg1_row = await db_session.get(Message, uuid.UUID(msg1["id"]))
    msg1_row.created_at = msg1_row.created_at - timedelta(seconds=1)
    await db_session.commit()
    # after_ts は「巻き戻し後」の msg1_row.created_at をそのまま基準にする。
    # こうすると after クエリは Message.created_at > after_ts（strictly greater
    # than）なので、msg1（= after_ts と同値）は境界で除外され、msg2（元の
    # created_at。msg1 と同一秒で作成されていても巻き戻し後の msg1 より後）だけが
    # 含まれる。巻き戻し前の msg1["created_at"] を使うと、msg1/msg2 が同一秒で
    # 作成された場合に after_ts == msg2.created_at となり msg2 まで除外されて
    # diff が空になり、テストがフレーキーになる。
    after_ts = msg1_row.created_at.isoformat()

    r = await client.get(
        f"/api/v1/transactions/{txn_id}/messages",
        params={"after": after_ts},
        headers=_auth(user_token),
    )
    assert r.status_code == 200
    diff = r.json()
    assert len(diff) == 1
    assert diff[0]["body"] == "来週火曜はいかがですか"


async def test_messages_sender_type_cannot_be_spoofed(
    client: AsyncClient, db_session: AsyncSession
):
    """リクエストボディに sender_type を含めても無視され、actor から自動判定される。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "spoof_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "spoof_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "なりすまし試行", "sender_type": "operator"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201
    assert r.json()["sender_type"] == "user"


async def test_messages_unread_count_after_read(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "unread_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "unread_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "1通目"},
        headers=_auth(user_token),
    )
    await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "2通目"},
        headers=_auth(user_token),
    )

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["unread_count"] == 2

    r = await client.post(f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(op_token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.json()["unread_count"] == 0

    # ユーザー側の未読は業者の既読処理に影響しない
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.json()["unread_count"] == 0


async def test_pending_operator_can_chat(client: AsyncClient, db_session: AsyncSession):
    """承認待ち(vendor_status=pending)業者が落札した成約でもチャット送受信できる
    （住所非開示のみで会話は許可という確定方針）。
    """
    user_token = await _signup_user(client, "pending_chat_user@example.com")
    case = await _create_case(client, user_token)
    op_token, op_id = await _pending_operator_token(client, db_session, "pending_chat_op@example.com")

    txn_id = await _force_select_bid_for_pending_operator(db_session, case["id"], op_id)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["awaiting_approval"] is True
    assert r.json()["address"] is None

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "承認待ちですが訪問希望日をご相談できますか"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(user_token))
    assert r.status_code == 200
    assert len(r.json()) == 1


# ── 日程調整 ──


async def test_schedule_propose_operator_only(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "sched_propose_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "sched_propose_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["2026-07-10 午前", "2026-07-11 午後"]},
        headers=_auth(user_token),
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["2026-07-10 午前", "2026-07-11 午後"]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "schedule_proposal"
    assert data["meta"]["slots"] == ["2026-07-10 午前", "2026-07-11 午後"]


async def test_schedule_confirm_user_only_and_status_transition(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "sched_confirm_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "sched_confirm_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": "2026-07-15", "visit_time_slot": "午前"},
        headers=_auth(op_token),
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": "2026-07-15", "visit_time_slot": "午前", "note": "在宅確認済み"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "visiting"
    assert data["visit_date"] == "2026-07-15"
    assert data["visit_time_slot"] == "午前"

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(user_token))
    assert r.status_code == 200
    kinds = [m["kind"] for m in r.json()]
    assert "schedule_confirmed" in kinds


# ── 開示ゲート回帰（既存フローが壊れていないこと） ──


async def test_regression_full_flow_still_passes_with_new_fields(
    client: AsyncClient, db_session: AsyncSession
):
    """既存の落札〜成約詳細取得フローが新規カラム追加後も200で動作し、
    新規フィールド（unread_count, visit_time_slot）が妥当な初期値を持つこと。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "regression_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "regression_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200
    data = r.json()
    assert data["unread_count"] == 0
    assert data["visit_time_slot"] is None
    assert data["address"] is not None


# ── プロフィール ──


async def test_operator_profile_strong_categories_must_be_subset(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "profile_subset_op@example.com")

    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都"],
            "categories": ["家電", "家具"],
            "strong_categories": ["家電", "書籍"],
            "is_public": True,
            "show_stats": True,
            "show_reviews": True,
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 422


async def test_operator_profile_update_ignores_verified_fields(
    client: AsyncClient, db_session: AsyncSession
):
    """company_name 等の審査確定項目を PUT ボディに含めても無視され、更新されないこと。"""
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "profile_immutable_op@example.com", "元の会社名"
    )

    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "company_name": "書き換え試行株式会社",
            "license_number": "第000000000000号",
            "areas": ["東京都", "神奈川県"],
            "categories": ["家電"],
            "strong_categories": ["家電"],
            "business_hours": "9:00-18:00",
            "intro_message": "丁寧に対応します。",
            "is_public": True,
            "show_stats": True,
            "show_reviews": True,
            "show_message": True,
            "accept_unsellable": True,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["company_name"] == "元の会社名"
    assert data["areas"] == ["東京都", "神奈川県"]
    assert data["accept_unsellable"] is True

    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["company_name"] == "元の会社名"


async def test_operator_profile_first_access_auto_creates(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "profile_autocreate_op@example.com")

    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 200
    data = r.json()
    assert data["areas"] == []
    assert data["is_public"] is True


async def test_vendor_public_profile_respects_show_flags(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "public_profile_op@example.com", "公開プロフィール株式会社"
    )
    await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都"],
            "categories": ["家電"],
            "strong_categories": ["家電"],
            "intro_message": "秘密のメッセージ",
            "is_public": True,
            "show_stats": True,
            "show_reviews": True,
            "show_message": False,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )

    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["intro_message"] is None  # show_message=False のため省かれる
    assert data["company_name"] == "公開プロフィール株式会社"


async def test_vendor_public_profile_404_when_not_public(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "private_profile_op@example.com", "非公開株式会社"
    )
    await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": [],
            "categories": [],
            "strong_categories": [],
            "is_public": False,
            "show_stats": True,
            "show_reviews": True,
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )

    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 404


# ── 最高入札額 ──


async def test_top_bid_amount_reflects_max_across_operators(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "topbid_user@example.com")
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "topbid_op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "topbid_op2@example.com", "B社")
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 40000}, headers=_auth(op1_token)
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 55000}, headers=_auth(op2_token)
    )
    assert r.status_code == 201

    r = await client.get("/api/v1/cases", headers=_auth(op1_token))
    assert r.status_code == 200
    target = next(c for c in r.json() if c["id"] == case["id"])
    assert target["top_bid_amount"] == 55000

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(op2_token))
    assert r.status_code == 200
    assert r.json()["top_bid_amount"] == 55000
