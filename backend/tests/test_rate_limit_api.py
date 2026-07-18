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

from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import get_rate_limiter
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
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from tests.test_rate_limit import FakeClock

_TEST_LINE_CLIENT_ID = "test-line-channel-id-rl"

_LOGIN_MSG = "ログインの試行回数が上限に達しました。しばらく時間をおいて再度お試しください。"
_PASSWORD_MSG = "パスワード変更の試行回数が上限に達しました。しばらく時間をおいて再度お試しください。"
_DELETE_MSG = "試行回数が上限に達しました。しばらく時間をおいて再度お試しください。"
_SIGNUP_MSG = "登録試行が集中しています。しばらく時間をおいて再度お試しください。"
_LINE_MSG = "リクエストが集中しています。しばらく時間をおいて再度お試しください。"


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
) -> RateLimitConfig:
    return RateLimitConfig(
        enabled=enabled,
        login_account=RateLimitRule(login_account_max, login_window),
        login_ip=RateLimitRule(login_ip_max, login_window),
        sensitive_account=RateLimitRule(sensitive_max, sensitive_window),
        signup_ip=RateLimitRule(signup_max, signup_window),
        line_ip=RateLimitRule(line_max, line_window),
        max_keys=10000,
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
            assert r.status_code == 400
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
        """DIAG_TOKEN 設定 + 一致するトークンでは peer/trusted_hops も含む。"""
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
