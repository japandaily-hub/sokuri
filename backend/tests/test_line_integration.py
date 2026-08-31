"""LINEログイン統合 / LINE Push通知の統合・単体テスト。

- line_notify._push: トークン未設定スキップ / 成功 / 失敗の3ケース（httpxモック）
- notify_dispatch: LINE優先・メールフォールバックの分岐
- /auth/line/exchange: 新規作成・既存ログイン・連携（Bearer有）・重複409・
  業者テーブルへの新規作成が発生しないこと・channel audience 検証・userId書式検証・
  User/Operator相互重複チェック
- select_bid: 落選業者へのdispatch呼び出しが正しい件数呼ばれること（当選者には呼ばれないこと）

LINE Verify API (`GET /oauth2/v2.1/verify`) は Critical 対応（audience検証）で
`_fetch_line_user_id` から必ず呼ばれるようになったため、Profile API と併せて
`_mock_line_get` でエンドポイント URL に応じて出し分けてモックする。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import jwt as pyjwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.api.v1.endpoints import auth as auth_endpoint
from app.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.services import line_notify, notify, notify_dispatch

_TEST_LINE_CLIENT_ID = "test-line-channel-id"


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
        email="admin_line@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_line@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str = "line_user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201
    return r.json()["access_token"]


async def _reauth_token(
    client: AsyncClient, user_token: str, password: str = "password123"
) -> str:
    """パスワード設定済みユーザーがLINE連携（新規付与）に必要な再認証トークンを発行する。"""
    r = await client.post(
        "/api/v1/users/me/reauth-token",
        json={"current_password": password},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text
    return r.json()["reauth_token"]


async def _operator_reauth_token(
    client: AsyncClient, op_token: str, password: str = "operatorpass1"
) -> str:
    """業者がLINE連携（新規付与）に必要な再認証トークンを発行する（user側と対称。
    security review H-1対応）。"""
    r = await client.post(
        "/api/v1/operator/reauth-token",
        json={"current_password": password},
        headers=_auth(op_token),
    )
    assert r.status_code == 200, r.text
    return r.json()["reauth_token"]


async def _invite_code(client: AsyncClient, admin_token: str) -> str:
    r = await client.post(
        "/api/v1/admin/invites", json={}, headers=_auth(admin_token)
    )
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
    assert r.status_code == 201
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
        "photos": [],
    }


async def _create_case(client: AsyncClient, user_token: str) -> dict:
    r = await client.post(
        "/api/v1/cases", json=_case_payload(), headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


def _mock_line_profile_response(user_id: str) -> httpx.Response:
    return httpx.Response(200, json={"userId": user_id, "displayName": "テストユーザー"})


def _mock_line_verify_response(
    client_id: str = _TEST_LINE_CLIENT_ID, expires_in: int = 3600
) -> httpx.Response:
    return httpx.Response(
        200, json={"client_id": client_id, "expires_in": expires_in, "scope": "profile"}
    )


def _mock_line_get(
    user_id: str = "Uc682572a6a72e6504e76b92ae3c05732",
    *,
    verify_response: httpx.Response | None = None,
    profile_response: httpx.Response | None = None,
) -> AsyncMock:
    """`_LINE_VERIFY_ENDPOINT` / `_LINE_PROFILE_ENDPOINT` を URL で出し分けるモック。"""
    verify_res = verify_response or _mock_line_verify_response()
    profile_res = profile_response or _mock_line_profile_response(user_id)

    async def _side_effect(url, *args, **kwargs):
        if url == auth_endpoint._LINE_VERIFY_ENDPOINT:
            return verify_res
        if url == auth_endpoint._LINE_PROFILE_ENDPOINT:
            return profile_res
        raise AssertionError(f"未想定のURLへのリクエスト: {url}")

    return AsyncMock(side_effect=_side_effect)


@pytest.fixture(autouse=True)
def _line_client_id_configured(monkeypatch):
    """全テスト共通で LINE_CLIENT_ID を設定済み状態にする
    （未設定時の挙動は TestLineChannelNotConfigured で個別に検証する）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "line_client_id", _TEST_LINE_CLIENT_ID)


