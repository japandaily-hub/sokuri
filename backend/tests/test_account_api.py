"""アカウント（マイページ）API の統合テスト — プロフィール / パスワード変更 / 退会。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用。
client フィクスチャ等は test_katadzuke_api.py のパターンを踏襲しローカルに複製する）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import create_access_token, hash_password
from app.db.models.case import Case
from app.db.models.transaction import Transaction
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
    assert r.status_code == 200
    return r.json()["access_token"]


async def _signup_user(
    client: AsyncClient, email: str = "user1@example.com", password: str = "password123"
) -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _invite_code(client: AsyncClient, admin_token: str) -> str:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
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
    assert r.status_code == 201, r.text
    data = r.json()
    return data["access_token"], data["operator"]["id"]


async def _verified_operator(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    email: str,
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
        "photos": [],
    }


async def _create_case(client: AsyncClient, user_token: str) -> dict:
    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(user_token))
    assert r.status_code == 201, r.text
    return r.json()


async def _create_transaction(
    client: AsyncClient, user_token: str, op_token: str, amount: int = 30000
) -> tuple[str, str]:
    """案件作成 → 入札 → 落札まで進め、(case_id, transaction_id) を返す。"""
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": amount}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return case["id"], r.json()["id"]


PROFILE_PAYLOAD = {
    "family_name": "田中",
    "given_name": "太郎",
    "family_name_kana": "タナカ",
    "given_name_kana": "タロウ",
    "phone": "090-1234-5678",
    "residence_area": "tokyo",
}


# ──────────────────────────── プロフィール ────────────────────────────


async def test_get_profile_initial(client: AsyncClient):
    token = await _signup_user(client)
    r = await client.get("/api/v1/users/me/profile", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == "user1@example.com"
    assert data["family_name"] is None
    assert data["given_name"] is None
    assert data["family_name_kana"] is None
    assert data["given_name_kana"] is None
    assert data["phone"] is None
    assert data["residence_area"] is None
    assert data["has_password"] is True
    assert data["line_linked"] is False


async def test_get_profile_unauthenticated_401(client: AsyncClient):
    r = await client.get("/api/v1/users/me/profile")
    assert r.status_code == 401


async def test_update_profile_persists_and_syncs_name(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _signup_user(client)
    r = await client.put("/api/v1/users/me/profile", json=PROFILE_PAYLOAD, headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["family_name"] == "田中"
    assert data["given_name"] == "太郎"
    assert data["family_name_kana"] == "タナカ"
    assert data["given_name_kana"] == "タロウ"
    assert data["phone"] == "090-1234-5678"
    assert data["residence_area"] == "tokyo"

    r = await client.get("/api/v1/users/me/profile", headers=_auth(token))
    assert r.status_code == 200
    persisted = r.json()
    assert persisted["family_name"] == "田中"
    assert persisted["given_name"] == "太郎"

    user = await db_session.scalar(select(User).where(User.email == "user1@example.com"))
    assert user is not None
    assert user.name == "田中 太郎"


async def test_update_profile_unauthenticated_401(client: AsyncClient):
    r = await client.put("/api/v1/users/me/profile", json=PROFILE_PAYLOAD)
    assert r.status_code == 401


# ── バリデーション422 ──


async def test_update_profile_missing_family_name_422(client: AsyncClient):
    token = await _signup_user(client)
    payload = dict(PROFILE_PAYLOAD)
    del payload["family_name"]
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 422


async def test_update_profile_invalid_residence_area_422(client: AsyncClient):
    token = await _signup_user(client)
    payload = dict(PROFILE_PAYLOAD)
    payload["residence_area"] = "hokkaido"
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 422


async def test_update_profile_non_kana_family_name_kana_422(client: AsyncClient):
    token = await _signup_user(client)
    payload = dict(PROFILE_PAYLOAD)
    payload["family_name_kana"] = "たなか"  # ひらがなは不可（全角カタカナのみ許容）
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 422


async def test_update_profile_invalid_phone_422(client: AsyncClient):
    token = await _signup_user(client)
    payload = dict(PROFILE_PAYLOAD)
    payload["phone"] = "abc-defg"
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 422


async def test_update_profile_whitespace_only_name_422(client: AsyncClient):
    """空白のみの姓名は strip 後に min_length で弾く（API直叩き対策）。"""
    token = await _signup_user(client)
    for blank in (" ", "　", " 　 "):
        payload = dict(PROFILE_PAYLOAD)
        payload["family_name"] = blank
        r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
        assert r.status_code == 422, f"family_name={blank!r} が通ってしまった"


async def test_update_profile_kana_control_whitespace_422(client: AsyncClient):
    """カナ欄はタブ・改行等の制御空白を弾く（通常の半角/全角スペースは複合姓カナ用に許容）。"""
    token = await _signup_user(client)
    payload = dict(PROFILE_PAYLOAD)
    payload["family_name_kana"] = "タナカ\tタロウ"
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 422

    payload["family_name_kana"] = "タナカ タロウ"  # 半角スペースは許容
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    payload["family_name_kana"] = "タナカ　タロウ"  # 全角スペースも許容
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text


# ──────────────────────────── パスワード変更 ────────────────────────────


async def test_change_password_success_and_token_rotation(client: AsyncClient):
    token = await _signup_user(client, "pwuser@example.com", "oldpassword1")
    # JWT の iat / password_changed_at は秒精度で比較する（deps.py の失効ゲート参照）。
    # in-memory SQLite + ASGI transport はミリ秒単位で完了するため、待機なしだと
    # signup と change-password が同一秒内に収まり iat 比較が真にならず旧トークンが
    # 失効しない（テストのみのタイミング起因の揺れ。ゲート実装は仕様通り）。
    # 秒境界を跨がせるため実時間で待機する。
    await asyncio.sleep(1.1)
    r = await client.put(
        "/api/v1/users/me/password",
        json={"current_password": "oldpassword1", "new_password": "newpassword1"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]
    assert new_token

    # 旧パスワードではログイン不可
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "pwuser@example.com", "password": "oldpassword1"},
    )
    assert r.status_code == 401

    # 新パスワードでログイン可能
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "pwuser@example.com", "password": "newpassword1"},
    )
    assert r.status_code == 200

    # 旧トークンはパスワード変更失効ゲートにより401
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.status_code == 401

    # レスポンスに含まれる新トークンは有効
    r = await client.get("/api/v1/auth/me", headers=_auth(new_token))
    assert r.status_code == 200


async def test_change_password_wrong_current_400(client: AsyncClient):
    token = await _signup_user(client, "pwuser2@example.com")
    r = await client.put(
        "/api/v1/users/me/password",
        json={"current_password": "wrongpassword", "new_password": "newpassword1"},
        headers=_auth(token),
    )
    assert r.status_code == 400


async def test_change_password_too_short_422(client: AsyncClient):
    token = await _signup_user(client, "pwuser3@example.com")
    r = await client.put(
        "/api/v1/users/me/password",
        json={"current_password": "password123", "new_password": "short12"},
        headers=_auth(token),
    )
    assert r.status_code == 422


async def test_change_password_line_only_user_409(client: AsyncClient, db_session: AsyncSession):
    user = User(
        email="lineuser@example.com",
        password_hash=None,
        name="LINEユーザー",
        role="user",
        line_user_id="U" + "a" * 32,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token(user.id, "user", user.role)

    r = await client.put(
        "/api/v1/users/me/password",
        json={"current_password": "whatever1", "new_password": "newpassword1"},
        headers=_auth(token),
    )
    assert r.status_code == 409


async def test_change_password_unauthenticated_401(client: AsyncClient):
    r = await client.put(
        "/api/v1/users/me/password",
        json={"current_password": "a", "new_password": "newpassword1"},
    )
    assert r.status_code == 401


# ──────────────────────────── アカウント削除（退会） ────────────────────────────


async def test_delete_account_confirm_false_422(client: AsyncClient):
    token = await _signup_user(client, "delconfirm@example.com")
    r = await client.request(
        "DELETE", "/api/v1/users/me", json={"confirm": False}, headers=_auth(token)
    )
    assert r.status_code == 422


async def test_delete_account_wrong_password_400(client: AsyncClient):
    token = await _signup_user(client, "delwrongpw@example.com")
    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "wrongpassword", "confirm": True},
        headers=_auth(token),
    )
    assert r.status_code == 400


async def test_delete_account_success(client: AsyncClient, db_session: AsyncSession):
    token = await _signup_user(client, "deluser@example.com", "correctpassword1")
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.status_code == 200
    user_id = r.json()["user"]["id"]

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "correctpassword1", "confirm": True},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["detail"]

    # 同一emailで再ログイン不可
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "deluser@example.com", "password": "correctpassword1"},
    )
    assert r.status_code == 401

    # 旧トークンは論理削除ゲートにより失効
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.status_code == 401

    # DB上で匿名化されていることを確認
    user = await db_session.get(User, uuid.UUID(user_id))
    assert user is not None
    assert user.email == f"deleted-{user.id}@deleted.katazuke.internal"
    assert user.phone is None
    assert user.line_user_id is None
    assert user.password_hash is None
    assert user.name is None
    assert user.family_name is None
    assert user.given_name is None
    assert user.deleted_at is not None


async def test_delete_account_line_only_user_no_password_needed(
    client: AsyncClient, db_session: AsyncSession
):
    user = User(
        email="linedel@example.com",
        password_hash=None,
        name="LINE退会ユーザー",
        role="user",
        line_user_id="U" + "b" * 32,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token(user.id, "user", user.role)

    r = await client.request(
        "DELETE", "/api/v1/users/me", json={"confirm": True}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text


async def test_delete_account_blocked_by_pending_transaction(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "delpending@example.com", "correctpassword1")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "delpending_op@example.com"
    )
    await _create_transaction(client, user_token, op_token)

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "correctpassword1", "confirm": True},
        headers=_auth(user_token),
    )
    assert r.status_code == 409


async def test_delete_account_blocked_by_visiting_transaction(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "delvisiting@example.com", "correctpassword1")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "delvisiting_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)

    visit_date = (date.today() + timedelta(days=7)).isoformat()
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": visit_date, "visit_time_slot": "10:00-12:00"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "visiting"

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "correctpassword1", "confirm": True},
        headers=_auth(user_token),
    )
    assert r.status_code == 409


async def test_delete_account_cancels_open_case_and_keeps_completed_transaction(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "delsideeffect@example.com", "correctpassword1")

    # 完了済み取引を1件作る（削除ブロック対象外・レコードは保持される想定）
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "delsideeffect_op@example.com"
    )
    completed_case_id, txn_id = await _create_transaction(client, user_token, op_token)
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"

    # 未成約のopen案件をもう1件作る（削除時にcancelled化される想定）
    open_case = await _create_case(client, user_token)

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "correctpassword1", "confirm": True},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text

    cancelled_case = await db_session.get(Case, uuid.UUID(open_case["id"]))
    assert cancelled_case is not None
    assert cancelled_case.status == "cancelled"
    assert cancelled_case.address_detail is None

    completed_txn = await db_session.get(Transaction, uuid.UUID(txn_id))
    assert completed_txn is not None
    assert completed_txn.status == "completed"

    completed_case = await db_session.get(Case, uuid.UUID(completed_case_id))
    assert completed_case is not None
    assert completed_case.address_detail is not None


async def test_transaction_contact_email_masked_after_account_deletion(
    client: AsyncClient, db_session: AsyncSession
):
    """退会後の完了取引詳細で、業者にトムストンメール（内部UUID入り）を開示しない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "delcontact@example.com", "correctpassword1")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "delcontact_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200, r.text

    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "correctpassword1", "confirm": True},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    contact_email = r.json()["contact_email"]
    assert contact_email == "退会済みユーザー"
    assert "deleted.katazuke.internal" not in contact_email


async def test_delete_account_then_resignup_with_same_email(client: AsyncClient):
    email = "reuse@example.com"
    token = await _signup_user(client, email, "correctpassword1")
    r = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": "correctpassword1", "confirm": True},
        headers=_auth(token),
    )
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "brandnewpass1", "name": "再登録ユーザー"},
    )
    assert r.status_code == 201


async def test_delete_account_unauthenticated_401(client: AsyncClient):
    r = await client.request("DELETE", "/api/v1/users/me", json={"confirm": True})
    assert r.status_code == 401
