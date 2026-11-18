"""依頼者の本人確認書類（身分証画像）の受付廃止の回帰テスト。

運転免許証等の画像を預からない方針（user_identity.py・alembic 0049）を固定する。

- 旧エンドポイント（依頼者・運営とも）はすべて 410 Gone を返し、DB に何も書かない。
- 画像付きの multipart を送っても本文を読まずに 410 を返す（行が増えない）。
- 認証の有無・他人の document_id にかかわらず同じ固定の応答（在不在を漏らさない）。
- 旧スコープ（identity_submit）・旧通知関数が残っていない（受付が復活しないためのガード）。
- 退会時の匿名化（過去に提出された画像列の NULL 化）は引き続き効く。
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

from app.api.v1.endpoints.user_identity import (
    IDENTITY_DOCUMENTS_RETIRED_DETAIL,
    RETIRED_IDENTITY_ROUTES,
)
from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.user import User
from app.db.models.user_identity_document import UserIdentityDocument
from app.db.session import get_session

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256


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


async def _make_admin(client: AsyncClient, db_session: AsyncSession, email: str) -> str:
    admin = User(
        email=email, password_hash=hash_password("adminpass123"), name="管理者", role="admin"
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "adminpass123"})
    assert r.status_code == 200
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"agreed_terms": True, "email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _concrete_path(path: str, document_id: uuid.UUID) -> str:
    return "/api/v1" + path.replace("{document_id}", str(document_id))


async def _insert_legacy_document(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """廃止前に提出された書類（画像入り）を直接作る。"""
    document = UserIdentityDocument(
        user_id=user_id,
        doc_type="drivers_license",
        front_image_data=_PNG_BYTES,
        front_image_content_type="image/png",
        back_image_data=_PNG_BYTES,
        back_image_content_type="image/png",
        status="pending",
        submitted_at=datetime.now(timezone.utc),
    )
    db_session.add(document)
    await db_session.commit()
    return document.id


class TestRetiredEndpoints:
    def test_route_table_covers_user_and_admin_endpoints(self):
        paths = {path for _, path in RETIRED_IDENTITY_ROUTES}
        assert "/users/me/identity-documents" in paths
        assert "/admin/identity-documents" in paths
        assert len(RETIRED_IDENTITY_ROUTES) == len(set(RETIRED_IDENTITY_ROUTES))

    @pytest.mark.parametrize("method,path", RETIRED_IDENTITY_ROUTES)
    async def test_every_retired_route_returns_410_without_auth(
        self, client: AsyncClient, method: str, path: str
    ):
        r = await client.request(method, _concrete_path(path, uuid.uuid4()))
        assert r.status_code == 410, r.text
        assert r.json() == {"detail": IDENTITY_DOCUMENTS_RETIRED_DETAIL}
        assert r.headers.get("cache-control") == "no-store"

    @pytest.mark.parametrize("method,path", RETIRED_IDENTITY_ROUTES)
    async def test_every_retired_route_returns_410_for_admin(
        self, client: AsyncClient, db_session: AsyncSession, method: str, path: str
    ):
        """運営でも審査・画像の取得はできない（画像を誰にも渡さない）。"""
        admin_token = await _make_admin(client, db_session, f"admin-{uuid.uuid4().hex[:8]}@example.com")
        r = await client.request(
            method, _concrete_path(path, uuid.uuid4()), headers=_auth(admin_token)
        )
        assert r.status_code == 410, r.text

    async def test_submit_with_images_stores_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await _signup_user(client, "retired_submit@example.com")
        r = await client.post(
            "/api/v1/users/me/identity-documents",
            files={
                "doc_type": (None, "drivers_license"),
                "front": ("front.png", _PNG_BYTES, "image/png"),
                "back": ("back.png", _PNG_BYTES, "image/png"),
            },
            headers=_auth(token),
        )
        assert r.status_code == 410, r.text
        count = await db_session.scalar(select(func.count()).select_from(UserIdentityDocument))
        assert count == 0
        user = (
            await db_session.execute(select(User).where(User.email == "retired_submit@example.com"))
        ).scalar_one()
        assert user.identity_status == "unverified"

    async def test_legacy_document_file_is_not_served_even_to_owner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """廃止前の行が残っていても（0049 適用前でも）画像は返さない。"""
        token = await _signup_user(client, "legacy_owner@example.com")
        owner = (
            await db_session.execute(select(User).where(User.email == "legacy_owner@example.com"))
        ).scalar_one()
        document_id = await _insert_legacy_document(db_session, owner.id)
        for side in ("front", "back"):
            r = await client.get(
                f"/api/v1/users/me/identity-documents/{document_id}/file?side={side}",
                headers=_auth(token),
            )
            assert r.status_code == 410
            assert _PNG_BYTES not in r.content


class TestNoIntakePathRemains:
    def test_rate_limit_scope_removed(self):
        from app.api.rate_limit_deps import _scope_spec
        from app.core.rate_limit import RateLimitConfig, RateLimitRule

        rule = RateLimitRule(5, 60)
        config = RateLimitConfig(
            enabled=True,
            login_account=rule,
            login_ip=rule,
            sensitive_account=rule,
            signup_ip=rule,
            line_ip=rule,
            max_keys=100,
        )
        with pytest.raises(ValueError):
            _scope_spec("identity_submit", config)

    def test_notify_functions_removed(self):
        from app.services import line_notify, notify, notify_dispatch

        assert not hasattr(notify, "send_identity_submitted_admin_alert")
        assert not hasattr(notify, "send_identity_document_reviewed")
        assert not hasattr(notify_dispatch, "dispatch_identity_document_reviewed")
        assert not hasattr(line_notify, "push_identity_document_reviewed")


class TestAccountDeletionStillErasesLegacyImages:
    async def test_images_none_but_row_remains_after_deletion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await _signup_user(client, "delete_flow_user@example.com")
        owner = (
            await db_session.execute(
                select(User).where(User.email == "delete_flow_user@example.com")
            )
        ).scalar_one()
        document_id = await _insert_legacy_document(db_session, owner.id)

        r_delete = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"password": "password123", "confirm": True},
            headers=_auth(token),
        )
        assert r_delete.status_code == 200, r_delete.text

        row = (
            await db_session.execute(
                select(
                    UserIdentityDocument.front_image_data,
                    UserIdentityDocument.back_image_data,
                ).where(UserIdentityDocument.id == document_id)
            )
        ).first()
        assert row is not None
        assert row == (None, None)


class TestAdminActivityKeepsPastReviews:
    async def test_past_reviews_listed_but_auto_closed_pending_is_not(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """過去の承認・差し戻しは運営の操作履歴に残り、0049 で自動終了した審査待ち
        （reviewed_at なし）は運営の操作として出ない。"""
        admin_token = await _make_admin(client, db_session, "activity_admin@example.com")
        admin = (
            await db_session.execute(select(User).where(User.email == "activity_admin@example.com"))
        ).scalar_one()
        await _signup_user(client, "activity_owner@example.com")
        owner = (
            await db_session.execute(select(User).where(User.email == "activity_owner@example.com"))
        ).scalar_one()
        now = datetime.now(timezone.utc)
        ids: dict[str, uuid.UUID] = {}
        for key, status_value, reviewed in (
            ("approved", "approved", True),
            ("rejected", "rejected", True),
            ("auto_closed", "rejected", False),
        ):
            document = UserIdentityDocument(
                user_id=owner.id,
                doc_type="drivers_license",
                front_image_data=None,
                front_image_content_type="image/png",
                status=status_value,
                submitted_at=now,
                reviewed_by=admin.id if reviewed else None,
                reviewed_at=now if reviewed else None,
                reject_reason="受付終了" if not reviewed else None,
            )
            db_session.add(document)
            await db_session.flush()
            ids[key] = document.id
        await db_session.commit()

        r = await client.get("/api/v1/admin/activity", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        entries = {
            item["target_id"]: item["action"]
            for item in r.json()["items"]
            if item["target_type"] == "identity_document"
        }
        assert entries == {
            str(ids["approved"]): "identity_document_approve",
            str(ids["rejected"]): "identity_document_reject",
        }