# ──────────────────────────── line_notify._push ────────────────────────────


class TestLineNotifyPush:
    async def test_push_skips_when_token_unset(self):
        """LINE_CHANNEL_ACCESS_TOKEN 未設定時は送信せず False を返す。"""
        settings = get_settings()
        assert settings.line_channel_access_token == ""
        with patch.object(httpx.AsyncClient, "post", new=AsyncMock()) as mock_post:
            result = await line_notify._push("U1234567890", "test message")
        assert result is False
        mock_post.assert_not_called()

    async def test_push_success(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "line_channel_access_token", "dummy-token")
        mock_response = httpx.Response(
            200,
            json={},
            request=httpx.Request("POST", line_notify._LINE_PUSH_ENDPOINT),
        )
        with patch.object(
            httpx.AsyncClient, "post", new=AsyncMock(return_value=mock_response)
        ) as mock_post:
            result = await line_notify._push("U1234567890", "test message")
        assert result is True
        mock_post.assert_called_once()

    async def test_push_failure_returns_false(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "line_channel_access_token", "dummy-token")
        with patch.object(
            httpx.AsyncClient,
            "post",
            new=AsyncMock(side_effect=httpx.ConnectTimeout("timeout")),
        ):
            result = await line_notify._push("U1234567890", "test message")
        assert result is False


# ──────────────────────────── notify_dispatch ────────────────────────────


