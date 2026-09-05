"""依頼者の本人確認（/users/me/identity, /users/me/identity-documents, /admin/identity-documents）
の統合テスト。

in-memory SQLite + ASGITransport（tests/conftest.py のフィクスチャを利用。client
フィクスチャ等は test_operator_license_image.py / test_account_api.py のパターンを
ローカルに複製する）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.user import User
from app.db.models.user_identity_document import UserIdentityDocument
from app.db.session import get_session
from app.services.storage import sniff_image_ext

_JST = timezone(timedelta(hours=9), name="Asia/Tokyo")


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
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _set_birth_date(client: AsyncClient, token: str, birth_date: str | None) -> None:
    payload = {
        "family_name": "田中",
        "given_name": "太郎",
        "family_name_kana": "タナカ",
        "given_name_kana": "タロウ",
    }
    if birth_date is not None:
        payload["birth_date"] = birth_date
    r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text


def _adult_birth_date_str() -> str:
    """今日ちょうど18歳になる生年月日（境界=OK側）。"""
    today = datetime.now(_JST).date()
    return date(today.year - 18, today.month, today.day).isoformat()


def _minor_birth_date_str() -> str:
    """明日18歳になる（＝今日はまだ17歳・境界=NG側）生年月日。"""
    today = datetime.now(_JST).date()
    return (date(today.year - 18, today.month, today.day) + timedelta(days=1)).isoformat()


# PNG/WEBPのマジックバイト（operator_license テストと同じ作法）。
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
_WEBP_BYTES = b"RIFF" + (8).to_bytes(4, "little") + b"WEBP" + b"\x00" * 64
_NOT_IMAGE_BYTES = b"this is definitely not an image file" * 10
assert sniff_image_ext(_PNG_BYTES) == "png"
assert sniff_image_ext(_WEBP_BYTES) == "webp"


async def _adult_user(client: AsyncClient, email: str) -> str:
    token = await _signup_user(client, email)
    await _set_birth_date(client, token, _adult_birth_date_str())
    return token


def _files(doc_type: str, *, with_back: bool = True) -> dict:
    files = {
        "doc_type": (None, doc_type),
        "front": ("front.png", _PNG_BYTES, "image/png"),
    }
    if with_back:
        files["back"] = ("back.png", _PNG_BYTES, "image/png")
    return files


IDENTITY_URL = "/api/v1/users/me/identity-documents"


# ──────────────────────────── 裏面必須マトリクス ────────────────────────────


class TestBackRequirementMatrix:
    @pytest.mark.parametrize(
        "doc_type", ["drivers_license", "residence_card", "health_insurance_card"]
    )
    async def test_back_required_missing_returns_422(self, client: AsyncClient, doc_type: str):
        token = await _adult_user(client, f"back_missing_{doc_type}@example.com")
        r = await client.post(
            IDENTITY_URL, files=_files(doc_type, with_back=False), headers=_auth(token)
        )
        assert r.status_code == 422, r.text

    @pytest.mark.parametrize(
        "doc_type", ["drivers_license", "residence_card", "health_insurance_card"]
    )
    async def test_back_required_provided_returns_200(self, client: AsyncClient, doc_type: str):
        token = await _adult_user(client, f"back_ok_{doc_type}@example.com")
        r = await client.post(
            IDENTITY_URL, files=_files(doc_type, with_back=True), headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        assert r.json()["has_back"] is True

    @pytest.mark.parametrize("doc_type", ["my_number_card", "passport"])
    async def test_back_discarded_for_my_number_and_passport(
        self, client: AsyncClient, doc_type: str
    ):
        token = await _adult_user(client, f"back_discard_{doc_type}@example.com")
        r = await client.post(
            IDENTITY_URL, files=_files(doc_type, with_back=True), headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        assert r.json()["has_back"] is False

    @pytest.mark.parametrize("doc_type", ["my_number_card", "passport"])
    async def test_back_optional_omitted_still_succeeds(
        self, client: AsyncClient, doc_type: str
    ):
        token = await _adult_user(client, f"back_omit_{doc_type}@example.com")
        r = await client.post(
            IDENTITY_URL, files=_files(doc_type, with_back=False), headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        assert r.json()["has_back"] is False


# ──────────────────────────── 生年月日・年齢前提 ────────────────────────────


class TestAgeAndBirthDatePreconditions:
    async def test_birth_date_not_registered_returns_422(self, client: AsyncClient):
        token = await _signup_user(client, "no_birth_date@example.com")
        r = await client.post(
            IDENTITY_URL, files=_files("passport"), headers=_auth(token)
        )
        assert r.status_code == 422, r.text
        assert "生年月日" in r.text

    async def test_turns_18_today_is_allowed(self, client: AsyncClient):
        token = await _signup_user(client, "turns18_today@example.com")
        await _set_birth_date(client, token, _adult_birth_date_str())
        r = await client.post(
            IDENTITY_URL, files=_files("passport"), headers=_auth(token)
        )
        assert r.status_code == 200, r.text

    async def test_turns_18_tomorrow_is_rejected(self, client: AsyncClient):
        token = await _signup_user(client, "turns18_tomorrow@example.com")
        await _set_birth_date(client, token, _minor_birth_date_str())
        r = await client.post(
            IDENTITY_URL, files=_files("passport"), headers=_auth(token)
        )
        assert r.status_code == 422, r.text


# ──────────────────────────── 再提出・重複提出の状態遷移 ────────────────────────────


class TestResubmissionStateMachine:
    async def test_resubmit_while_pending_returns_409(self, client: AsyncClient):
        token = await _adult_user(client, "pending_resubmit@example.com")
        r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        assert r1.status_code == 200, r1.text

        r2 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        assert r2.status_code == 409

    async def test_resubmit_after_rejection_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session, "identity_admin1@katadzuke.jp")
        token = await _adult_user(client, "rejected_resubmit@example.com")
        r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        assert r1.status_code == 200, r1.text
        document_id = r1.json()["document_id"]

        r2 = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/reject",
            json={"reject_reason": "画像が不鮮明です。"},
            headers=_auth(admin_token),
        )
        assert r2.status_code == 200, r2.text

        r3 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        assert r3.status_code == 200, r3.text

        r4 = await client.get("/api/v1/users/me/identity", headers=_auth(token))
        assert r4.json()["status"] == "pending"

    async def test_resubmit_after_approval_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session, "identity_admin2@katadzuke.jp")
        token = await _adult_user(client, "approved_resubmit@example.com")
        r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        document_id = r1.json()["document_id"]

        r2 = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/approve", headers=_auth(admin_token)
        )
        assert r2.status_code == 200, r2.text

        r3 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        assert r3.status_code == 409


# ──────────────────────────── 非画像・IDOR ────────────────────────────


class TestFileValidationAndIDOR:
    async def test_non_image_front_returns_422(self, client: AsyncClient):
        token = await _adult_user(client, "non_image@example.com")
        files = {
            "doc_type": (None, "passport"),
            "front": ("front.png", _NOT_IMAGE_BYTES, "image/png"),
        }
        r = await client.post(IDENTITY_URL, files=files, headers=_auth(token))
        assert r.status_code == 422

    async def test_other_users_document_id_returns_404(self, client: AsyncClient):
        token1 = await _adult_user(client, "idor_owner@example.com")
        token2 = await _adult_user(client, "idor_attacker@example.com")

        r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token1))
        document_id = r1.json()["document_id"]

        r2 = await client.get(
            f"{IDENTITY_URL}/{document_id}/file",
            params={"side": "front"},
            headers=_auth(token2),
        )
        assert r2.status_code == 404

        # 本人は取得できる（IDORではなく認可が正しく機能していることの対照確認）。
        r3 = await client.get(
            f"{IDENTITY_URL}/{document_id}/file",
            params={"side": "front"},
            headers=_auth(token1),
        )
        assert r3.status_code == 200

    async def test_back_zero_bytes_on_required_doc_type_returns_422(self, client: AsyncClient):
        """裏面必須の書類種別で、裏面フィールドは存在するが中身が0バイトの場合は
        「裏面未提出」と同様に扱い422を返す（QA M-4）。"""
        token = await _adult_user(client, "back_zero_bytes@example.com")
        files = {
            "doc_type": (None, "drivers_license"),
            "front": ("front.png", _PNG_BYTES, "image/png"),
            "back": ("back.png", b"", "image/png"),
        }
        r = await client.post(IDENTITY_URL, files=files, headers=_auth(token))
        assert r.status_code == 422, r.text


class TestIdentitySubmitRateLimit:
    async def test_identity_submit_rate_limited_returns_429(self, db_session: AsyncSession):
        """scope=identity_submit の user_id 軸レート制限が上限超過で429を返すことを確認する
        （QA M-3）。test_user_profile_ext.py の bank-account レート制限テストと同じパターン。
        """
        from app.api.rate_limit_deps import get_rate_limiter
        from app.core.rate_limit import (
            InMemoryRateLimitStore,
            RateLimitConfig,
            RateLimitRule,
            RateLimiter,
        )

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
            token = await _adult_user(client, "identity_rl@example.com")

            r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
            assert r1.status_code == 200, r1.text

            r2 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
            assert r2.status_code == 429
            assert "Retry-After" in r2.headers


# ──────────────────────────── admin: 一覧・承認・却下 ────────────────────────────


class TestAdminReview:
    async def test_list_defaults_to_pending_and_approve_syncs_identity_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session, "identity_admin3@katadzuke.jp")
        token = await _adult_user(client, "admin_flow_user1@example.com")
        r1 = await client.post(
            IDENTITY_URL, files=_files("drivers_license"), headers=_auth(token)
        )
        document_id = r1.json()["document_id"]

        r_list = await client.get(
            "/api/v1/admin/identity-documents", headers=_auth(admin_token)
        )
        assert r_list.status_code == 200
        # r10 O-M1: 応答は {items,total,counts}（従来は素の list）。
        list_body = r_list.json()
        ids = [d["id"] for d in list_body["items"]]
        assert document_id in ids
        assert list_body["total"] == 1
        assert list_body["counts"]["pending"] == 1

        r_approve = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/approve", headers=_auth(admin_token)
        )
        assert r_approve.status_code == 200, r_approve.text
        assert r_approve.json()["status"] == "approved"

        r_profile = await client.get("/api/v1/users/me/profile", headers=_auth(token))
        assert r_profile.json()["identity_status"] == "approved"

    async def test_reject_requires_reason_and_syncs_identity_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session, "identity_admin4@katadzuke.jp")
        token = await _adult_user(client, "admin_flow_user2@example.com")
        r1 = await client.post(
            IDENTITY_URL, files=_files("health_insurance_card"), headers=_auth(token)
        )
        document_id = r1.json()["document_id"]

        r_missing_reason = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/reject",
            json={"reject_reason": ""},
            headers=_auth(admin_token),
        )
        assert r_missing_reason.status_code == 422

        r_reject = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/reject",
            json={"reject_reason": "画像不鮮明"},
            headers=_auth(admin_token),
        )
        assert r_reject.status_code == 200, r_reject.text
        assert r_reject.json()["status"] == "rejected"

        r_profile = await client.get("/api/v1/users/me/profile", headers=_auth(token))
        assert r_profile.json()["identity_status"] == "rejected"

    async def test_admin_file_view_is_audit_logged(
        self, client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ):
        admin_token = await _make_admin(client, db_session, "identity_admin5@katadzuke.jp")
        token = await _adult_user(client, "admin_flow_user3@example.com")
        r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        document_id = r1.json()["document_id"]

        with caplog.at_level(logging.INFO):
            r2 = await client.get(
                f"/api/v1/admin/identity-documents/{document_id}/file",
                params={"side": "front"},
                headers=_auth(admin_token),
            )
        assert r2.status_code == 200
        assert r2.headers["cache-control"] == "private, no-store"
        assert any(
            "本人確認書類を閲覧しました" in rec.message and str(document_id) in rec.message
            for rec in caplog.records
        )

    async def test_list_is_audit_logged(
        self, client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ):
        """一覧取得もPIIをログに書かずに監査ログを残す（M-3）。"""
        admin_token = await _make_admin(client, db_session, "identity_admin6@katadzuke.jp")
        token = await _adult_user(client, "admin_flow_user4@example.com")
        await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))

        with caplog.at_level(logging.INFO):
            r = await client.get(
                "/api/v1/admin/identity-documents", headers=_auth(admin_token)
            )
        assert r.status_code == 200
        assert any(
            "本人確認書類一覧を取得しました" in rec.message and "status=pending" in rec.message
            for rec in caplog.records
        )
        # PII本体（提出者のメールアドレス）はログに含めない。
        assert not any("admin_flow_user4@example.com" in rec.message for rec in caplog.records)


class TestAdminAccessControl:
    async def test_general_user_forbidden_from_admin_identity_endpoints(
        self, client: AsyncClient
    ):
        """一般ユーザーのJWTでは /admin/identity-documents* が403になる（Sec L-1）。"""
        token = await _adult_user(client, "not_admin@example.com")

        r_list = await client.get(
            "/api/v1/admin/identity-documents", headers=_auth(token)
        )
        assert r_list.status_code == 403

        r_approve = await client.patch(
            f"/api/v1/admin/identity-documents/{uuid.uuid4()}/approve", headers=_auth(token)
        )
        assert r_approve.status_code == 403

        r_reject = await client.patch(
            f"/api/v1/admin/identity-documents/{uuid.uuid4()}/reject",
            json={"reject_reason": "test"},
            headers=_auth(token),
        )
        assert r_reject.status_code == 403


class TestAdminDeletedUserDocuments:
    async def test_list_excludes_documents_of_deleted_users(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """退会（匿名化）済みユーザーの書類は一覧から除外される（QA M-2）。"""
        admin_token = await _make_admin(client, db_session, "identity_admin7@katadzuke.jp")
        token = await _adult_user(client, "deleted_before_review@example.com")
        r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        document_id = r1.json()["document_id"]

        r_delete = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"password": "password123", "confirm": True},
            headers=_auth(token),
        )
        assert r_delete.status_code == 200, r_delete.text

        r_list = await client.get(
            "/api/v1/admin/identity-documents",
            params={"status": "all"},
            headers=_auth(admin_token),
        )
        assert r_list.status_code == 200
        list_body = r_list.json()
        ids = [d["id"] for d in list_body["items"]]
        assert document_id not in ids
        # total / counts も一覧と同じ除外条件（退会済みは審査対象外）で数える。
        assert list_body["total"] == 0
        assert list_body["counts"] == {"pending": 0, "approved": 0, "rejected": 0}

    async def test_approve_erased_document_returns_410(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """退会により画像本体が消去済みの書類は承認しようとすると410になる（QA M-2）。"""
        admin_token = await _make_admin(client, db_session, "identity_admin8@katadzuke.jp")
        token = await _adult_user(client, "deleted_then_approve@example.com")
        r1 = await client.post(IDENTITY_URL, files=_files("passport"), headers=_auth(token))
        document_id = r1.json()["document_id"]

        r_delete = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"password": "password123", "confirm": True},
            headers=_auth(token),
        )
        assert r_delete.status_code == 200, r_delete.text

        r_approve = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/approve",
            headers=_auth(admin_token),
        )
        assert r_approve.status_code == 410, r_approve.text

        r_reject = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/reject",
            json={"reject_reason": "test"},
            headers=_auth(admin_token),
        )
        assert r_reject.status_code == 410, r_reject.text


# ──────────────────────────── 退会後の匿名化 ────────────────────────────


class TestAccountDeletionAnonymizesDocuments:
    async def test_images_none_but_row_and_status_remain_after_deletion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await _adult_user(client, "delete_flow_user@example.com")
        r1 = await client.post(
            IDENTITY_URL, files=_files("drivers_license"), headers=_auth(token)
        )
        document_id = r1.json()["document_id"]

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
                    UserIdentityDocument.status,
                    UserIdentityDocument.front_image_data,
                    UserIdentityDocument.back_image_data,
                ).where(UserIdentityDocument.id == uuid.UUID(document_id))
            )
        ).first()
        assert row is not None
        status_value, front_data, back_data = row
        assert status_value == "pending"
        assert front_data is None
        assert back_data is None
