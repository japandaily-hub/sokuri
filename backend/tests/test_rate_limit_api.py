"""認証系レート制限の統合テスト（HTTP 経由・``dependency_overrides`` で有効化）。

``test_account_api.py`` / ``test_line_integration.py`` の ``create_test_app``
パターンを踏襲し、加えて ``app.dependency_overrides[get_rate_limiter]`` で
テスト専用の隔離インスタンス（``FakeClock`` 注入済み）に差し替える
ローカルフィクスチャを定義する（設計書 §6-(b)）。

このフィクスチャ差し替えにより、``backend/tests/conftest.py`` が設定する
``RATE_LIMIT_ENABLED=false``（グローバルシングルトン常時無効化）には
一切依存しない。差し替え自体をしないテスト（TC-37）で、その既定無効化が
実際に効いていることも別途検証する。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import (
    _IPV6_48_LIMIT_MULTIPLIER,
    _IPV6_56_LIMIT_MULTIPLIER,
    get_rate_limiter,
)
from app.api.v1.endpoints import auth as auth_endpoint
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
)
from app.core.security import create_access_token, hash_password
from app.db.models.operator import Operator
from app.db.models.operator_application import OperatorApplication
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from tests.test_katadzuke_api import _application_payload
from tests.test_rate_limit import FakeClock

_TEST_LINE_CLIENT_ID = "test-line-channel-id-rl"

_LOGIN_MSG = "ログインの試行回数が上限に達しました。しばらく時間をおいて再度お試しください。"
_PASSWORD_MSG = "パスワード変更の試行回数が上限に達しました。しばらく時間をおいて再度お試しください。"
_DELETE_MSG = "試行回数が上限に達しました。しばらく時間をおいて再度お試しください。"
_SIGNUP_MSG = "登録試行が集中しています。しばらく時間をおいて再度お試しください。"
_LINE_MSG = "リクエストが集中しています。しばらく時間をおいて再度お試しください。"
_CASE_CREATE_MSG = "案件の作成が集中しています。しばらく時間をおいて再度お試しください。"


def _config(
    *,
    enabled: bool = True,
    login_account_max: int = 5,
    login_ip_max: int = 20,
    login_window: int = 900,
    sensitive_max: int = 5,
    sensitive_window: int = 900,
    signup_max: int = 10,
    signup_window: int = 3600,
    line_max: int = 20,
    line_window: int = 900,
    case_create_ip_max: int = 10,
    case_create_account_max: int = 10,
    case_create_window: int = 3600,
) -> RateLimitConfig:
    return RateLimitConfig(
        enabled=enabled,
        login_account=RateLimitRule(login_account_max, login_window),
        login_ip=RateLimitRule(login_ip_max, login_window),
        sensitive_account=RateLimitRule(sensitive_max, sensitive_window),
        signup_ip=RateLimitRule(signup_max, signup_window),
        line_ip=RateLimitRule(line_max, line_window),
        max_keys=10000,
        case_create_ip=RateLimitRule(case_create_ip_max, case_create_window),
        case_create_account=RateLimitRule(case_create_account_max, case_create_window),
    )


def create_test_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    return app


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_TEST_PUBLIC_IP_HEADERS = {"X-Forwarded-For": "198.51.100.200"}


async def _signup_user(
    client: AsyncClient,
    email: str,
    password: str = "password123",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """signup を叩く。

    既定で ``X-Forwarded-For`` に実在しない公開IP（RFC5737 レンジ）を
    付与する。ASGITransport 経由のテストでは ``request.client.host`` が
    ``"127.0.0.1"``（真正のループバック）になるため、XFF 無指定だと
    security review 指摘C（信頼位置がプライベート/ループバックなら
    IP軸をスキップする）により IP 軸が常にスキップされ、signup の
    IP 軸カウントを検証できない（本番では Render の LB が必ず XFF を
    付与するため、この既定値の方が実態に近い）。
    """
    return await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "name": "テスト太郎"},
        headers=headers if headers is not None else _TEST_PUBLIC_IP_HEADERS,
    )


async def _create_user(
    db_session: AsyncSession, email: str, password: str = "password123"
) -> User:
    """DB へ直接ユーザーを作成する（``/auth/signup`` を経由しない）。

    login/password/delete 系のテストは signup の IP 軸レート制限（10/時間）とは
    無関係の関心事のため、signup 自体のレート制限バジェットを消費しないよう
    DB へ直接作成する。
    """
    user = User(email=email, password_hash=hash_password(password), name="テスト太郎", role="user")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _user_token(user: User) -> str:
    return create_access_token(user.id, "user", user.role)


def _operator_token(operator: Operator) -> str:
    return create_access_token(operator.id, "operator", "operator")


async def _create_operator(
    db_session: AsyncSession, email: str, password: str = "operatorpass1"
) -> Operator:
    """DB へ直接業者アカウントを作成する（``/auth/operator/signup`` を経由しない）。"""
    operator = Operator(
        company_name="テスト片付け株式会社",
        contact_email=email,
        license_number="第123456789012号",
        password_hash=hash_password(password),
        vendor_status="pending",
    )
    db_session.add(operator)
    await db_session.commit()
    await db_session.refresh(operator)
    return operator


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(db_session: AsyncSession, fake_clock: FakeClock) -> AsyncIterator[AsyncClient]:
    """レート制限を有効化したテスト専用インスタンス（既定の本番相当ルール）を注入する。"""
    test_app = create_test_app(db_session)
    limiter = RateLimiter(config=_config(), store=InMemoryRateLimitStore(clock=fake_clock))
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def client_default(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """``get_rate_limiter`` を override しない、素の状態のクライアント（TC-37 用）。

    conftest.py が設定する ``RATE_LIMIT_ENABLED=false`` により、グローバル
    シングルトンは常時無効化されている前提を検証する。
    """
    test_app = create_test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def client_killswitch(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """``enabled=False`` を明示注入したクライアント（TC-36 用）。"""
    test_app = create_test_app(db_session)
    limiter = RateLimiter(config=_config(enabled=False), store=InMemoryRateLimitStore())
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


#: ``client_small_limits`` が使う login_ip / line_ip の上限値。
SMALL_LOGIN_IP_MAX = 3
SMALL_LINE_MAX = 3


@pytest.fixture
async def client_small_limits(
    db_session: AsyncSession, fake_clock: FakeClock
) -> AsyncIterator[AsyncClient]:
    """``login_ip_max`` / ``line_max`` を小さく（``SMALL_LOGIN_IP_MAX`` /
    ``SMALL_LINE_MAX`` = 3）した以外は ``client`` と同じクライアント（QA M-4）。

    「不採用→hopsへのフォールバック」「鍵の入れ替え」等、しきい値が具体的に
    本番値（20）である必要のないテストで使うことで、1テストあたりのHTTP
    リクエスト数を減らし試験時間を短縮する。核心の回帰（実際の本番値20で
    しきい値に到達することの確認）は ``client`` を使う
    ``TestRelayCoreBehavior`` に1本だけ残す。
    """
    test_app = create_test_app(db_session)
    limiter = RateLimiter(
        config=_config(login_ip_max=SMALL_LOGIN_IP_MAX, line_max=SMALL_LINE_MAX),
        store=InMemoryRateLimitStore(clock=fake_clock),
    )
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


# ──────────────────────────── login: アカウント軸 ────────────────────────────


class TestLoginAccountAxis:
    async def test_tc20_five_failures_then_429_with_retry_after(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc20@example.com")
        for _ in range(5):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": "tc20@example.com", "password": "wrong-password"},
            )
            assert r.status_code == 401
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc20@example.com", "password": "wrong-password"},
        )
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        assert int(r.headers["Retry-After"]) >= 1

    async def test_tc21_response_body_shape_and_message(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc21@example.com")
        for _ in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"email": "tc21@example.com", "password": "wrong-password"},
            )
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc21@example.com", "password": "wrong-password"},
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _LOGIN_MSG}

    async def test_tc22_successful_logins_never_consume_account_axis(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc22@example.com", password="correct-password1")
        for _ in range(20):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": "tc22@example.com", "password": "correct-password1"},
            )
            assert r.status_code == 200

    async def test_tc23_success_resets_account_axis(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc23@example.com", password="correct-password1")
        for _ in range(4):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": "tc23@example.com", "password": "wrong-password"},
            )
            assert r.status_code == 401
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc23@example.com", "password": "correct-password1"},
        )
        assert r.status_code == 200
        for _ in range(5):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": "tc23@example.com", "password": "wrong-password"},
            )
            assert r.status_code == 401
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc23@example.com", "password": "wrong-password"},
        )
        assert r.status_code == 429

    async def test_tc24_axis_independence_across_accounts_same_ip(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc24a@example.com")
        await _create_user(db_session, "tc24b@example.com", password="correct-password2")
        for _ in range(5):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": "tc24a@example.com", "password": "wrong-password"},
            )
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc24a@example.com", "password": "wrong-password"},
        )
        assert r.status_code == 429

        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc24b@example.com", "password": "correct-password2"},
        )
        assert r.status_code == 200

    async def test_tc28_window_advance_reopens_login(
        self, client: AsyncClient, fake_clock: FakeClock, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc28@example.com", password="correct-password3")
        for _ in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"email": "tc28@example.com", "password": "wrong-password"},
            )
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc28@example.com", "password": "wrong-password"},
        )
        assert r.status_code == 429

        fake_clock.advance(901)
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc28@example.com", "password": "correct-password3"},
        )
        assert r.status_code == 200


# ──────────────────────────── login: IP軸 ────────────────────────────


class TestLoginIpAxis:
    async def test_tc25_ip_axis_blocks_after_20_across_distinct_accounts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        xff = {"X-Forwarded-For": "198.51.100.10"}
        for i in range(20):
            await _create_user(db_session, f"tc25-{i}@example.com")
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": f"tc25-{i}@example.com", "password": "wrong-password"},
                headers=xff,
            )
            assert r.status_code == 401
        await _create_user(db_session, "tc25-final@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc25-final@example.com", "password": "wrong-password"},
            headers=xff,
        )
        assert r.status_code == 429

    async def test_qa_m1_ip_axis_exhausted_first_blocks_even_correct_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """QA指摘 M-1: IP軸を先に枯渇させた状態では、正しいパスワードでも
        429 になることを固定化する（意図された設計だが、未テストのため
        将来のリファクタで崩れうる。ガードの IP軸事前判定はパスワード検証
        より前に実行されるため、この優先順位が成立する）。"""
        xff = {"X-Forwarded-For": "198.51.100.40"}
        for i in range(20):
            email = f"qa-m1-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=xff,
            )
            assert r.status_code == 401

        # 今まで一度も試行していない、正しいパスワードを持つ新規アカウント。
        await _create_user(
            db_session, "qa-m1-fresh@example.com", password="totally-correct-pass1"
        )
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "qa-m1-fresh@example.com", "password": "totally-correct-pass1"},
            headers=xff,
        )
        assert r.status_code == 429

    async def test_tc26_ip_axis_separated_by_different_xff(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        for i in range(20):
            email = f"tc26-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers={"X-Forwarded-For": "198.51.100.20"},
            )
            assert r.status_code == 401
        # 別 IP からは全く影響を受けない。
        await _create_user(db_session, "tc26-other@example.com", password="correct-password4")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc26-other@example.com", "password": "correct-password4"},
            headers={"X-Forwarded-For": "198.51.100.21"},
        )
        assert r.status_code == 200

    async def test_tc27_message_identical_between_account_and_ip_axis(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc27-acct@example.com")
        for _ in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"email": "tc27-acct@example.com", "password": "wrong-password"},
            )
        r_acct = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc27-acct@example.com", "password": "wrong-password"},
        )
        assert r_acct.status_code == 429

        xff = {"X-Forwarded-For": "198.51.100.30"}
        for i in range(20):
            email = f"tc27-ip-{i}@example.com"
            await _create_user(db_session, email)
            await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=xff,
            )
        await _create_user(db_session, "tc27-ip-final@example.com")
        r_ip = await client.post(
            "/api/v1/auth/login",
            json={"email": "tc27-ip-final@example.com", "password": "wrong-password"},
            headers=xff,
        )
        assert r_ip.status_code == 429
        assert r_acct.json()["detail"] == r_ip.json()["detail"]


# ──────────────────────────── operator login ────────────────────────────


class TestOperatorLogin:
    async def test_tc29_operator_login_also_gets_429(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_operator(db_session, "tc29-op@example.com", password="operatorpass1")
        for _ in range(5):
            r = await client.post(
                "/api/v1/auth/operator/login",
                json={"email": "tc29-op@example.com", "password": "wrong-password"},
            )
            assert r.status_code == 401
        r = await client.post(
            "/api/v1/auth/operator/login",
            json={"email": "tc29-op@example.com", "password": "wrong-password"},
        )
        assert r.status_code == 429

    async def test_regression_user_blocked_does_not_block_operator_same_email(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """security review 最優先指摘の回帰テスト（無認証DoS）。

        同一メールアドレスで user アカウントと operator アカウントを作成し、
        user 側を誤パスワード5回で429にした直後、**同一メールアドレスの**
        operator 側へ正しいパスワードでログインすると成功しなければならない
        （ストアキーの実体が "user:"/"operator:" で名前空間分離されているため）。
        分離前は同じアカウント軸バケットを共有し、ここで 429 になっていた
        （攻撃者が相手のメールアドレスを知るだけで低コストのログイン妨害が
        成立する脆弱性だった）。
        """
        shared_email = "shared-identity-a@example.com"
        await _create_user(db_session, shared_email, password="user-correct-pass1")
        await _create_operator(db_session, shared_email, password="operator-correct-pass1")

        for _ in range(5):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": shared_email, "password": "wrong-password"},
            )
            assert r.status_code == 401
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": shared_email, "password": "wrong-password"},
        )
        assert r.status_code == 429

        # user 側が 429 でロックされていても、operator 側は無関係に成功する。
        r = await client.post(
            "/api/v1/auth/operator/login",
            json={"email": shared_email, "password": "operator-correct-pass1"},
        )
        assert r.status_code == 200

    async def test_regression_operator_blocked_does_not_block_user_same_email(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """上記の対称ケース: operator 側を先にロックしても user 側は無関係に成功する。"""
        shared_email = "shared-identity-b@example.com"
        await _create_user(db_session, shared_email, password="user-correct-pass1")
        await _create_operator(db_session, shared_email, password="operator-correct-pass1")

        for _ in range(5):
            r = await client.post(
                "/api/v1/auth/operator/login",
                json={"email": shared_email, "password": "wrong-password"},
            )
            assert r.status_code == 401
        r = await client.post(
            "/api/v1/auth/operator/login",
            json={"email": shared_email, "password": "wrong-password"},
        )
        assert r.status_code == 429

        r = await client.post(
            "/api/v1/auth/login",
            json={"email": shared_email, "password": "user-correct-pass1"},
        )
        assert r.status_code == 200


# ──────────────────────────── パスワード変更 / 退会（ユーザーID軸） ────────────────────────────


class TestSensitiveOperations:
    async def test_tc30_password_change_blocks_after_five_wrong_current(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "tc30@example.com", password="correct-password5")
        token = _user_token(user)
        for _ in range(5):
            r = await client.put(
                "/api/v1/users/me/password",
                json={"current_password": "wrong", "new_password": "newpassword123"},
                headers=_auth(token),
            )
            assert r.status_code == 400
        r = await client.put(
            "/api/v1/users/me/password",
            json={"current_password": "wrong", "new_password": "newpassword123"},
            headers=_auth(token),
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _PASSWORD_MSG}

    async def test_tc30b_correct_password_change_not_rate_limited(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "tc30b@example.com", password="correct-password6")
        token = _user_token(user)
        r = await client.put(
            "/api/v1/users/me/password",
            json={"current_password": "correct-password6", "new_password": "newpassword123"},
            headers=_auth(token),
        )
        assert r.status_code == 200

    async def test_tc31_delete_account_blocks_after_five_wrong_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "tc31@example.com", password="correct-password7")
        token = _user_token(user)
        for _ in range(5):
            r = await client.request(
                "DELETE",
                "/api/v1/users/me",
                json={"password": "wrong", "confirm": True},
                headers=_auth(token),
            )
            # 退会の再認証失敗は403（不可逆操作。業者退会と統一。r8-verify-fix）。
            assert r.status_code == 403
        r = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"password": "wrong", "confirm": True},
            headers=_auth(token),
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _DELETE_MSG}

    async def test_tc32_user_id_axis_independence(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_a = await _create_user(db_session, "tc32a@example.com", password="correct-password8")
        user_b = await _create_user(db_session, "tc32b@example.com", password="correct-password9")
        token_a = _user_token(user_a)
        token_b = _user_token(user_b)
        for _ in range(5):
            await client.put(
                "/api/v1/users/me/password",
                json={"current_password": "wrong", "new_password": "newpassword123"},
                headers=_auth(token_a),
            )
        r_a = await client.put(
            "/api/v1/users/me/password",
            json={"current_password": "wrong", "new_password": "newpassword123"},
            headers=_auth(token_a),
        )
        assert r_a.status_code == 429

        r_b = await client.put(
            "/api/v1/users/me/password",
            json={"current_password": "correct-password9", "new_password": "newpassword123"},
            headers=_auth(token_b),
        )
        assert r_b.status_code == 200


# ──────────────────────────── LINE連携 再認証/解除（scope="line_link_reauth"） ────────────────────────────


class TestLineLinkReauthRateLimit:
    async def test_unlink_line_blocks_after_five_wrong_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """DELETE /users/me/line-link にレート制限が効くこと（security review M-1対応）。"""
        user = await _create_user(db_session, "rl_unlink@example.com", password="correct-password10")
        user.line_user_id = "U" + "f" * 32
        await db_session.commit()
        token = _user_token(user)
        for _ in range(5):
            r = await client.request(
                "DELETE",
                "/api/v1/users/me/line-link",
                json={"current_password": "wrong"},
                headers=_auth(token),
            )
            assert r.status_code == 400
        r = await client.request(
            "DELETE",
            "/api/v1/users/me/line-link",
            json={"current_password": "wrong"},
            headers=_auth(token),
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _DELETE_MSG}

    async def test_operator_reauth_token_blocks_after_five_wrong_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        operator = await _create_operator(
            db_session, "rl_op_reauth@example.com", password="operatorpass1"
        )
        token = _operator_token(operator)
        for _ in range(5):
            r = await client.post(
                "/api/v1/operator/reauth-token",
                json={"current_password": "wrong"},
                headers=_auth(token),
            )
            assert r.status_code == 400
        r = await client.post(
            "/api/v1/operator/reauth-token",
            json={"current_password": "wrong"},
            headers=_auth(token),
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _DELETE_MSG}

    async def test_unlink_operator_line_blocks_after_five_wrong_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        operator = await _create_operator(
            db_session, "rl_op_unlink@example.com", password="operatorpass1"
        )
        operator.line_user_id = "U" + "1" * 32
        await db_session.commit()
        token = _operator_token(operator)
        for _ in range(5):
            r = await client.request(
                "DELETE",
                "/api/v1/operator/line-link",
                json={"current_password": "wrong"},
                headers=_auth(token),
            )
            assert r.status_code == 400
        r = await client.request(
            "DELETE",
            "/api/v1/operator/line-link",
            json={"current_password": "wrong"},
            headers=_auth(token),
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _DELETE_MSG}


# ──────────────────────────── signup（全リクエストカウント） ────────────────────────────


class TestSignup:
    async def test_tc33_ten_signups_then_eleventh_429(self, client: AsyncClient):
        for i in range(10):
            r = await _signup_user(client, f"tc33-{i}@example.com")
            assert r.status_code == 201, r.text
        r = await _signup_user(client, "tc33-11@example.com")
        assert r.status_code == 429
        assert r.json() == {"detail": _SIGNUP_MSG}

    async def test_tc34_conflict_409_also_counted(self, client: AsyncClient):
        r = await _signup_user(client, "tc34-dup@example.com")
        assert r.status_code == 201
        for _ in range(9):
            r = await _signup_user(client, "tc34-dup@example.com")
            assert r.status_code == 409
        r = await _signup_user(client, "tc34-dup@example.com")
        assert r.status_code == 429


# ──────────────────────────── 不正な XFF（フェイルクローズ） ────────────────────────────


class TestMalformedXffFailsClosed:
    """security review 指摘（M-5後半）: XFF ヘッダが存在するのに解決できない
    場合、以前は無言で IP 軸をスキップしていた（signup 等 IP 軸しか持たない
    スコープが完全に無防備になる）。ガード側でこれを検知し 400 で拒否する。

    XFF ヘッダがそもそも無い場合は従来どおりスキップし、400 にはならない
    （インフラ構成としてありうる状態のため）。QA指摘 M-2: ログインフロー
    自体がクラッシュ（500）しないことも併せて確認する。
    """

    async def test_signup_with_unresolvable_xff_is_rejected_400(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "malformed-xff-signup@example.com",
                "password": "password123",
                "name": "テスト太郎",
            },
            headers={"X-Forwarded-For": "not-an-ip"},
        )
        assert r.status_code == 400

    async def test_login_with_unresolvable_xff_is_rejected_400_not_500(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "malformed-xff-login@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "malformed-xff-login@example.com", "password": "wrong-password"},
            headers={"X-Forwarded-For": "; DROP TABLE"},
        )
        assert r.status_code == 400
        assert r.status_code != 500

    async def test_login_without_xff_header_is_not_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """XFF ヘッダがそもそも無い場合は 400 にならない（IP軸スキップのみ）。"""
        user = await _create_user(
            db_session, "no-xff-login@example.com", password="correct-password-noxff"
        )
        assert user is not None
        r = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "no-xff-login@example.com",
                "password": "correct-password-noxff",
            },
        )
        assert r.status_code == 200


# ──────── 攻撃者が誘発できない異常値 → IP軸スキップ（新設・security Critical） ────────


class TestSpecialUseAddressAtTrustPositionSkipsIpAxis:
    """信頼位置（parts[-trusted_hops]）に「攻撃者が誘発できない」異常値
    （未指定/マルチキャスト/予約済み）が現れた場合、フェイルクローズ(400)
    ではなくIP軸スキップに倒れることを確認する。攻撃者はこの位置の値を
    選べない（CF/プロキシが追記する位置）ため、誘発する手段自体が無く、
    スキップしても悪用経路にならない（``is_special_use_address`` 参照）。
    """

    @pytest.mark.parametrize(
        "special_ip",
        [
            "0.0.0.0",  # 未指定 (IPv4)
            "224.0.0.1",  # マルチキャスト
            "240.0.0.1",  # IETF予約済み (Class E)
        ],
    )
    async def test_special_use_address_skips_ip_axis_but_not_400(
        self, client: AsyncClient, db_session: AsyncSession, special_ip: str
    ):
        headers = {"X-Forwarded-For": special_ip}
        # IP軸の上限(20)を超える25回、別々のアカウントで失敗させても、
        # IP軸自体がスキップされているため 429 にも 400 にもならない。
        for i in range(25):
            email = f"special-{special_ip.replace('.', '-')}-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401


# ──────── CFレンジは攻撃者が誘発可能 → スキップせずカウント継続（WARNINGのみ） ────────


class TestCloudflareRangeAtTrustPositionDoesNotBypassIpAxis:
    """信頼位置が Cloudflare 公開レンジ内でも IP軸のカウントは継続する
    ことを固定化する（security review Critical 是正・撤回済み scan 方式の
    教訓）。スキップに倒すと、Cloudflare Workers 等から無料で取得できる
    CF egress IP を信頼位置に送り込むだけで IP軸を恒常的に無効化できて
    しまう（signup 等 IP軸しか持たないスコープが常時無防備になる）。ここでは
    カウントが継続していること（＝バイパスが生まれていないこと）を、IP軸
    上限(20)ちょうどで429になることで固定化する。
    """

    async def test_cf_range_ip_still_counted_and_eventually_429(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        cf_range_xff = {"X-Forwarded-For": "172.68.10.20"}  # Cloudflare公開レンジ内
        for i in range(20):
            email = f"cf-range-count-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=cf_range_xff,
            )
            assert r.status_code == 401
        await _create_user(db_session, "cf-range-count-21@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "cf-range-count-21@example.com", "password": "wrong-password"},
            headers=cf_range_xff,
        )
        # スキップされていれば 401 のままのはず。カウントが継続しているため
        # 21回目（上限20超過）で 429 になる。
        assert r.status_code == 429

    async def test_cf_range_ip_does_not_fail_closed(self, client: AsyncClient):
        """CFレンジは "攻撃者が誘発できる条件" として WARNING のみに倒す
        （フェイルクローズしない。400にならないことの確認）。"""
        r = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "cf-range-signup@example.com",
                "password": "password123",
                "name": "テスト太郎",
            },
            headers={"X-Forwarded-For": "172.68.10.20"},
        )
        assert r.status_code != 400
        assert r.status_code == 201


# ──────── ドリフト検知（scanとhopsの不一致）は判定結果に一切影響しない ────────


class TestScanDriftDetectionDoesNotAffectDecision:
    """診断専用の ``scan_client_ip_for_diagnostics`` と hops 方式の解決結果が
    不一致（ドリフト検知が発火する状況）でも、実際のレート制限の判定結果
    （200/401/429/400 のいずれになるか）が一切変わらないことを固定化する
    （``_check_scan_drift`` は WARNING を出すだけで分岐を持たない）。"""

    async def test_mismatch_case_login_still_behaves_normally(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # CFレンジ単体のXFF: hops は "172.68.10.20" をそのまま採用するが、
        # 診断用scanは信頼済みプロキシのみと判定し all_trusted(None) を返す
        # ため、hopsとscanの結果は必ず不一致になる（ドリフト検知が発火する）。
        # それでもログイン自体は通常どおり 401 で完結することを確認する。
        await _create_user(db_session, "drift-mismatch@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "drift-mismatch@example.com", "password": "wrong-password"},
            headers={"X-Forwarded-For": "172.68.10.20"},
        )
        assert r.status_code == 401


# ──────────────────────────── プライベートIPはIP軸をスキップ ────────────────────────────


class TestPrivateIpAtTrustPositionSkipsIpAxis:
    """security review 指摘C（最重要・全断モードの構造的な封じ込め）。

    TRUSTED_PROXY_HOPS 誤設定で信頼位置（``parts[-trusted_hops]``）に
    内部プロキシの固定IPが来た場合、そのまま IP軸のキーに使うと全ユーザーが
    同一バケットを共有し、数分で全世界のログインが429になる全断を起こす。
    IP軸をスキップすることで、誤構成時でも「レート制限が緩む」だけで済み、
    認証全断は構造的に起こりえなくなる。アカウント軸は依然として通常どおり
    適用されることも併せて確認する。
    """

    async def test_private_ip_skips_ip_axis_but_account_axis_still_enforced(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        private_xff = {"X-Forwarded-For": "10.0.0.5"}

        # IP軸の上限(20)を超える25回、別々のアカウントで失敗させても、
        # IP軸自体がスキップされているため 429 にならない
        # (スキップしていなければ21回目で429になるはず)。
        for i in range(25):
            email = f"priv-ip-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=private_xff,
            )
            assert r.status_code == 401

        # アカウント軸は依然として有効: 同一アカウントを5回失敗させると429。
        target_email = "priv-ip-target@example.com"
        await _create_user(db_session, target_email)
        for _ in range(5):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": target_email, "password": "wrong-password"},
                headers=private_xff,
            )
            assert r.status_code == 401
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": target_email, "password": "wrong-password"},
            headers=private_xff,
        )
        assert r.status_code == 429

    async def test_loopback_ip_at_trust_position_also_skips_ip_axis(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """ループバック(127.0.0.1 等)も同様にスキップ対象。"""
        loopback_xff = {"X-Forwarded-For": "127.0.0.1"}
        for i in range(25):
            email = f"loop-ip-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=loopback_xff,
            )
            assert r.status_code == 401


# ──────── IPv6 の IP軸: /64・/56・/48 の3段で数える（新設） ────────


class TestIpv6RateLimitTiers:
    """IPv6 の IP軸を /64・/56・/48 の3段で数えることの統合テスト。

    修正前は解決した IP の文字列全体をキーにしていたため、IPv6 の利用者
    （自宅回線は通常 /64、日本の IPoE でひかり電話ありの HGW なら /56）は
    要求ごとに送信元アドレスを替えるだけで毎回新しいバケットになり、IP軸
    しか持たないスコープを含む全スコープの IP軸を回避できた。アドレスは
    文書用レンジ 2001:db8::/32（RFC3849）の中で作る。/56 の境界は第4グループの
    上位8ビット（例 2001:db8:5:1:: と 2001:db8:5:ff:: は同じ /56、2001:db8:5:100:: は
    別の /56）。
    """

    async def test_login_ip_axis_blocks_within_same_slash64(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """修正前なら21個の別アドレスは21個の別キーとなり、一度も429に
        ならなかった。"""
        for i in range(20):
            r = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": f"ipv6-64-login-{i}@example.com",
                    "password": "wrong-password",
                },
                headers={"X-Forwarded-For": f"2001:db8:1:1::{i + 1:x}"},
            )
            assert r.status_code == 401

        target_email = "ipv6-64-login-target@example.com"
        await _create_user(db_session, target_email, password="correct-password-v6")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": target_email, "password": "correct-password-v6"},
            headers={"X-Forwarded-For": "2001:db8:1:1::15"},
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _LOGIN_MSG}

        # 同じ利用者・同じ/48内の別の/64からは影響を受けない。
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": target_email, "password": "correct-password-v6"},
            headers={"X-Forwarded-For": "2001:db8:1:2::1"},
        )
        assert r.status_code == 200

    async def test_signup_ip_axis_blocks_within_same_slash64(self, client: AsyncClient):
        """修正前なら10個の別アドレスは10個の別キーとなり、一度も429に
        ならなかった。"""
        for i in range(10):
            r = await _signup_user(
                client,
                f"ipv6-64-signup-{i}@example.com",
                headers={"X-Forwarded-For": f"2001:db8:1:1::{i + 1:x}"},
            )
            assert r.status_code == 201, r.text
        r = await _signup_user(
            client,
            "ipv6-64-signup-over@example.com",
            headers={"X-Forwarded-For": "2001:db8:1:1::b"},
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _SIGNUP_MSG}

        r = await _signup_user(
            client,
            "ipv6-64-signup-other64@example.com",
            headers={"X-Forwarded-For": "2001:db8:1:2::1"},
        )
        assert r.status_code == 201, r.text

    async def test_operator_application_counts_same_slash64_at_real_hops_position(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """修正前なら本番と同じ段数でも、右から3番目の実アドレスを/64内で
        替えるだけで業者申込の5件/時間の上限を無限に回避できた。記録される
        client_ip は丸めない生のIPv6のままであることも確認する。"""
        monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 3)
        application_ids = []
        real_ips = []
        for i in range(5):
            real_ip = f"2001:db8:1:1::{i + 1:x}"
            real_ips.append(real_ip)
            r = await _post_operator_application(
                client,
                f"oa-v6-64-{i}@example.com",
                headers={
                    "X-Forwarded-For": (
                        f"198.51.100.{i + 1}, {real_ip}, 172.68.10.20, 10.196.14.1"
                    )
                },
            )
            assert r.status_code == 201, r.text
            application_ids.append(uuid.UUID(r.json()["application_id"]))
        r = await _post_operator_application(
            client,
            "oa-v6-64-over@example.com",
            headers={
                "X-Forwarded-For": "198.51.100.99, 2001:db8:1:1::b, 172.68.10.20, 10.196.14.1"
            },
        )
        assert r.status_code == 429

        for application_id, real_ip in zip(application_ids, real_ips):
            application = await db_session.get(OperatorApplication, application_id)
            assert application is not None
            assert application.client_ip == real_ip

    async def test_signup_one_slash56_household_cannot_block_its_slash48_neighbours(
        self, client: AsyncClient, db_session: AsyncSession, caplog
    ):
        """/56 を1つ持つ世帯（日本の IPoE の HGW 等）が /64 を替えながら送っても、上限の
        K56 倍で止まり（axis=ip6_56）、同じ /48 の別の世帯（別の /56）は影響を受けない。
        /64 だけで数える実装なら、/64 を替えるたびに枠が戻って止まらなかった。"""
        existing_email = "ipv6-tier-household-dup@example.com"
        await _create_user(db_session, existing_email)
        # 登録済みのメールで送る: 409 はハッシュ計算が走らず速く、全件方式なので数えられる。
        for t in range(_IPV6_56_LIMIT_MULTIPLIER):
            for i in range(10):
                r = await _signup_user(
                    client,
                    existing_email,
                    headers={"X-Forwarded-For": f"2001:db8:4:{t + 1:x}::{i + 1:x}"},
                )
                assert r.status_code == 409
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            r = await _signup_user(
                client, existing_email, headers={"X-Forwarded-For": "2001:db8:4:ff::1"}
            )
        assert r.status_code == 429
        assert r.json() == {"detail": _SIGNUP_MSG}
        messages = [record.getMessage() for record in caplog.records]
        assert any("scope=signup" in m and "axis=ip6_56" in m for m in messages)

        # 同じ /48 の別の /56（別の世帯）は通る。
        r = await _signup_user(
            client, existing_email, headers={"X-Forwarded-For": "2001:db8:4:100::1"}
        )
        assert r.status_code == 409

    async def test_login_wider_tiers_cap_failures_spread_over_many_slash64(
        self, client: AsyncClient, caplog
    ):
        """/64 を替えながら失敗を積み上げても、同じ /56 では /64 の上限の K56 倍、同じ
        /48 では K48 倍で止まる。/64 だけで数える実装なら、/64 を替えるたびに枠が戻り、
        失敗を無制限に積み上げられた（修正前はアドレスを替えるだけで同じだった）。"""
        slash56_count = _IPV6_48_LIMIT_MULTIPLIER // _IPV6_56_LIMIT_MULTIPLIER
        attempt = 0
        # 存在しないメールで失敗させる（パスワード照合が走らないので速い）。
        for s in range(slash56_count):
            for t in range(_IPV6_56_LIMIT_MULTIPLIER):
                for i in range(20):
                    r = await client.post(
                        "/api/v1/auth/login",
                        json={
                            "email": f"ipv6-tier-login-{attempt}@example.com",
                            "password": "wrong-password",
                        },
                        headers={"X-Forwarded-For": f"2001:db8:2:{s * 0x100 + t + 1:x}::{i + 1:x}"},
                    )
                    attempt += 1
                    assert r.status_code == 401

        blocked = [
            ("2001:db8:2:ff::1", "ip6_56"),  # 失敗で埋まった /56 の新しい /64
            ("2001:db8:2:ff00::1", "ip6_48"),  # 同じ /48 の新しい /56
        ]
        for xff, axis in blocked:
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
                r = await client.post(
                    "/api/v1/auth/login",
                    json={
                        "email": f"ipv6-tier-login-{axis}@example.com",
                        "password": "wrong-password",
                    },
                    headers={"X-Forwarded-For": xff},
                )
            assert r.status_code == 429
            assert r.json() == {"detail": _LOGIN_MSG}
            assert int(r.headers["Retry-After"]) >= 1
            messages = [record.getMessage() for record in caplog.records]
            assert any("scope=login" in m and f"axis={axis} " in m for m in messages)

        # 別の /48 は無関係（存在しないメールなので 401 のまま）。
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "ipv6-tier-login-other48@example.com", "password": "wrong-password"},
            headers={"X-Forwarded-For": "2001:db8:9:1::1"},
        )
        assert r.status_code == 401

    async def test_signup_rejected_requests_are_not_counted_into_wider_tiers(
        self, client: AsyncClient, db_session: AsyncSession, caplog
    ):
        """狭い段で弾かれた要求まで広い段に数える実装だと、1つの /64 の連打で /56・/48 が
        埋まり、同じ範囲の別の /64・/56（別の利用者）の登録が途中から 429 になる。弾かれた
        要求を広い段に数えないことを固定化する（修正前は広い段自体が無かった）。"""
        existing_email = "ipv6-tier-signup-dup@example.com"
        await _create_user(db_session, existing_email)

        async def signup_from(xff: str) -> int:
            r = await _signup_user(client, existing_email, headers={"X-Forwarded-For": xff})
            return r.status_code

        # 最初の /56 の1つ目の /64: 10 回は 409（全件方式なので数える）、続く 5 回は
        # /64 の上限で 429。
        for i in range(10):
            assert await signup_from(f"2001:db8:5:1::{i + 1:x}") == 409
        for i in range(5):
            assert await signup_from(f"2001:db8:5:1::{i + 11:x}") == 429
        # 同じ /56 の残りの /64 も 10 回ずつ 409。/64 で弾かれた 5 回を /56 に数えて
        # いれば、ここで途中から 429 になる。
        for t in range(1, _IPV6_56_LIMIT_MULTIPLIER):
            for i in range(10):
                assert await signup_from(f"2001:db8:5:{t + 1:x}::{i + 1:x}") == 409
        # 最初の /56 は埋まった。同じ /56 の新しい /64 は /56 の段で弾かれる（/48 に数えない）。
        for i in range(5):
            assert await signup_from(f"2001:db8:5:ff::{i + 1:x}") == 429
        # 同じ /48 の残りの /56 で /48 を埋める。弾かれた要求を /48 に数えていれば途中から 429。
        slash56_count = _IPV6_48_LIMIT_MULTIPLIER // _IPV6_56_LIMIT_MULTIPLIER
        for s in range(1, slash56_count):
            for t in range(_IPV6_56_LIMIT_MULTIPLIER):
                for i in range(10):
                    xff = f"2001:db8:5:{s * 0x100 + t + 1:x}::{i + 1:x}"
                    assert await signup_from(xff) == 409
        # /48 は上限に達した。同じ /48 の新しい /56 は /48 の段で 429（axis=ip6_48）。
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            assert await signup_from("2001:db8:5:ff00::1") == 429
        messages = [record.getMessage() for record in caplog.records]
        assert any("scope=signup" in m and "axis=ip6_48" in m for m in messages)

    async def test_bucket_count_does_not_grow_once_wider_tiers_are_saturated(
        self, db_session: AsyncSession
    ):
        """広い段が塞がった後も、新しい /64 から来るたびにストアのキーが増える実装だと、
        大量の /64 を送りつけるだけでメモリ（RL_MAX_KEYS）を圧迫できる。塞がった後は
        新しい /64・/56 からの要求も peek で弾かれるだけで、キーを作らないことを固定化する。"""
        test_app = create_test_app(db_session)
        store = InMemoryRateLimitStore(clock=FakeClock())
        limiter = RateLimiter(config=_config(), store=store)
        test_app.dependency_overrides[get_rate_limiter] = lambda: limiter
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as saturating_client:
            existing_email = "ipv6-tier-saturate-dup@example.com"
            await _create_user(db_session, existing_email)
            slash56_count = _IPV6_48_LIMIT_MULTIPLIER // _IPV6_56_LIMIT_MULTIPLIER
            for s in range(slash56_count):
                for t in range(_IPV6_56_LIMIT_MULTIPLIER):
                    for i in range(10):
                        r = await _signup_user(
                            saturating_client,
                            existing_email,
                            headers={
                                "X-Forwarded-For": f"2001:db8:6:{s * 0x100 + t + 1:x}::{i + 1:x}"
                            },
                        )
                        assert r.status_code == 409

            key_count_before = len(store)
            # 埋まった /56 の新しい /64 と、同じ /48 の新しい /56 から送る。
            for xff in (
                "2001:db8:6:ff::1",
                "2001:db8:6:fe::1",
                "2001:db8:6:ff00::1",
                "2001:db8:6:fe00::1",
                "2001:db8:6:fd00::1",
            ):
                r = await _signup_user(
                    saturating_client, existing_email, headers={"X-Forwarded-For": xff}
                )
                assert r.status_code == 429
            assert len(store) == key_count_before

    async def test_narrow_tier_over_limit_log_shows_ip6_64_axis_and_slash48_ip_net(
        self, client: AsyncClient, caplog
    ):
        """超過ログの ip_net は生のIPv6アドレスでも/64表記でもなく、常に
        /48に丸めた値であることを固定化する(truncate_ip_for_logの既定仕様)。
        修正前はキーがアドレス全体だったため、この段(axis=ip6_64)自体が
        存在しなかった。"""
        raw_ip = "2001:db8:3:1::b"
        for i in range(10):
            r = await _signup_user(
                client,
                f"ipv6-64-log-{i}@example.com",
                headers={"X-Forwarded-For": f"2001:db8:3:1::{i + 1:x}"},
            )
            assert r.status_code == 201, r.text
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            r = await _signup_user(
                client, "ipv6-64-log-over@example.com", headers={"X-Forwarded-For": raw_ip}
            )
        assert r.status_code == 429
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "scope=signup" in m and "axis=ip6_64" in m and "ip_net=2001:db8:3::/48" in m
            for m in messages
        )
        assert not any(raw_ip in m for m in messages)
        assert not any("/64" in m for m in messages)


# ──────────────────────────── LINEログイン統合（全リクエストカウント） ────────────────────────────


def _mock_line_verify_response(
    client_id: str = _TEST_LINE_CLIENT_ID, expires_in: int = 3600
) -> httpx.Response:
    return httpx.Response(
        200, json={"client_id": client_id, "expires_in": expires_in, "scope": "profile"}
    )


def _mock_line_profile_response(user_id: str) -> httpx.Response:
    return httpx.Response(200, json={"userId": user_id, "displayName": "テストユーザー"})


def _mock_line_get(user_id: str = "Uc682572a6a72e6504e76b92ae3c05732") -> AsyncMock:
    verify_res = _mock_line_verify_response()
    profile_res = _mock_line_profile_response(user_id)

    async def _side_effect(url, *args, **kwargs):
        if url == auth_endpoint._LINE_VERIFY_ENDPOINT:
            return verify_res
        if url == auth_endpoint._LINE_PROFILE_ENDPOINT:
            return profile_res
        raise AssertionError(f"未想定のURLへのリクエスト: {url}")

    return AsyncMock(side_effect=_side_effect)


class TestLineExchange:
    async def test_tc35_twenty_requests_then_twentyfirst_429(
        self, client: AsyncClient, monkeypatch
    ):
        settings = get_settings()
        monkeypatch.setattr(settings, "line_client_id", _TEST_LINE_CLIENT_ID)
        # ASGITransport 経由では request.client.host が "127.0.0.1"（真正の
        # ループバック）になるため、XFF 無指定だと security review 指摘Cにより
        # IP軸が常にスキップされる。本番では Render の LB が必ず XFF を
        # 付与するため、実在しない公開IP（RFC5737）を明示して実態に近づける。
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get()):
            for _ in range(20):
                r = await client.post(
                    "/api/v1/auth/line/exchange",
                    json={"line_access_token": "dummy-line-token"},
                    headers=_TEST_PUBLIC_IP_HEADERS,
                )
                assert r.status_code == 200
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=_TEST_PUBLIC_IP_HEADERS,
            )
        assert r.status_code == 429
        assert r.json() == {"detail": _LINE_MSG}


# ──────────────────────────── 案件作成（コストDoS対策・IP軸/アカウント軸とも全リクエストカウント） ────────────────────────────


def _minimal_case_payload() -> dict:
    """AI解析（Gemini呼び出し）を経由しない最小の案件作成ペイロード。

    photos/items を空にすることで generate_case_summary が空リストに対して
    即座にフォールバック文を返すため、Google API キー等の外部依存なしに
    レート制限の判定（IP軸/アカウント軸のカウント）のみを検証できる。
    """
    return {
        "purpose": "遺品整理",
        "prefecture": "東京都",
        "city": "世田谷区",
        "photos": [],
        "items": [],
    }


class TestCaseCreateRateLimit:
    """``POST /cases`` のコストDoS対策レート制限（security review 指摘対応）。

    AI解析(Gemini呼び出し)を伴うため、認証済みアカウントでも高頻度作成で
    コストが積み上がる。IP軸・アカウント軸とも成功/失敗を問わず全リクエスト
    をカウントする方式（signupと同様）。
    """

    async def test_account_axis_blocks_after_ten(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """ループバックIP（IP軸は自動スキップされる）の下でアカウント軸のみを検証する。"""
        user = await _create_user(db_session, "case-create-acct@example.com")
        token = _user_token(user)
        for _ in range(10):
            r = await client.post(
                "/api/v1/cases", json=_minimal_case_payload(), headers=_auth(token)
            )
            assert r.status_code == 201, r.text
        r = await client.post(
            "/api/v1/cases", json=_minimal_case_payload(), headers=_auth(token)
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _CASE_CREATE_MSG}

    async def test_ip_axis_blocks_after_ten_across_distinct_accounts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """別々のアカウントでも同一IPからの作成回数が上限(10)を超えると429になる。"""
        xff = {"X-Forwarded-For": "198.51.100.77"}
        for i in range(10):
            user = await _create_user(db_session, f"case-create-ip-{i}@example.com")
            token = _user_token(user)
            r = await client.post(
                "/api/v1/cases",
                json=_minimal_case_payload(),
                headers={**_auth(token), **xff},
            )
            assert r.status_code == 201, r.text
        user = await _create_user(db_session, "case-create-ip-final@example.com")
        token = _user_token(user)
        r = await client.post(
            "/api/v1/cases",
            json=_minimal_case_payload(),
            headers={**_auth(token), **xff},
        )
        assert r.status_code == 429
        assert r.json() == {"detail": _CASE_CREATE_MSG}


_CONTACT_MSG = "お問い合わせが集中しています。時間をおいて再度お送りください。"


class TestContactRateLimit:
    """``POST /contact`` のレート制限（security review H-1 / N-2対応）。

    config.py に新規スコープを追加しない方針のため、数値ルールは既存の
    case_create（IP軸・アカウント軸とも10req/3600s、両軸とも全リクエスト
    カウント）を流用するが、scope 名は専用の "contact" に分離しているため
    バケット実体は POST /cases とは独立している（N-2対応）。
    """

    @pytest.fixture(autouse=True)
    def _reset_contact_process_cap(self):
        """contact.py のプロセス内キャップ（N-4）はモジュールグローバルの
        deque でテスト間共有されるため、各テスト前にリセットする（R-M4対応）。
        """
        from app.api.v1.endpoints import contact as contact_endpoint

        contact_endpoint._recent_notification_timestamps.clear()
        yield
        contact_endpoint._recent_notification_timestamps.clear()

    @staticmethod
    def _payload(email: str) -> dict:
        return {
            "name": "テスト太郎",
            "email": email,
            "category": "trouble",
            "message": "取引でトラブルが発生しました。ご確認をお願いします。",
        }

    async def test_ip_axis_blocks_after_ten_across_distinct_emails(self, client: AsyncClient):
        """同一IPから異なるメールアドレスで送っても、IP軸の上限(10)超過で429になる。"""
        xff = {"X-Forwarded-For": "198.51.100.88"}
        with patch(
            "app.api.v1.endpoints.contact.notify.send_contact_received",
            new_callable=AsyncMock,
        ):
            for i in range(10):
                r = await client.post(
                    "/api/v1/contact",
                    json=self._payload(f"contact-ip-{i}@example.com"),
                    headers=xff,
                )
                assert r.status_code == 202, r.text
            r = await client.post(
                "/api/v1/contact",
                json=self._payload("contact-ip-final@example.com"),
                headers=xff,
            )
        assert r.status_code == 429
        assert r.json() == {"detail": _CONTACT_MSG}

    async def test_account_axis_blocks_after_ten_for_same_email(self, client: AsyncClient):
        """ループバックIP（IP軸は自動スキップされる）の下で、同一メールアドレス
        への hit_account（アカウント軸）のみを検証する。"""
        with patch(
            "app.api.v1.endpoints.contact.notify.send_contact_received",
            new_callable=AsyncMock,
        ):
            for _ in range(10):
                r = await client.post(
                    "/api/v1/contact", json=self._payload("contact-acct@example.com")
                )
                assert r.status_code == 202, r.text
            r = await client.post(
                "/api/v1/contact", json=self._payload("contact-acct@example.com")
            )
        assert r.status_code == 429
        assert r.json() == {"detail": _CONTACT_MSG}


# ──────────────────── 業者事前申込（/operator-applications・IP軸） ────────────────────

_OPERATOR_APPLICATION_MSG = "送信回数の上限に達しました。しばらく時間をおいて再度お試しください。"

# 2026-09-26 に本番（TRUSTED_PROXY_HOPS=3）で実測した X-Forwarded-For のうち、
# 利用者が書けない右側3段（実クライアント, Cloudflare, Render 内部）。左に何を
# 足しても右から3番目（実クライアント）は変わらない。
_OA_REAL_CLIENT_IP = "203.0.113.50"
_OA_PROXY_APPENDED = f"{_OA_REAL_CLIENT_IP}, 172.68.10.20, 10.196.14.1"


async def _post_operator_application(
    client: AsyncClient,
    email: str,
    headers: dict[str, str] | list[tuple[str, str]] | None = None,
) -> httpx.Response:
    """業者事前申込を送る（既定の XFF は ``_signup_user`` と同じ RFC5737 の公開IP 1段）。"""
    return await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email=email),
        headers=headers if headers is not None else _TEST_PUBLIC_IP_HEADERS,
    )


class TestOperatorApplicationIpAxis:
    """``POST /operator-applications``（無認証・/business の送信先）の IP 軸
    （同一IPから1時間5件・全リクエストカウント）。

    以前はエンドポイントが X-Forwarded-For の先頭（利用者が自由に書ける値）で
    DB の件数を数えていたため、リクエストごとに XFF を付け替えるだけで制限を
    回避でき、記録される client_ip も偽の値になっていた。現在は他のスコープと
    同じ ``RateLimitGuard``（右から N 番目の正本解決）で判定する。
    """

    async def test_sixth_from_same_ip_is_429_and_other_ip_is_unaffected(
        self, client: AsyncClient
    ):
        for i in range(5):
            r = await _post_operator_application(client, f"oa-limit-{i}@example.com")
            assert r.status_code == 201, r.text
        r = await _post_operator_application(client, "oa-limit-over@example.com")
        assert r.status_code == 429
        assert r.json() == {"detail": _OPERATOR_APPLICATION_MSG}
        assert int(r.headers["Retry-After"]) >= 1

        r = await _post_operator_application(
            client,
            "oa-limit-other-ip@example.com",
            headers={"X-Forwarded-For": "198.51.100.201"},
        )
        assert r.status_code == 201, r.text

    async def test_spoofed_leftmost_xff_is_counted_as_same_ip(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """リクエストごとに先頭の偽の値を変えても、右から3番目の実IPで数えて記録する
        （修正前はこの6件目も 201 で通り、記録も偽の値だった）。"""
        monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 3)
        application_ids = []
        for i in range(5):
            r = await _post_operator_application(
                client,
                f"oa-spoof-{i}@example.com",
                headers={"X-Forwarded-For": f"198.51.100.{i + 1}, {_OA_PROXY_APPENDED}"},
            )
            assert r.status_code == 201, r.text
            application_ids.append(uuid.UUID(r.json()["application_id"]))
        r = await _post_operator_application(
            client,
            "oa-spoof-over@example.com",
            headers={"X-Forwarded-For": f"198.51.100.99, {_OA_PROXY_APPENDED}"},
        )
        assert r.status_code == 429

        for application_id in application_ids:
            application = await db_session.get(OperatorApplication, application_id)
            assert application is not None
            assert application.client_ip == _OA_REAL_CLIENT_IP

    async def test_spoofed_value_in_separate_xff_header_line_is_counted_as_same_ip(
        self, client: AsyncClient, monkeypatch
    ):
        """偽の値を別の X-Forwarded-For ヘッダ行で送っても同じIPとして数える
        （headers.get() は先頭行＝偽の値しか返さないため、全行を結合して右から数える）。"""
        monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 3)
        for i in range(5):
            r = await _post_operator_application(
                client,
                f"oa-dup-{i}@example.com",
                headers=[
                    ("X-Forwarded-For", f"198.51.100.{i + 1}"),
                    ("X-Forwarded-For", _OA_PROXY_APPENDED),
                ],
            )
            assert r.status_code == 201, r.text
        r = await _post_operator_application(
            client,
            "oa-dup-over@example.com",
            headers=[
                ("X-Forwarded-For", "198.51.100.99"),
                ("X-Forwarded-For", _OA_PROXY_APPENDED),
            ],
        )
        assert r.status_code == 429

    @pytest.mark.parametrize(
        ("trusted_hops", "xff"),
        [
            (1, "not-an-ip"),  # IP として読めない値
            (3, "198.51.100.7"),  # 信頼する段数より短い（右から3番目が無い）
        ],
    )
    async def test_unresolvable_xff_is_rejected_400_and_not_saved(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
        trusted_hops: int,
        xff: str,
    ):
        monkeypatch.setattr(get_settings(), "trusted_proxy_hops", trusted_hops)
        email = f"oa-bad-xff-{trusted_hops}@example.com"
        r = await _post_operator_application(client, email, headers={"X-Forwarded-For": xff})
        assert r.status_code == 400
        saved = await db_session.scalar(
            select(func.count())
            .select_from(OperatorApplication)
            .where(OperatorApplication.contact_email == email)
        )
        assert saved == 0

    async def test_rejected_422_requests_are_also_counted(self, client: AsyncClient):
        """本文の検証エラーや同意なしで 422 になる送信も数える（ガードは本文の検証より
        先に動く）。依存の順序が変わって数えなくなったら、ここで気づけるようにする。"""
        missing_field = _application_payload(email="oa-422-missing@example.com")
        del missing_field["company_name"]
        not_agreed = _application_payload(email="oa-422-not-agreed@example.com")
        not_agreed["agreed"] = False
        for payload in (missing_field, missing_field, missing_field, not_agreed, not_agreed):
            r = await client.post(
                "/api/v1/operator-applications", json=payload, headers=_TEST_PUBLIC_IP_HEADERS
            )
            assert r.status_code == 422
        r = await _post_operator_application(client, "oa-422-valid@example.com")
        assert r.status_code == 429

    @pytest.mark.parametrize(
        "content_type",
        [
            "text/plain",  # fetch の no-cors で送れる
            None,  # Content-Type なし（Uint8Array 等の本文）
            "application/x-www-form-urlencoded",  # <form> で送れる
            "multipart/form-data",  # <form enctype> で送れる
            "application/csp-report",  # CSP の違反報告（report-uri）
            "application/reports+json",  # Reporting API（FastAPI は JSON として読む）
        ],
    )
    async def test_non_json_body_is_rejected_415_before_counting(
        self, client: AsyncClient, content_type: str | None
    ):
        """第三者のページが訪問者のブラウザからプリフライトなしで送れる（または送れうる）
        本文は、数える前に 415 で止める。通すと本文の検証で 422 になるが、ガードがその前に
        数えるので訪問者の IP の枠を消費してしまう。受け付けるのは application/json だけ。"""
        body = json.dumps(_application_payload(email="oa-simple@example.com")).encode("utf-8")
        headers = dict(_TEST_PUBLIC_IP_HEADERS)
        if content_type is not None:
            headers["Content-Type"] = content_type
        for _ in range(6):
            r = await client.post("/api/v1/operator-applications", content=body, headers=headers)
            assert r.status_code == 415
        # 枠は1件も消費されていない。charset 付きの application/json は通る。
        r = await _post_operator_application(
            client,
            "oa-simple-valid@example.com",
            headers={**_TEST_PUBLIC_IP_HEADERS, "Content-Type": "application/json; charset=utf-8"},
        )
        assert r.status_code == 201, r.text

    @pytest.mark.parametrize(
        ("trusted_position_ip", "counted"),
        [
            ("198.51.100.30", True),  # 公開 IPv4
            ("2001:db8::30", True),  # 公開 IPv6
            ("172.68.10.20", True),  # Cloudflare のレンジ（攻撃者が誘発できるので数え続ける）
            ("10.0.0.5", False),  # プライベート
            ("100.64.0.5", False),  # RFC 6598（クラウド内部で多用）
            ("127.0.0.1", False),  # ループバック
            ("0.0.0.0", False),  # 未指定
            ("224.0.0.1", False),  # マルチキャスト
            ("240.0.0.1", False),  # 予約済み
        ],
    )
    async def test_recorded_ip_matches_what_the_guard_counts(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        trusted_position_ip: str,
        counted: bool,
    ):
        """ガードが IP 軸で数える値だけを client_ip に記録し、数えずにスキップする値は記録
        しない。ガード側にスキップ条件を足して記録側が追従しなかった場合（またはその逆）に
        ここで落ちる（記録側は operator_applications._client_ip_for_record）。"""
        headers = {"X-Forwarded-For": trusted_position_ip}
        application_ids = []
        for i in range(5):
            r = await _post_operator_application(client, f"oa-eq-{i}@example.com", headers=headers)
            assert r.status_code == 201, r.text
            application_ids.append(uuid.UUID(r.json()["application_id"]))
        r = await _post_operator_application(client, "oa-eq-over@example.com", headers=headers)
        assert r.status_code == (429 if counted else 201)

        application = await db_session.get(OperatorApplication, application_ids[0])
        assert application is not None
        assert application.client_ip == (trusted_position_ip if counted else None)

    async def test_over_limit_log_has_only_truncated_ip(self, client: AsyncClient, caplog):
        """超過時の WARNING に生の IP を出さない（/24 に丸めた値のみ）。"""
        raw_ip = "198.51.100.123"
        xff = {"X-Forwarded-For": raw_ip}
        for i in range(5):
            r = await _post_operator_application(client, f"oa-log-{i}@example.com", headers=xff)
            assert r.status_code == 201, r.text
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            r = await _post_operator_application(client, "oa-log-over@example.com", headers=xff)
        assert r.status_code == 429
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "scope=operator_application" in m and "ip_net=198.51.100.0/24" in m for m in messages
        )
        assert not any(raw_ip in m for m in messages)

    async def test_bucket_is_separate_from_signup(self, client: AsyncClient):
        """業者申込の枠を使い切っても、同じIPからの会員登録（signup）は止まらない
        （scope が別なのでバケットを共有しない）。"""
        for i in range(5):
            r = await _post_operator_application(client, f"oa-separate-{i}@example.com")
            assert r.status_code == 201, r.text
        r = await _post_operator_application(client, "oa-separate-over@example.com")
        assert r.status_code == 429

        r = await _signup_user(client, "oa-separate-signup@example.com")
        assert r.status_code == 201, r.text

    async def test_killswitch_disables_the_limit(self, client_killswitch: AsyncClient):
        """緊急停止スイッチ（RATE_LIMIT_ENABLED=false）で他のスコープと同じく止まる
        （以前の DB 件数方式はスイッチの対象外だった）。"""
        for i in range(8):
            r = await _post_operator_application(client_killswitch, f"oa-kill-{i}@example.com")
            assert r.status_code == 201, r.text


# ──────────────────────────── キルスイッチ / 既存テスト非破壊 ────────────────────────────


class TestKillSwitchAndNonRegression:
    async def test_tc36_killswitch_never_429s(
        self, client_killswitch: AsyncClient, db_session: AsyncSession
    ):
        await _create_user(db_session, "tc36@example.com")
        for _ in range(100):
            r = await client_killswitch.post(
                "/api/v1/auth/login",
                json={"email": "tc36@example.com", "password": "wrong-password"},
            )
            assert r.status_code == 401

    async def test_tc37_default_disabled_state_never_429s(self, client_default: AsyncClient):
        for i in range(25):
            email = f"tc37-{i}@example.com"
            r = await _signup_user(client_default, email)
            assert r.status_code == 201, r.text
            r = await client_default.post(
                "/api/v1/auth/login", json={"email": email, "password": "password123"}
            )
            assert r.status_code == 200


# ──────────────────────────── 診断エンドポイント ────────────────────────────


class TestDiagClientIp:
    """診断エンドポイントはフィールド単位でゲートする（security review M-1 対応）。

    エンドポイント自体は常に到達可能（404 で完全に閉じない）。
    ``peer``/``trusted_hops`` のみ ``DIAG_TOKEN`` 一致時に追加される。
    """

    async def test_tc38_unauthorized_access_never_exposes_peer_or_hops(self):
        """DIAG_TOKEN 設定時、トークンなし/誤トークンは基本フィールドのみ返り、
        peer / trusted_hops（内部トポロジ・サーバ設定値）は一切含まれない。"""
        settings = Settings(
            _env_file=None,
            APP_ENV="development",
            jwt_secret="a" * 64,
            diag_token="secret-diag-token",
        )
        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            for params in (None, {"token": "wrong"}):
                r = await ac.get("/api/v1/_diag/client-ip", params=params)
                assert r.status_code == 200
                body = r.json()
                assert "xff_raw" in body
                assert "xff_count" in body
                assert "resolved_ip" in body
                assert "peer" not in body
                assert "trusted_hops" not in body

            r = await ac.get("/api/v1/_diag/client-ip", params={"token": "secret-diag-token"})
            assert r.status_code == 200
            body = r.json()
            assert "peer" in body
            assert body["trusted_hops"] == settings.trusted_proxy_hops

    async def test_tc38b_non_ascii_token_does_not_500(self):
        """非ASCIIトークンでも TypeError→500 にならない（security review M-2）。"""
        settings = Settings(
            _env_file=None,
            APP_ENV="development",
            jwt_secret="a" * 64,
            diag_token="secret-diag-token",
        )
        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/_diag/client-ip", params={"token": "あ"})
            assert r.status_code == 200
            assert "trusted_hops" not in r.json()

    async def test_tc39_base_fields_available_without_diag_token_configured(self):
        """DIAG_TOKEN 未設定（現状のβ運用）でも xff_raw/xff_count/resolved_ip
        は常に取得できる（実測に必要な最小限の情報。§2）。peer/trusted_hops は
        DIAG_TOKEN 自体が未設定のため誰にも返らない。"""
        settings = Settings(_env_file=None, APP_ENV="development", jwt_secret="a" * 64)
        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get(
                "/api/v1/_diag/client-ip",
                headers={"X-Forwarded-For": "203.0.113.9"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["resolved_ip"] == "203.0.113.9"
        assert body["xff_count"] == 1
        assert "xff_raw" in body
        assert "peer" not in body
        assert "trusted_hops" not in body

    async def test_tc39b_full_fields_with_matching_token(self):
        """DIAG_TOKEN 設定 + 一致するトークンでは peer/trusted_hops も含む。
        ``strategy`` は CLIENT_IP_STRATEGY 撤回に伴い削除済みのため、
        認可時でも含まれないことを確認する（qa 指摘 M-2）。"""
        settings = Settings(
            _env_file=None,
            APP_ENV="development",
            jwt_secret="a" * 64,
            diag_token="secret-diag-token",
        )
        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get(
                "/api/v1/_diag/client-ip",
                headers={"X-Forwarded-For": "203.0.113.9"},
                params={"token": "secret-diag-token"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["resolved_ip"] == "203.0.113.9"
        assert body["trusted_hops"] == settings.trusted_proxy_hops
        assert "peer" in body
        assert "strategy" not in body

    async def test_qa_m2_diag_scan_fields_are_populated_and_asserted(self):
        """qa 指摘 M-2: このエンドポイントは TRUSTED_PROXY_HOPS 実測・ドリフト
        検知の唯一の実測器のため、``resolved_ip_scan`` / ``scan_reason`` /
        ``scan_matches_hops`` / ``cf_connecting_ip`` をゼロカバレッジのまま
        放置しない。本番実測連鎖（client → CF → Render内部）を模した XFF で、
        hops方式・診断用scan方式が一致することを実際にassertする。"""
        settings = Settings(_env_file=None, APP_ENV="development", jwt_secret="a" * 64)
        # trusted_proxy_hops の既定値(1)に合わせ、右端が実クライアントIPになる
        # ようヘッダを組む（hops=1 は末尾1件を採用する）。
        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get(
                "/api/v1/_diag/client-ip",
                headers={
                    "X-Forwarded-For": "210.157.193.243",
                    "CF-Connecting-IP": "210.157.193.243",
                },
            )
        assert r.status_code == 200
        body = r.json()
        assert body["resolved_ip"] == "210.157.193.243"
        assert body["resolved_ip_scan"] == "210.157.193.243"
        assert body["scan_reason"] == "ok"
        assert body["scan_matches_hops"] is True
        assert body["cf_connecting_ip"] == "210.157.193.243"

    async def test_qa_m2_diag_scan_reason_all_trusted_and_mismatch_flagged(self):
        """信頼済みプロキシ2段だけの XFF（実クライアントIPを含まない構成）では、
        hops方式（既定 trusted_hops=1）は末尾の内部プロキシIPをそのまま
        ``resolved_ip`` として返してしまう一方、診断用scanは全要素が信頼済み
        と判定して ``all_trusted``（``resolved_ip_scan=None``）を返す。
        両者が一致しないことで ``scan_matches_hops`` が False になり、
        ドリフト検知シグナルとして機能することを確認する。"""
        settings = Settings(_env_file=None, APP_ENV="development", jwt_secret="a" * 64)
        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get(
                "/api/v1/_diag/client-ip",
                headers={"X-Forwarded-For": "172.68.10.20, 10.193.27.131"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["resolved_ip"] == "10.193.27.131"
        assert body["resolved_ip_scan"] is None
        assert body["scan_reason"] == "all_trusted"
        assert body["scan_matches_hops"] is False