class TestNotifyDispatch:
    async def test_dispatch_bid_selected_prefers_line_when_available(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_selected", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_selected", email_mock)

        await notify_dispatch.dispatch_bid_selected("U123", "op@example.com", "txn1", 10000)

        push_mock.assert_called_once_with("U123", "txn1", 10000)
        email_mock.assert_not_called()

    async def test_dispatch_bid_selected_falls_back_to_email_when_no_line(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_selected", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_selected", email_mock)

        await notify_dispatch.dispatch_bid_selected(None, "op@example.com", "txn1", 10000)

        push_mock.assert_not_called()
        email_mock.assert_called_once_with("op@example.com", "txn1", 10000)

    async def test_dispatch_bid_selected_falls_back_to_email_when_line_fails(self, monkeypatch):
        push_mock = AsyncMock(return_value=False)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_selected", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_selected", email_mock)

        await notify_dispatch.dispatch_bid_selected("U123", "op@example.com", "txn1", 10000)

        push_mock.assert_called_once()
        email_mock.assert_called_once_with("op@example.com", "txn1", 10000)

    async def test_dispatch_bid_lost_prefers_line(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_lost", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_lost", email_mock)

        await notify_dispatch.dispatch_bid_lost("U123", "op@example.com", "case1")

        push_mock.assert_called_once_with("U123", "case1")
        email_mock.assert_not_called()

    async def test_dispatch_bid_lost_falls_back_to_email(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_lost", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_lost", email_mock)

        await notify_dispatch.dispatch_bid_lost(None, "op@example.com", "case1")

        push_mock.assert_not_called()
        email_mock.assert_called_once_with("op@example.com", "case1")

    async def test_dispatch_schedule_confirmed_prefers_line(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_schedule_confirmed", push_mock)
        monkeypatch.setattr("app.services.notify.send_schedule_confirmed", email_mock)

        await notify_dispatch.dispatch_schedule_confirmed(
            "U123", "op@example.com", "txn1", "2026-08-01"
        )

        push_mock.assert_called_once_with("U123", "txn1", "2026-08-01")
        email_mock.assert_not_called()


# ──────────────────────────── /auth/line/exchange ────────────────────────────


class TestLineExchange:
    async def test_new_user_created_when_no_existing_line_link(self, client: AsyncClient, db_session: AsyncSession):
        line_user_id = "U2dce194fdcc4602dd6b5ab2b7d05b975"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["account_type"] == "user"
        assert body["user"]["email"] == f"line-{line_user_id}@line.katazuke.internal"

        user = await db_session.scalar(select(User).where(User.line_user_id == line_user_id))
        assert user is not None
        assert user.password_hash is None

        # 業者テーブルには一切作成されない。
        any_operator = await db_session.scalar(select(Operator).limit(1))
        assert any_operator is None

    async def test_existing_line_user_logs_in(self, client: AsyncClient, db_session: AsyncSession):
        line_user_id = "Ufb142e6145592de63fcdbd015c32670d"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r1.status_code == 200
        user_id_1 = r1.json()["user"]["id"]

        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r2.status_code == 200
        assert r2.json()["user"]["id"] == user_id_1

        # 新規Userが2件作られていないことを確認。
        count = len(
            (
                await db_session.scalars(
                    select(User).where(User.line_user_id == line_user_id)
                )
            ).all()
        )
        assert count == 1

    async def test_link_existing_jwt_user_with_bearer(self, client: AsyncClient, db_session: AsyncSession):
        user_token = await _signup_user(client, "link_user@example.com")
        reauth_token = await _reauth_token(client, user_token)
        line_user_id = "Uddfe30ff6ab11fe08f372c0ad0a16285"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": reauth_token},
                headers=_auth(user_token),
            )
        assert r.status_code == 200, r.text
        assert r.json()["user"]["email"] == "link_user@example.com"

        user = await db_session.scalar(select(User).where(User.email == "link_user@example.com"))
        assert user.line_user_id == line_user_id

    async def test_link_conflict_returns_409(self, client: AsyncClient, db_session: AsyncSession):
        line_user_id = "U9ff16bc766ab84d3ca704320ae983f0f"

        # user1 が先に連携。
        user1_token = await _signup_user(client, "conflict_user1@example.com")
        reauth1 = await _reauth_token(client, user1_token)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": reauth1},
                headers=_auth(user1_token),
            )
        assert r1.status_code == 200

        # user2 が同じ line_user_id を連携しようとすると409。
        user2_token = await _signup_user(client, "conflict_user2@example.com")
        reauth2 = await _reauth_token(client, user2_token)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": reauth2},
                headers=_auth(user2_token),
            )
        assert r2.status_code == 409

    async def test_line_profile_api_failure_returns_502(self, client: AsyncClient):
        with patch.object(
            httpx.AsyncClient,
            "get",
            new=AsyncMock(side_effect=httpx.ConnectTimeout("timeout")),
        ):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 502

    async def test_line_profile_api_error_status_returns_502(self, client: AsyncClient):
        mock_response = httpx.Response(401, json={"error": "invalid_token"})
        with patch.object(
            httpx.AsyncClient,
            "get",
            new=_mock_line_get(profile_response=mock_response),
        ):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 502

    async def test_line_only_user_cannot_password_login(self, client: AsyncClient):
        """password_hash が None の LINE専用ユーザーはパスワードログインで401。"""
        line_user_id = "Ubea37442e8d539d05f802f5c5b7f0983"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 200
        email = r.json()["user"]["email"]

        r2 = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "anything12345"}
        )
        assert r2.status_code == 401


# ──────────────────────────── audience検証 / userId書式検証（Critical対応） ────────────────────────────


