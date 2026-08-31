"""業者許可証画像アップロード（/operator/license-image, /admin/operators/{id}/license-image）の統合テスト。

- アップロード: 成功(200) / 未認証401 / 非画像415 / 10MB超422 / 差し替え（上書き）
- 取得: 本人200 / 未アップロード404 / 一般ユーザー401 / admin取得200 / 非admin(業者)401
- deferred カラム: 通常の select(Operator) では license_image_data がロードされないこと
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.services.storage import MAX_UPLOAD_BYTES, sniff_image_ext


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
        email="admin_license@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_license@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str = "license_user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _invite_code(client: AsyncClient, admin_token: str) -> str:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201
    return r.json()["code"]


async def _verified_operator(
    client: AsyncClient,
    admin_token: str,
    email: str,
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


# PNGのマジックバイト（8バイトシグネチャ）+ ダミーボディ。
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
_NOT_IMAGE_BYTES = b"this is definitely not an image file" * 10


# ──────────────────────────── アップロード ────────────────────────────


class TestUploadLicenseImage:
    async def test_upload_success(self, client: AsyncClient, db_session: AsyncSession):
        admin_token = await _make_admin(client, db_session)
        op_token, op_id = await _verified_operator(client, admin_token, "license_op1@example.com")

        r = await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("license.png", _PNG_BYTES, "image/png")},
            headers=_auth(op_token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["uploaded_at"]

        operator = await db_session.get(Operator, uuid.UUID(op_id))
        assert operator.has_license_image is True
        assert operator.license_image_content_type == "image/png"

    async def test_upload_unauthenticated_401(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("license.png", _PNG_BYTES, "image/png")},
        )
        assert r.status_code == 401

    async def test_upload_non_image_415(self, client: AsyncClient, db_session: AsyncSession):
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(client, admin_token, "license_op2@example.com")

        r = await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("fake.png", _NOT_IMAGE_BYTES, "image/png")},
            headers=_auth(op_token),
        )
        assert r.status_code == 415

    async def test_upload_too_large_422(self, client: AsyncClient, db_session: AsyncSession):
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(client, admin_token, "license_op3@example.com")

        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_UPLOAD_BYTES + 1)
        r = await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("license.png", oversized, "image/png")},
            headers=_auth(op_token),
        )
        assert r.status_code == 422

    async def test_upload_replaces_existing(self, client: AsyncClient, db_session: AsyncSession):
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(client, admin_token, "license_op4@example.com")

        r1 = await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("license1.png", _PNG_BYTES, "image/png")},
            headers=_auth(op_token),
        )
        assert r1.status_code == 200

        webp_bytes = b"RIFF" + (8).to_bytes(4, "little") + b"WEBP" + b"\x00" * 64
        r2 = await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("license2.webp", webp_bytes, "image/webp")},
            headers=_auth(op_token),
        )
        assert r2.status_code == 200

        r3 = await client.get("/api/v1/operator/license-image", headers=_auth(op_token))
        assert r3.status_code == 200
        assert r3.content == webp_bytes
        assert r3.headers["content-type"] == "image/webp"


# ──────────────────────────── 取得 ────────────────────────────


class TestGetLicenseImage:
    async def test_get_own_image_success(self, client: AsyncClient, db_session: AsyncSession):
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(client, admin_token, "license_get1@example.com")
        await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("license.png", _PNG_BYTES, "image/png")},
            headers=_auth(op_token),
        )

        r = await client.get("/api/v1/operator/license-image", headers=_auth(op_token))
        assert r.status_code == 200
        assert r.content == _PNG_BYTES
        assert r.headers["content-type"] == "image/png"

    async def test_get_not_uploaded_404(self, client: AsyncClient, db_session: AsyncSession):
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(client, admin_token, "license_get2@example.com")

        r = await client.get("/api/v1/operator/license-image", headers=_auth(op_token))
        assert r.status_code == 404

    async def test_get_by_general_user_401(self, client: AsyncClient):
        user_token = await _signup_user(client, "license_get_user@example.com")
        r = await client.get("/api/v1/operator/license-image", headers=_auth(user_token))
        assert r.status_code == 401

    async def test_admin_can_get_operator_license_image(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session)
        op_token, op_id = await _verified_operator(client, admin_token, "license_get3@example.com")
        await client.post(
            "/api/v1/operator/license-image",
            files={"file": ("license.png", _PNG_BYTES, "image/png")},
            headers=_auth(op_token),
        )

        r = await client.get(
            f"/api/v1/admin/operators/{op_id}/license-image", headers=_auth(admin_token)
        )
        assert r.status_code == 200
        assert r.content == _PNG_BYTES

    async def test_non_admin_operator_cannot_use_admin_route(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session)
        op_token, op_id = await _verified_operator(client, admin_token, "license_get4@example.com")
        other_op_token, _ = await _verified_operator(
            client, admin_token, "license_get5@example.com"
        )

        r = await client.get(
            f"/api/v1/admin/operators/{op_id}/license-image", headers=_auth(other_op_token)
        )
        assert r.status_code == 401

    async def test_admin_get_not_uploaded_404(self, client: AsyncClient, db_session: AsyncSession):
        admin_token = await _make_admin(client, db_session)
        _, op_id = await _verified_operator(client, admin_token, "license_get6@example.com")

        r = await client.get(
            f"/api/v1/admin/operators/{op_id}/license-image", headers=_auth(admin_token)
        )
        assert r.status_code == 404


# ──────────────────────────── マジックバイト判定（sniff_image_ext） ────────────────────────────


class TestSniffImageExt:
    def test_jpeg(self):
        assert sniff_image_ext(b"\xff\xd8\xff\xe0" + b"\x00" * 10) == "jpeg"

    def test_png(self):
        assert sniff_image_ext(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10) == "png"

    def test_webp(self):
        data = b"RIFF" + (20).to_bytes(4, "little") + b"WEBP" + b"\x00" * 20
        assert sniff_image_ext(data) == "webp"

    def test_unknown_returns_none(self):
        assert sniff_image_ext(b"not an image at all") is None

    def test_content_type_and_extension_are_not_trusted(self):
        """拡張子/Content-Typeを詐称しても、実バイト列と矛盾すればNoneを返す。"""
        assert sniff_image_ext(b"<html>fake</html>") is None


# ──────────────────────────── deferredカラムの検証 ────────────────────────────


class TestLicenseImageDeferredColumn:
    async def test_license_image_data_not_loaded_by_default_select(
        self, db_session: AsyncSession
    ):
        """通常の select(Operator) では license_image_data がロードされないこと
        （全業者関連クエリでBLOBが毎回ロードされるとメモリ枯渇DoSの原因になるため）。"""
        operator = Operator(
            company_name="deferred検証株式会社",
            contact_email="deferred_check@example.com",
            password_hash=hash_password("operatorpass1"),
            vendor_status="active",
        )
        db_session.add(operator)
        await db_session.commit()
        await db_session.refresh(operator)

        operator.license_image_data = _PNG_BYTES
        operator.license_image_content_type = "image/png"
        operator.license_image_uploaded_at = datetime.now(timezone.utc)
        await db_session.commit()
        operator_id = operator.id  # expire_all前にPKを退避（expired属性への同期アクセスを避ける）

        # identity map のキャッシュを介さず、新規ロード時の挙動を検証するため expire する。
        db_session.expire_all()
        fetched = await db_session.scalar(
            select(Operator).where(Operator.id == operator_id)
        )
        state = sa_inspect(fetched)
        assert "license_image_data" in state.unloaded
        # content_type / uploaded_at は deferred にしていないため通常通りロードされる。
        assert "license_image_content_type" not in state.unloaded
        assert "license_image_uploaded_at" not in state.unloaded
        assert fetched.has_license_image is True
