"""admin専用エンドポイントの認可負テスト（QA r4-review H2対応）。

対象根拠: `.agent-state/audit/r4-review.md` H2
「事前申込の GET /{id}・reveal-bank-account（口座全桁）・approve・reject に
認可の負テスト0件」。あわせて r3 で新設した admin/{cases,transactions,users} の
GET と admin/users/{id}/{suspend,promote,demote} についても、依頼者(user)・
業者(operator)・無トークン の3主体で 401/403 になることを検証する
（各ルートが個々に admin ゲートへ依存しており、1箇所の実装ミスが即座に
権限バイパスへ直結するため、ルート単位で網羅する）。

既存カバレッジとの関係:
- test_katadzuke_api.py::test_admin_operator_applications_require_admin_role は
  一覧APIのみ（依頼者トークンのみ）を確認しており、GET /{id}・reveal-bank-account・
  approve・reject の4ルートには負テストが無かった → 本ファイルで新規追加。
- test_katadzuke_api.py::test_admin_list_cases_and_transactions は業者トークン・
  無トークンのみ確認（依頼者トークンが未検証）→ 本ファイルで依頼者トークンを補完。
- test_admin_user_controls.py の suspend/promote/demote は依頼者トークン・
  無トークンのみ確認（業者トークンが未検証）→ 本ファイルで業者トークンを補完。
- GET /admin/users には認可負テストが1件も無かった → 本ファイルで新規追加。
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
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="admin_authz_neg@katadzoku.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_authz_neg@katadzoku.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "依頼者太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _signup_operator(client: AsyncClient, admin_token: str, email: str) -> str:
    """招待コードを発行して業者アカウントを作り、アクセストークンを返す。"""
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "認可負テスト株式会社",
            "email": email,
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.fixture
async def principals(client: AsyncClient, db_session: AsyncSession) -> dict[str, str | None]:
    """(admin_token, user_token, operator_token, no-token) の3負け主体+adminをまとめて用意する。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "authz_neg_user@example.com")
    operator_token = await _signup_operator(client, admin_token, "authz_neg_operator@example.com")
    return {
        "admin": admin_token,
        "user": user_token,
        "operator": operator_token,
        "none": None,
    }


# ──────────────────────────── 業者事前申込（審査） ────────────────────────────


def _application_payload(email: str) -> dict:
    return {
        "company_name": "認可負テスト対象株式会社",
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
            "account_holder": "ニンカフテストカブシキガイシャ",
        },
        "agreed": True,
    }


@pytest.fixture
async def application_id(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/operator-applications", json=_application_payload("authz_neg_app@example.com")
    )
    assert r.status_code == 201, r.text
    return r.json()["application_id"]


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_get_operator_application_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], application_id: str, principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.get(
        f"/api/v1/admin/operator-applications/{application_id}", headers=headers
    )
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_reveal_bank_account_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], application_id: str, principal: str
):
    """口座全桁の開示は特に機微度が高いため、権限漏れが即座に情報漏洩へ直結する。"""
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.post(
        f"/api/v1/admin/operator-applications/{application_id}/reveal-bank-account",
        headers=headers,
    )
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_approve_operator_application_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], application_id: str, principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve", headers=headers
    )
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_reject_operator_application_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], application_id: str, principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/reject",
        json={"reject_reason": "不備があるため"},
        headers=headers,
    )
    assert r.status_code in (401, 403), r.text


# ──────────────────────────── admin: 案件・成約・依頼者一覧（横断閲覧） ────────────────────────────


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_admin_list_cases_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.get("/api/v1/admin/cases", headers=headers)
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_admin_list_transactions_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.get("/api/v1/admin/transactions", headers=headers)
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_admin_list_users_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.get("/api/v1/admin/users", headers=headers)
    assert r.status_code in (401, 403), r.text


# ──────────────────────────── admin: 依頼者の停止／権限昇降格 ────────────────────────────


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_suspend_user_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}/suspend",
        json={"suspended": True},
        headers=headers,
    )
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_promote_user_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.post(f"/api/v1/admin/users/{uuid.uuid4()}/promote", headers=headers)
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("principal", ["user", "operator", "none"])
async def test_demote_user_requires_admin(
    client: AsyncClient, principals: dict[str, str | None], principal: str
):
    token = principals[principal]
    headers = _auth(token) if token else {}
    r = await client.post(f"/api/v1/admin/users/{uuid.uuid4()}/demote", headers=headers)
    assert r.status_code in (401, 403), r.text