class TestLineAudienceVerification:
    async def test_verify_client_id_mismatch_returns_401(self, client: AsyncClient):
        """Verify APIのclient_idが自社チャネルIDと不一致なら401（クロスチャネルなりすまし対策）。"""
        mismatched = _mock_line_verify_response(client_id="attacker-other-channel-id")
        with patch.object(
            httpx.AsyncClient, "get", new=_mock_line_get(verify_response=mismatched)
        ):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 401

    async def test_verify_expires_in_zero_returns_401(self, client: AsyncClient):
        """expires_in <= 0（期限切れ相当）なら401。"""
        expired = _mock_line_verify_response(expires_in=0)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(verify_response=expired)):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 401

    async def test_verify_api_error_status_returns_401(self, client: AsyncClient):
        """Verify API自体がエラー（無効トークン等、通常400）を返した場合は401。"""
        error_res = httpx.Response(400, json={"error": "invalid_request"})
        with patch.object(
            httpx.AsyncClient, "get", new=_mock_line_get(verify_response=error_res)
        ):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 401

    async def test_line_client_id_not_configured_returns_503(self, client: AsyncClient, monkeypatch):
        """LINE_CLIENT_ID未設定時はVerify APIを呼ぶ前に503で拒否する。"""
        settings = get_settings()
        monkeypatch.setattr(settings, "line_client_id", "")
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock()) as mock_get:
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 503
        mock_get.assert_not_called()

    async def test_invalid_user_id_format_returns_401(self, client: AsyncClient):
        """Profile APIが返すuserIdがLINEの書式（U+32桁16進）に合致しない場合は401。"""
        bad_profile = httpx.Response(
            200, json={"userId": "not-a-valid-line-user-id", "displayName": "x"}
        )
        with patch.object(
            httpx.AsyncClient, "get", new=_mock_line_get(profile_response=bad_profile)
        ):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 401


# ──────────────────────────── User/Operator 相互重複チェック（Medium-2対応） ────────────────────────────


