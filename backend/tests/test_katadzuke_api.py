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
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
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


async def test_operator_signup_requires_valid_invite(client: AsyncClient):
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": "KDZ-NOTEXIST",
            "company_name": "X社",
            "email": "op@example.com",
            "password": "operatorpass1",
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


async def test_unverified_operator_cannot_list_cases(
    client: AsyncClient, db_session: AsyncSession
):
    """vendor_status=pending の業者は案件一覧にアクセス不可（403）。
    TASK-2: open 登録は limited（閲覧可）、pending は DB 直接挿入でのみ発生するエッジケース。
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
    assert r.status_code == 403


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
    """招待コードなしでオープン登録 → vendor_status=limited → 案件閲覧・入札可能。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "オープン登録業者テスト",
            "email": "open_op@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["operator"]["vendor_status"] == "limited"
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
    assert r.status_code == 201


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
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["operator"]["vendor_status"] == "active"


async def test_limited_operator_address_hidden(
    client: AsyncClient, db_session: AsyncSession
):
    """limited業者が落札した場合、住所情報は非開示でawaiting_approval=True。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "住所非開示テスト業者",
            "email": "limited_op@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 201
    limited_op_token = r.json()["access_token"]
    assert r.json()["operator"]["vendor_status"] == "limited"

    user_token = await _signup_user(client, "user_for_limited@example.com")
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(limited_op_token),
    )
    assert r.status_code == 201
    bid_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid_id}/select",
        headers=_auth(user_token),
    )
    assert r.status_code == 201
    txn_id = r.json()["id"]

    r = await client.get(
        f"/api/v1/transactions/{txn_id}",
        headers=_auth(limited_op_token),
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
        },
    )
    assert r.status_code == 201
    op_id = r.json()["operator"]["id"]
    assert r.json()["operator"]["vendor_status"] == "limited"

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
    assert data["vendor_status"] == "limited"
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
