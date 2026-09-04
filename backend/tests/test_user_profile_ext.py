"""マイページ拡張API（プロフィール後方互換 / 住所 / 振込先口座）の統合テスト。

in-memory SQLite + ASGITransport（tests/conftest.py のフィクスチャを利用。
client フィクスチャ等は test_account_api.py のパターンをローカルに複製する）。
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import get_rate_limiter
from app.api.v1.router import api_router
from app.core.rate_limit import InMemoryRateLimitStore, RateLimitConfig, RateLimitRule, RateLimiter
from app.core.security import create_access_token, hash_password
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


async def _signup_user(
    client: AsyncClient, email: str = "pex_user1@example.com", password: str = "password123"
) -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


PROFILE_PAYLOAD_LEGACY = {
    "family_name": "田中",
    "given_name": "太郎",
    "family_name_kana": "タナカ",
    "given_name_kana": "タロウ",
    "phone": "090-1234-5678",
    "residence_area": "tokyo",
}

VALID_BANK_PAYLOAD = {
    "bank_name": "カタヅケ銀行",
    "branch_name": "本店",
    "account_type": "普通",
    "account_number": "1234567",
    "account_holder_kana": "カタヅケ タロウ",
    "current_password": "password123",
}


# ──────────────────────────── プロフィール（後方互換） ────────────────────────────


class TestProfileBackwardCompat:
    async def test_put_profile_without_birth_date_occupation_still_succeeds(
        self, client: AsyncClient
    ):
        token = await _signup_user(client)
        r = await client.put(
            "/api/v1/users/me/profile", json=PROFILE_PAYLOAD_LEGACY, headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["birth_date"] is None
        assert data["occupation"] is None
        assert data["identity_status"] == "unverified"
        assert data["has_bank_account"] is False

    async def test_put_profile_with_birth_date_occupation(self, client: AsyncClient):
        token = await _signup_user(client)
        payload = {
            **PROFILE_PAYLOAD_LEGACY,
            "birth_date": "1990-05-01",
            "occupation": "会社員",
        }
        r = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["birth_date"] == "1990-05-01"
        assert data["occupation"] == "会社員"


# ──────────────────────────── 住所 ────────────────────────────


class TestAddress:
    async def test_get_address_initial_all_null(self, client: AsyncClient):
        token = await _signup_user(client)
        r = await client.get("/api/v1/users/me/address", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert data == {
            "postal_code": None,
            "prefecture": None,
            "city": None,
            "address_line1": None,
            "address_line2": None,
            "residence_area": None,
        }

    async def test_put_address_normalizes_postal_code_hyphen(self, client: AsyncClient):
        token = await _signup_user(client)
        r = await client.put(
            "/api/v1/users/me/address",
            json={
                "postal_code": "150-0001",
                "prefecture": "東京都",
                "city": "渋谷区",
                "address_line1": "神宮前1-1-1",
                "address_line2": None,
            },
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["postal_code"] == "1500001"
        assert data["residence_area"] == "tokyo"

    async def test_put_address_8digit_postal_code_422(self, client: AsyncClient):
        token = await _signup_user(client)
        r = await client.put(
            "/api/v1/users/me/address",
            json={
                "postal_code": "15000012",
                "prefecture": "東京都",
                "city": "渋谷区",
                "address_line1": "神宮前1-1-1",
            },
            headers=_auth(token),
        )
        assert r.status_code == 422

    async def test_put_address_invalid_prefecture_422(self, client: AsyncClient):
        token = await _signup_user(client)
        r = await client.put(
            "/api/v1/users/me/address",
            json={
                "postal_code": "1500001",
                "prefecture": "東京",  # 「都」抜けは無効
                "city": "渋谷区",
                "address_line1": "神宮前1-1-1",
            },
            headers=_auth(token),
        )
        assert r.status_code == 422

    async def test_residence_area_sync_hokkaido_maps_to_other(self, client: AsyncClient):
        token = await _signup_user(client)
        r = await client.put(
            "/api/v1/users/me/address",
            json={
                "postal_code": "0600000",
                "prefecture": "北海道",
                "city": "札幌市",
                "address_line1": "北1条西1丁目",
            },
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["residence_area"] == "other"

    async def test_put_address_preserves_address_line2(self, client: AsyncClient):
        """address_line2（建物名・部屋番号）が更新後も保持されることの回帰確認（QA L-3）。"""
        token = await _signup_user(client)
        r = await client.put(
            "/api/v1/users/me/address",
            json={
                "postal_code": "1500001",
                "prefecture": "東京都",
                "city": "渋谷区",
                "address_line1": "神宮前1-1-1",
                "address_line2": "カタヅケビル101号室",
            },
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["address_line2"] == "カタヅケビル101号室"

        r2 = await client.get("/api/v1/users/me/address", headers=_auth(token))
        assert r2.status_code == 200
        assert r2.json()["address_line2"] == "カタヅケビル101号室"


class TestProfileResidenceAreaSingleSource:
    """QA M-1: prefecture 登録済みユーザーは PUT /users/me/profile の
    residence_area を送っても無視され、prefecture 由来の値が維持されることを確認する。
    """

    async def test_profile_put_does_not_override_residence_area_once_prefecture_set(
        self, client: AsyncClient
    ):
        token = await _signup_user(client, email="pex_residence1@example.com")
        r = await client.put(
            "/api/v1/users/me/address",
            json={
                "postal_code": "1500001",
                "prefecture": "東京都",
                "city": "渋谷区",
                "address_line1": "神宮前1-1-1",
            },
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["residence_area"] == "tokyo"

        # 住所（東京都）登録済みの状態で、profile に矛盾する residence_area を送る。
        payload = {**PROFILE_PAYLOAD_LEGACY, "residence_area": "osaka"}
        r2 = await client.put("/api/v1/users/me/profile", json=payload, headers=_auth(token))
        assert r2.status_code == 200, r2.text
        assert r2.json()["residence_area"] == "tokyo"

    async def test_profile_put_uses_body_residence_area_when_no_address_registered(
        self, client: AsyncClient
    ):
        """住所未登録ユーザーは従来通り body の residence_area がそのまま反映される
        （後方互換）。"""
        token = await _signup_user(client, email="pex_residence2@example.com")
        r = await client.put(
            "/api/v1/users/me/profile", json=PROFILE_PAYLOAD_LEGACY, headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        assert r.json()["residence_area"] == "tokyo"


# ──────────────────────────── 振込先口座 ────────────────────────────


class TestBankAccount:
    async def test_get_bank_account_initial_not_registered(self, client: AsyncClient):
        token = await _signup_user(client)
        r = await client.get("/api/v1/users/me/bank-account", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert data["has_bank_account"] is False
        assert data["account_number_masked"] is None

    async def test_put_bank_account_db_column_has_no_plaintext(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await _signup_user(client, email="pex_bank1@example.com")
        r = await client.put(
            "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
        )
        assert r.status_code == 200, r.text

        raw = (
            await db_session.execute(
                text("SELECT bank_account_enc FROM users WHERE email=:email"),
                {"email": "pex_bank1@example.com"},
            )
        ).scalar_one()
        assert raw is not None
        assert "1234567" not in raw
        assert "カタヅケ タロウ" not in raw

    async def test_put_bank_account_response_masks_account_number(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank2@example.com")
        r = await client.put(
            "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        body_text = r.text
        assert "1234567" not in body_text
        data = r.json()
        assert data["has_bank_account"] is True
        assert data["account_number_masked"] == "***4567"
        assert data["account_holder_kana"] == "カタヅケ タロウ"

    async def test_get_bank_account_response_never_contains_plaintext_number(
        self, client: AsyncClient
    ):
        token = await _signup_user(client, email="pex_bank3@example.com")
        r = await client.put(
            "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        r2 = await client.get("/api/v1/users/me/bank-account", headers=_auth(token))
        assert r2.status_code == 200
        assert "1234567" not in r2.text

    async def test_put_bank_account_number_not_7digits_422(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank4@example.com")
        payload = {**VALID_BANK_PAYLOAD, "account_number": "12345"}
        r = await client.put(
            "/api/v1/users/me/bank-account", json=payload, headers=_auth(token)
        )
        assert r.status_code == 422

    async def test_put_bank_account_holder_hiragana_422(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank5@example.com")
        payload = {**VALID_BANK_PAYLOAD, "account_holder_kana": "かたづけ たろう"}
        r = await client.put(
            "/api/v1/users/me/bank-account", json=payload, headers=_auth(token)
        )
        assert r.status_code == 422

    async def test_delete_bank_account_then_has_bank_account_false(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank6@example.com")
        r = await client.put(
            "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
        )
        assert r.status_code == 200, r.text

        r2 = await client.request(
            "DELETE",
            "/api/v1/users/me/bank-account",
            json={"current_password": "password123"},
            headers=_auth(token),
        )
        assert r2.status_code == 204

        r3 = await client.get("/api/v1/users/me/bank-account", headers=_auth(token))
        assert r3.status_code == 200
        assert r3.json()["has_bank_account"] is False

    # ──────────── current_password 再認証（security review H-1） ────────────

    async def test_put_bank_account_missing_current_password_422(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank_reauth1@example.com")
        payload = dict(VALID_BANK_PAYLOAD)
        del payload["current_password"]
        r = await client.put(
            "/api/v1/users/me/bank-account", json=payload, headers=_auth(token)
        )
        assert r.status_code == 422, r.text

    async def test_put_bank_account_wrong_current_password_400(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank_reauth2@example.com")
        payload = {**VALID_BANK_PAYLOAD, "current_password": "wrongpassword"}
        r = await client.put(
            "/api/v1/users/me/bank-account", json=payload, headers=_auth(token)
        )
        assert r.status_code == 400, r.text

    async def test_delete_bank_account_missing_current_password_422(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank_reauth3@example.com")
        r = await client.put(
            "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
        )
        assert r.status_code == 200, r.text

        r2 = await client.request(
            "DELETE", "/api/v1/users/me/bank-account", json={}, headers=_auth(token)
        )
        assert r2.status_code == 422, r2.text

    async def test_delete_bank_account_wrong_current_password_400(self, client: AsyncClient):
        token = await _signup_user(client, email="pex_bank_reauth4@example.com")
        r = await client.put(
            "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
        )
        assert r.status_code == 200, r.text

        r2 = await client.request(
            "DELETE",
            "/api/v1/users/me/bank-account",
            json={"current_password": "wrongpassword"},
            headers=_auth(token),
        )
        assert r2.status_code == 400, r2.text

    async def test_bank_account_line_only_user_exempt_from_current_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """LINEログイン専用（password_hash=None）ユーザーは current_password なしで
        登録・削除できる。ただし直近10分以内に発行されたトークンに限る
        （step-up 認証。security review H-1 / 再レビュー A の docstring 参照）。"""
        user = User(
            email="pex_bank_line@example.com",
            password_hash=None,
            name="LINEユーザー",
            role="user",
            line_user_id="U" + "f" * 32,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        token = create_access_token(user.id, "user", user.role)

        payload = dict(VALID_BANK_PAYLOAD)
        del payload["current_password"]
        r = await client.put(
            "/api/v1/users/me/bank-account", json=payload, headers=_auth(token)
        )
        assert r.status_code == 200, r.text

        r2 = await client.request(
            "DELETE", "/api/v1/users/me/bank-account", json={}, headers=_auth(token)
        )
        assert r2.status_code == 204, r2.text

    async def test_bank_account_line_only_user_stale_token_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """LINE専用ユーザーでも、発行から10分を超えた（窃取されうる古い）トークンでは
        口座の登録・削除ができず 403（再ログイン要求）になる（再レビュー A 対応）。"""
        from datetime import datetime, timedelta, timezone

        user = User(
            email="pex_bank_line_stale@example.com",
            password_hash=None,
            name="LINEユーザー",
            role="user",
            line_user_id="U" + "e" * 32,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        stale = create_access_token(
            user.id, "user", user.role,
            issued_at=datetime.now(timezone.utc) - timedelta(minutes=11),
        )

        payload = dict(VALID_BANK_PAYLOAD)
        del payload["current_password"]
        r = await client.put("/api/v1/users/me/bank-account", json=payload, headers=_auth(stale))
        assert r.status_code == 403, r.text
        assert "再ログイン" in r.json()["detail"]

        r2 = await client.request(
            "DELETE", "/api/v1/users/me/bank-account", json={}, headers=_auth(stale)
        )
        assert r2.status_code == 403, r2.text

    async def test_bank_account_change_notifies_via_line_and_email(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """口座の登録・削除で dispatch_bank_account_changed が line_user_id と email の
        両方を伴って呼ばれる（LINE Push + メールの二経路通知。再レビュー A 対応）。"""
        from unittest.mock import AsyncMock, patch

        user = User(
            email="pex_bank_notify@example.com",
            password_hash=hash_password("Passw0rd!xyz"),
            name="通知ユーザー",
            role="user",
            line_user_id="U" + "d" * 32,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        token = create_access_token(user.id, "user", user.role)

        payload = dict(VALID_BANK_PAYLOAD)
        payload["current_password"] = "Passw0rd!xyz"
        with patch(
            "app.api.v1.endpoints.users.notify_dispatch.dispatch_bank_account_changed",
            new=AsyncMock(),
        ) as mock:
            r = await client.put("/api/v1/users/me/bank-account", json=payload, headers=_auth(token))
            assert r.status_code == 200, r.text
            r2 = await client.request(
                "DELETE",
                "/api/v1/users/me/bank-account",
                json={"current_password": "Passw0rd!xyz"},
                headers=_auth(token),
            )
            assert r2.status_code == 204, r2.text
        assert mock.await_count == 2
        first_args = mock.await_args_list[0].args
        assert first_args[0] == user.line_user_id
        assert first_args[1] == user.email
        assert first_args[2] == "登録"
        assert mock.await_args_list[1].args[2] == "削除"

    async def test_bank_account_update_rate_limited_returns_429(self, db_session: AsyncSession):
        """scope=bank_account_update の user_id 軸レート制限が上限超過で429を返すことを確認する。

        ``conftest.py`` の既定 ``RATE_LIMIT_ENABLED=false`` に依存せず、
        test_case_cancel.py と同じパターンでテスト専用の有効な RateLimiter を注入する。
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
            token = await _signup_user(client, email="pex_bank_rl@example.com")

            r1 = await client.put(
                "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
            )
            assert r1.status_code == 200, r1.text

            r2 = await client.put(
                "/api/v1/users/me/bank-account", json=VALID_BANK_PAYLOAD, headers=_auth(token)
            )
            assert r2.status_code == 429
            assert "Retry-After" in r2.headers