class TestLineCrossAccountConflict:
    async def test_user_line_id_blocks_operator_link(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Userで使用中のline_user_idをOperator連携で使おうとすると409。"""
        admin_token = await _make_admin(client, db_session)
        line_user_id = "U126531011c10141b4046d04eb29de9a2"

        user_token = await _signup_user(client, "cross_user@example.com")
        reauth_token = await _reauth_token(client, user_token)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": reauth_token},
                headers=_auth(user_token),
            )
        assert r1.status_code == 200

        op_token, _ = await _verified_operator(client, admin_token, "cross_operator@example.com")
        op_reauth_token = await _operator_reauth_token(client, op_token)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": op_reauth_token},
                headers=_auth(op_token),
            )
        assert r2.status_code == 409

    async def test_operator_line_id_blocks_user_link(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Operatorで使用中のline_user_idをUser連携で使おうとすると409（逆方向）。"""
        admin_token = await _make_admin(client, db_session)
        line_user_id = "U20d045d0d8212c84bbdb1e97bfeb5d8e"

        op_token, _ = await _verified_operator(client, admin_token, "cross_operator2@example.com")
        op_reauth_token = await _operator_reauth_token(client, op_token)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": op_reauth_token},
                headers=_auth(op_token),
            )
        assert r1.status_code == 200

        user_token = await _signup_user(client, "cross_user2@example.com")
        reauth_token = await _reauth_token(client, user_token)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": reauth_token},
                headers=_auth(user_token),
            )
        assert r2.status_code == 409

    async def test_operator_line_id_blocks_new_user_creation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Operatorで使用中のline_user_idは、Bearer無し（新規User作成）フローでも409。"""
        admin_token = await _make_admin(client, db_session)
        line_user_id = "U42e4a3913296a1197bbedab6b15c60e9"

        op_token, _ = await _verified_operator(client, admin_token, "cross_operator3@example.com")
        op_reauth_token = await _operator_reauth_token(client, op_token)
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": op_reauth_token},
                headers=_auth(op_token),
            )
        assert r1.status_code == 200

        # Bearerなしで同じ line_user_id が新規User作成を試みる。
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r2.status_code == 409


# ──────────────────────────── select_bid の落選通知dispatch ────────────────────────────


class TestSelectBidDispatch:
    async def test_dispatch_called_for_losers_not_winner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "select_bid_user@example.com")
        op1_token, op1_id = await _verified_operator(
            client, admin_token, "select_bid_op1@example.com", "A社"
        )
        op2_token, op2_id = await _verified_operator(
            client, admin_token, "select_bid_op2@example.com", "B社"
        )
        op3_token, op3_id = await _verified_operator(
            client, admin_token, "select_bid_op3@example.com", "C社"
        )
        case = await _create_case(client, user_token)

        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids", json={"amount": 10000}, headers=_auth(op1_token)
        )
        bid1 = r.json()
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids", json={"amount": 20000}, headers=_auth(op2_token)
        )
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids", json={"amount": 30000}, headers=_auth(op3_token)
        )

        selected_calls = []
        lost_calls = []

        async def _fake_selected(line_user_id, email, transaction_id, amount):
            selected_calls.append((line_user_id, email, transaction_id, amount))

        async def _fake_lost(line_user_id, email, case_id):
            lost_calls.append((line_user_id, email, case_id))

        with patch(
            "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_selected",
            new=_fake_selected,
        ), patch(
            "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_lost",
            new=_fake_lost,
        ):
            r = await client.post(
                f"/api/v1/cases/{case['id']}/bids/{bid1['id']}/select",
                headers=_auth(user_token),
            )
        assert r.status_code == 201, r.text

        assert len(selected_calls) == 1
        assert selected_calls[0][1] == "select_bid_op1@example.com"

        assert len(lost_calls) == 2
        lost_emails = {c[1] for c in lost_calls}
        assert lost_emails == {"select_bid_op2@example.com", "select_bid_op3@example.com"}


# ──────────────────────────── 仮メール（LINE専用ユーザー）の送信経路混入防止（Medium-1対応） ────────────────────────────


class TestPlaceholderEmailNotLeaked:
    async def test_is_placeholder_email_helper(self):
        assert notify.is_placeholder_email("line-Uabc@line.katazuke.internal") is True
        assert notify.is_placeholder_email("real_user@example.com") is False
        assert notify.is_placeholder_email(None) is False
        assert notify.is_placeholder_email("") is False
        # サフィックス一致の大小文字ゆらぎにも対応。
        assert notify.is_placeholder_email("line-Uabc@LINE.KATAZUKE.INTERNAL") is True

    async def test_bid_received_notification_skipped_for_line_only_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """案件所有者がLINE専用ユーザー（仮メール）の場合、入札通知メールは送信しない。"""
        admin_token = await _make_admin(client, db_session)
        line_user_id = "U290490d51e46a6b89d6f562abebf6028"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 200
        line_user_token = r.json()["access_token"]

        op_token, _ = await _verified_operator(
            client, admin_token, "placeholder_test_op@example.com"
        )
        case = await _create_case(client, line_user_token)

        with patch(
            "app.api.v1.endpoints.bids.notify.send_bid_received", new=AsyncMock()
        ) as send_mock:
            r = await client.post(
                f"/api/v1/cases/{case['id']}/bids",
                json={"amount": 15000},
                headers=_auth(op_token),
            )
        assert r.status_code == 201, r.text
        send_mock.assert_not_called()

    async def test_case_created_notification_skipped_for_line_only_user(
        self, client: AsyncClient
    ):
        """案件登録完了メールもLINE専用ユーザー（仮メール）宛には送信しない。"""
        line_user_id = "U7114a0aef5d01adcd7a5d83c00c8e54e"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 200
        line_user_token = r.json()["access_token"]

        with patch(
            "app.api.v1.endpoints.cases.notify.send_case_created", new=AsyncMock()
        ) as send_mock:
            await _create_case(client, line_user_token)
        send_mock.assert_not_called()

    async def test_operator_sees_line_contact_notice_instead_of_placeholder_email(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """成約詳細で業者に開示される contact_email が、仮メールなら案内文言に置き換わる。"""
        admin_token = await _make_admin(client, db_session)
        line_user_id = "U871ae97fa0ac5cdea646eaeaef41fe0f"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
            )
        assert r.status_code == 200
        line_user_token = r.json()["access_token"]

        op_token, _ = await _verified_operator(
            client, admin_token, "placeholder_test_op2@example.com"
        )
        case = await _create_case(client, line_user_token)
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids",
            json={"amount": 12000},
            headers=_auth(op_token),
        )
        assert r.status_code == 201, r.text
        bid = r.json()

        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
            headers=_auth(line_user_token),
        )
        assert r.status_code == 201, r.text
        txn_id = r.json()["id"]

        r = await client.get(
            f"/api/v1/transactions/{txn_id}", headers=_auth(op_token)
        )
        assert r.status_code == 200, r.text
        assert r.json()["contact_email"] == "LINEにて連絡"


# ──────────────────────────── reauth_token必須化 / 再バインド拒否 / 失効ゲート（security review対応） ────────────────────────────


class TestLineExchangeReauthAndRebind:
    async def _reauth_token(
        self, client: AsyncClient, user_token: str, password: str = "password123"
    ) -> str:
        r = await client.post(
            "/api/v1/users/me/reauth-token",
            json={"current_password": password},
            headers=_auth(user_token),
        )
        assert r.status_code == 200, r.text
        return r.json()["reauth_token"]

    async def test_link_without_reauth_token_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """パスワード設定済みユーザーがreauth_tokenを付けずに初回連携を試みると401。"""
        user_token = await _signup_user(client, "reauth_missing@example.com")
        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f001"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(user_token),
            )
        assert r.status_code == 401

    async def test_other_users_reauth_token_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """他ユーザーが発行したreauth_tokenは sub 不一致で401拒否される。"""
        user_token = await _signup_user(client, "reauth_owner@example.com")
        other_token = await _signup_user(client, "reauth_other@example.com")
        other_reauth = await self._reauth_token(client, other_token)

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f002"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    "reauth_token": other_reauth,
                },
                headers=_auth(user_token),
            )
        assert r.status_code == 401

    async def test_expired_reauth_token_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_token = await _signup_user(client, "reauth_expired@example.com")
        user = await db_session.scalar(
            select(User).where(User.email == "reauth_expired@example.com")
        )
        settings = get_settings()
        expired_payload = {
            "sub": str(user.id),
            "purpose": "line_link",
            "iat": datetime.now(timezone.utc) - timedelta(minutes=10),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
        expired_token = pyjwt.encode(expired_payload, settings.jwt_secret, algorithm="HS256")

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f003"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    "reauth_token": expired_token,
                },
                headers=_auth(user_token),
            )
        assert r.status_code == 401

    async def test_wrong_purpose_token_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """通常のaccess_token（purposeクレーム無し）はreauth_tokenとして使えない。"""
        user_token = await _signup_user(client, "reauth_wrong_purpose@example.com")

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f004"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    # 通常のaccess_token自身をreauth_tokenとして流用しようとする攻撃を想定。
                    "reauth_token": user_token,
                },
                headers=_auth(user_token),
            )
        assert r.status_code == 401

    async def test_line_only_user_link_skips_reauth_requirement(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """LINE専用アカウント（password_hash=None）は再認証手段が無いためreauth_token無しで連携できる。"""
        user = User(
            email="line_only_link@line.katazuke.internal",
            password_hash=None,
            name=None,
            role="user",
            line_user_id=None,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        token = create_access_token(user.id, "user", user.role)

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f005"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(token),
            )
        assert r.status_code == 200, r.text

    async def test_rebind_to_different_line_account_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """既に別のLINEアカウントに連携済みのユーザーは無条件で再バインド不可（最重要指摘）。"""
        user_token = await _signup_user(client, "rebind_user@example.com")
        reauth1 = await self._reauth_token(client, user_token)
        line_user_id_1 = "Ue9d1e6c1c4e94e848bdafba7c2f0f006"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id_1)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    "reauth_token": reauth1,
                },
                headers=_auth(user_token),
            )
        assert r1.status_code == 200

        # reauth_token を付けても、別LINEアカウントへの再バインドは常に拒否する。
        reauth2 = await self._reauth_token(client, user_token)
        line_user_id_2 = "Ue9d1e6c1c4e94e848bdafba7c2f0f007"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id_2)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    "reauth_token": reauth2,
                },
                headers=_auth(user_token),
            )
        assert r2.status_code == 409

    async def test_resend_same_line_user_id_is_idempotent(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """既に連携済みと同一のline_user_idの再送は、reauth_token無しでも成功する（冪等）。"""
        user_token = await _signup_user(client, "idempotent_user@example.com")
        reauth1 = await self._reauth_token(client, user_token)
        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f008"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    "reauth_token": reauth1,
                },
                headers=_auth(user_token),
            )
        assert r1.status_code == 200

        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(user_token),
            )
        assert r2.status_code == 200

        count = len(
            (
                await db_session.scalars(
                    select(User).where(User.line_user_id == line_user_id)
                )
            ).all()
        )
        assert count == 1

    async def test_deleted_account_jwt_rejected_on_line_exchange(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """退会（論理削除）済みの旧JWTは、line_exchangeのBearer経路でも401で失効する。"""
        user_token = await _signup_user(client, "deleted_gate@example.com")
        user = await db_session.scalar(
            select(User).where(User.email == "deleted_gate@example.com")
        )
        user.deleted_at = datetime.now(timezone.utc)
        await db_session.commit()

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f009"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(user_token),
            )
        assert r.status_code == 401

    async def test_password_changed_jwt_rejected_on_line_exchange(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """パスワード変更後の旧JWTは、line_exchangeのBearer経路でも401で失効する（iatゲート）。"""
        user_token = await _signup_user(client, "pwchanged_gate@example.com")
        await asyncio.sleep(1.1)
        r = await client.put(
            "/api/v1/users/me/password",
            json={"current_password": "password123", "new_password": "newpassword1"},
            headers=_auth(user_token),
        )
        assert r.status_code == 200, r.text

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f010"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(user_token),
            )
        assert r2.status_code == 401

    async def test_suspended_operator_jwt_rejected_on_line_exchange(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """停止中（is_suspended）業者の旧JWTは、line_exchangeのBearer経路でも403で失効する。"""
        admin_token = await _make_admin(client, db_session)
        op_token, op_id = await _verified_operator(
            client, admin_token, "suspended_op@example.com"
        )
        operator = await db_session.get(Operator, uuid.UUID(op_id))
        operator.is_suspended = True
        await db_session.commit()

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f011"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(op_token),
            )
        assert r.status_code == 403

    async def test_operator_rebind_to_different_line_account_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """業者側も再バインド不可（user分岐と同様のガード）。"""
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(client, admin_token, "rebind_op@example.com")
        op_reauth_token_1 = await _operator_reauth_token(client, op_token)

        line_user_id_1 = "Ue9d1e6c1c4e94e848bdafba7c2f0f012"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id_1)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": op_reauth_token_1},
                headers=_auth(op_token),
            )
        assert r1.status_code == 200

        # reauth_token を付けても、別LINEアカウントへの再バインドは常に拒否する
        # （既に line_user_id_1 に連携済みのため、ここは再認証チェックより前段の
        # 「再バインド禁止」ガードで拒否される。reauth_token の有無は結果に影響しない）。
        op_reauth_token_2 = await _operator_reauth_token(client, op_token)
        line_user_id_2 = "Ue9d1e6c1c4e94e848bdafba7c2f0f013"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id_2)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": op_reauth_token_2},
                headers=_auth(op_token),
            )
        assert r2.status_code == 409

    async def test_operator_link_without_reauth_token_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """業者（password_hash設定済み）がreauth_tokenを付けずに初回連携を試みると401
        （security review H-1対応。従来はoperator分岐に再認証要求が一切無かった）。"""
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(
            client, admin_token, "op_reauth_missing@example.com"
        )
        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f014"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(op_token),
            )
        assert r.status_code == 401

    async def test_operator_resend_same_line_user_id_is_idempotent_without_reauth(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """業者側も、既に連携済みと同一line_user_idの再送はreauth_token無しで成功する（冪等）。"""
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(
            client, admin_token, "op_idempotent@example.com"
        )
        op_reauth_token = await _operator_reauth_token(client, op_token)
        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f015"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r1 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token", "reauth_token": op_reauth_token},
                headers=_auth(op_token),
            )
        assert r1.status_code == 200

        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(op_token),
            )
        assert r2.status_code == 200

    async def test_user_reauth_token_rejected_for_operator_exchange(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """user向けに発行されたreauth_token（typ="user"）は、operator側のline_exchangeに
        使い回せない（typ不一致で401。security review H-1対応の構造的分離）。"""
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(
            client, admin_token, "op_typ_reject@example.com"
        )
        user_token = await _signup_user(client, "typ_reject_user@example.com")
        user_reauth_token = await self._reauth_token(client, user_token)

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f016"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    "reauth_token": user_reauth_token,
                },
                headers=_auth(op_token),
            )
        assert r.status_code == 401

    async def test_operator_reauth_token_rejected_for_user_exchange(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """operator向けに発行されたreauth_token（typ="operator"）は、user側のline_exchangeに
        使い回せない（typ不一致で401。逆方向）。"""
        admin_token = await _make_admin(client, db_session)
        op_token, _ = await _verified_operator(
            client, admin_token, "op_typ_reject2@example.com"
        )
        op_reauth_token = await _operator_reauth_token(client, op_token)
        user_token = await _signup_user(client, "typ_reject_user2@example.com")

        line_user_id = "Ue9d1e6c1c4e94e848bdafba7c2f0f017"
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={
                    "line_access_token": "dummy-line-token",
                    "reauth_token": op_reauth_token,
                },
                headers=_auth(user_token),
            )
        assert r.status_code == 401

    async def test_reauth_token_rejected_as_bearer_on_protected_endpoint(
        self, client: AsyncClient
    ):
        """reauth_token（purposeクレーム付きの用途限定トークン）は、通常の
        Authorization: Bearer として保護エンドポイントを通過できてはならない
        （security review Medium指摘対応: deps._decode / line_exchangeのBearer
        抽出の両方でpurposeクレームを検証していないと、発行から5分間、通常の
        セッショントークンとして機能してしまう）。"""
        token = await self._reauth_token(client, await _signup_user(client, "reauth_as_bearer@example.com"))

        # deps.get_current_user経由の保護エンドポイントで拒否されること。
        r = await client.get("/api/v1/users/me/profile", headers=_auth(token))
        assert r.status_code == 401

        # line_exchangeのBearer抽出経路でも同様に拒否されること
        # （Authorization: Bearerとしてreauth_tokenそのものを渡すケース）。
        with patch.object(
            httpx.AsyncClient, "get", new=_mock_line_get("Uaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa9")
        ):
            r2 = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_auth(token),
            )
        assert r2.status_code == 401


# ──────────────────────────── signupでのLINE専用プレースホルダemail拒否（費用対効果の高い追加修正） ────────────────────────────


class TestSignupRejectsPlaceholderEmail:
    async def test_user_signup_rejects_line_placeholder_email_422(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "line-Uabc123@line.katazuke.internal",
                "password": "password123",
                "name": "テスト",
            },
        )
        assert r.status_code == 422

    async def test_user_signup_rejects_deleted_placeholder_email_422(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "deleted-abc123@deleted.katazuke.internal",
                "password": "password123",
                "name": "テスト",
            },
        )
        assert r.status_code == 422

    async def test_operator_signup_rejects_line_placeholder_email_422(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session)
        code = await _invite_code(client, admin_token)
        r = await client.post(
            "/api/v1/auth/operator/signup",
            json={
                "invite_code": code,
                "company_name": "テスト会社",
                "email": "line-Uxyz789@line.katazuke.internal",
                "password": "operatorpass1",
                "license_number": "第123456789012号",
                "agreed": True,
            },
        )
        assert r.status_code == 422
