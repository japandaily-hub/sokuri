"""JSON 必須ゲート（``app.api.json_body_deps.require_json_body``）の単体・統合・
構造検査テスト。

レート制限のテスト（``tests/test_rate_limit_api.py`` / ``tests/test_rate_limit.py``）の
ヘルパーには依存させず、本ファイルだけで完結させる（``_application_payload`` のみ
``tests.test_katadzuke_api`` から借用する）。

構成:
    (a) ``require_json_body`` 自体の単体テスト（許可/拒否する Content-Type の一覧）。
    (b) 拒否時の WARNING ログがスロットリングされ、生のヘッダ値を含まないこと。
    (c) 対象7エンドポイント × 4種の Content-Type で、本文の検証より前に 415 で
        止まり、レート制限を1件も消費しないこと（陽性対照で IP 軸が生きている
        ことも確認する）。
    (d) 認証必須エンドポイント（/cases・/analyze）では、未認証の要求がこのゲート
        にもレート制限にも到達しないこと。ゲート対象外の login（失敗のみカウント）
        でも、JSON 以外の本文が失敗として数えられないこと。
    (e) 「``require_json_body`` を ``RateLimitGuard`` より前に置く」という配置規約
        （``app.api.json_body_deps`` モジュール docstring 参照）を、実アプリの
        全ルートに対して静的に検証する（CI での付け忘れ防止）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable, Iterator

import fastapi.params as fastapi_params
import pytest
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.dependencies.models import Dependant
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import json_body_deps
from app.api.deps import (
    get_case_viewer_actor,
    get_current_actor,
    get_current_admin,
    get_current_operator,
    get_current_user,
    get_current_user_claims,
    get_ops_or_admin,
    get_verified_operator,
)
from app.api.json_body_deps import require_json_body
from app.api.rate_limit_deps import RateLimitGuard, _scope_spec, get_rate_limiter
from app.api.v1.router import api_router
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
)
from app.core.security import create_access_token, hash_password
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from tests.effective_routes import effective_api_routes
from tests.test_katadzuke_api import _application_payload

_UNSUPPORTED_MEDIA_TYPE_DETAIL = "リクエストの形式が正しくありません。"

# ASGITransport 経由では request.client.host が常に "127.0.0.1"（ループバック）に
# なるため、XFF 無指定だと信頼位置がループバックと判定され IP 軸そのものが
# スキップされる（rate_limit_deps._warn_private_ip_skip 参照）。テスト環境の
# TRUSTED_PROXY_HOPS は既定 1 のため、この1段だけで足りる。
_XFF_HEADERS = {"X-Forwarded-For": "198.51.100.200"}


def _config() -> RateLimitConfig:
    """IP 軸の上限を 2 に絞ったテスト専用設定（陽性対照の3回目で 429 になる値）。"""
    return RateLimitConfig(
        enabled=True,
        login_account=RateLimitRule(5, 900),
        login_ip=RateLimitRule(20, 900),
        sensitive_account=RateLimitRule(5, 900),
        signup_ip=RateLimitRule(2, 3600),
        line_ip=RateLimitRule(2, 900),
        max_keys=10000,
        case_create_ip=RateLimitRule(2, 3600),
        case_create_account=RateLimitRule(10, 3600),
        operator_application_ip=RateLimitRule(2, 3600),
    )


def _build_test_app(session: AsyncSession, store: InMemoryRateLimitStore) -> FastAPI:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    limiter = RateLimiter(config=_config(), store=store)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture
def store() -> InMemoryRateLimitStore:
    """``len(store)`` でカウント済みキー数を確認するため、テストで参照を保持する。"""
    return InMemoryRateLimitStore()


@pytest.fixture
async def client(
    db_session: AsyncSession, store: InMemoryRateLimitStore
) -> AsyncIterator[AsyncClient]:
    test_app = _build_test_app(db_session, store)
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers=_XFF_HEADERS,
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_json_body_log_throttle() -> Iterator[None]:
    """``require_json_body`` の拒否ログのスロットル状態をテスト前後で初期化する。

    プロセス内スロットリング（``ThrottledLogger``、既定60秒）はテスト実行順に
    依存させないため、本ファイルの全テストで前後にリセットする。
    """
    json_body_deps._non_json_body_reject_throttle.reset()
    yield
    json_body_deps._non_json_body_reject_throttle.reset()


async def _create_test_user(
    db_session: AsyncSession, email: str, password: str = "password123"
) -> User:
    """DB へ直接ユーザーを作成する（``/auth/signup`` を経由せず、signup 側の
    レート制限バジェットを消費しない。tests/test_rate_limit_api.py の
    ``_create_user`` と同じ作り方）。"""
    user = User(email=email, password_hash=hash_password(password), name="テスト太郎", role="user")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_token(user: User) -> str:
    return create_access_token(user.id, "user", user.role)


def _make_request(content_type: str | None, path: str = "/api/v1/dummy") -> Request:
    """``require_json_body`` を HTTP なしで直接 await するための最小 ASGI scope。

    ``content_type=None`` はヘッダ自体が無い状態、``content_type=""`` はヘッダは
    あるが値が空文字の状態を表す（区別して両方をテストする）。
    """
    content_types = [] if content_type is None else [content_type]
    return _make_request_with_content_types(content_types, path)


def _make_request_with_content_types(
    content_types: list[str], path: str = "/api/v1/dummy"
) -> Request:
    """Content-Type ヘッダを ``content_types`` の順に（複数行も可）持つ最小 ASGI scope。"""
    headers = [(b"content-type", value.encode("utf-8")) for value in content_types]
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


# ──────────────────────────── (a) require_json_body 単体 ────────────────────────────


class TestRequireJsonBodyUnit:
    @pytest.mark.parametrize(
        "content_type",
        [
            "application/json",
            "application/json; charset=utf-8",
            "Application/JSON",
            "application/json ; charset=UTF-8",
            "application/json;",
        ],
    )
    async def test_accepts_application_json_variants(self, content_type: str) -> None:
        request = _make_request(content_type)
        assert await require_json_body(request) is None

    @pytest.mark.parametrize(
        "content_type",
        [
            None,  # Content-Type ヘッダなし
            "",  # ヘッダはあるが空文字
            "text/plain",
            "text/plain; charset=utf-8",
            "application/x-www-form-urlencoded",
            "multipart/form-data; boundary=x",
            "application/csp-report",
            "application/reports+json",
            "application/merge-patch+json",
            "application/jsonx",
            "text/json",
            "application/json, text/plain",
        ],
    )
    async def test_rejects_non_json_content_types_with_415(
        self, content_type: str | None
    ) -> None:
        request = _make_request(content_type)
        with pytest.raises(HTTPException) as exc_info:
            await require_json_body(request)
        assert exc_info.value.status_code == 415
        assert exc_info.value.detail == _UNSUPPORTED_MEDIA_TYPE_DETAIL

    async def test_duplicate_content_type_lines_are_judged_by_the_first_value(self) -> None:
        """Content-Type が複数行あるときは先頭の値で判定する（FastAPI 本体も本文を JSON と
        して読むかを同じ ``request.headers.get("content-type")``＝先頭の値で決めるため、
        判定と本文の読み方が食い違わない。統合側は
        ``test_duplicate_content_type_lines_match_how_fastapi_reads_the_body``）。
        ブラウザの fetch は同名ヘッダを1つの値に結合する（"text/plain, application/json"
        はセーフリスト外でプリフライトが要り、ここでも拒否する）ため、複数行はブラウザ
        以外からしか来ない。"""
        json_first = _make_request_with_content_types(["application/json", "text/plain"])
        assert await require_json_body(json_first) is None

        text_first = _make_request_with_content_types(["text/plain", "application/json"])
        with pytest.raises(HTTPException) as exc_info:
            await require_json_body(text_first)
        assert exc_info.value.status_code == 415


# ──────────────────────────── (b) 拒否時ログのスロットリング ────────────────────────────


class TestRejectionLogging:
    async def test_warning_logged_once_per_throttle_window_without_raw_header(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        request = _make_request(
            "application/x-evil-marker-123", path="/api/v1/dummy-diagnostic-path"
        )
        with caplog.at_level(logging.WARNING, logger="app.api.json_body_deps"):
            with pytest.raises(HTTPException):
                await require_json_body(request)
            # スロットル窓内（既定60秒）の2回目は出ない。
            with pytest.raises(HTTPException):
                await require_json_body(request)

        records = [r for r in caplog.records if r.name == "app.api.json_body_deps"]
        assert len(records) == 1
        message = records[0].getMessage()
        assert "path=/api/v1/dummy-diagnostic-path" in message
        assert "content_type=other" in message
        # 生のヘッダ値（分類できない攻撃者細工値の marker 部分）を含まないこと。
        assert "evil-marker-123" not in message
        assert "x-evil-marker-123" not in message

    async def test_warning_uses_route_template_instead_of_actual_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """照合したルートがあれば、ID 等を含みうる実際のパスではなくテンプレートを出す。"""
        case_id = "123e4567-e89b-12d3-a456-426614174000"
        request = _make_request("text/plain", path=f"/api/v1/cases/{case_id}")
        request.scope["route"] = SimpleNamespace(path="/api/v1/cases/{case_id}")
        with caplog.at_level(logging.WARNING, logger="app.api.json_body_deps"):
            with pytest.raises(HTTPException):
                await require_json_body(request)

        records = [r for r in caplog.records if r.name == "app.api.json_body_deps"]
        assert len(records) == 1
        message = records[0].getMessage()
        assert "path=/api/v1/cases/{case_id}" in message
        assert "content_type=text/plain" in message
        assert case_id not in message


# ──────────────────────────── (c) エンドポイント別: 数える前に 415 ────────────────────────────


@dataclass(frozen=True)
class _GateTargetEndpoint:
    case_id: str
    path: str
    body: dict
    needs_auth: bool = False


def _gate_target_endpoints() -> list[_GateTargetEndpoint]:
    return [
        _GateTargetEndpoint(
            "auth_signup",
            "/api/v1/auth/signup",
            {"email": "gate-signup@example.com", "password": "password123", "name": "テスト太郎"},
        ),
        _GateTargetEndpoint(
            "auth_operator_signup",
            "/api/v1/auth/operator/signup",
            {
                "company_name": "テスト片付け株式会社",
                "email": "gate-opsignup@example.com",
                "password": "operatorpass1",
                "license_number": "第123456789012号",
                "agreed": True,
            },
        ),
        _GateTargetEndpoint(
            "auth_line_exchange",
            "/api/v1/auth/line/exchange",
            {"line_access_token": "dummy-line-token"},
        ),
        _GateTargetEndpoint(
            "contact",
            "/api/v1/contact",
            {
                "name": "テスト太郎",
                "email": "gate-contact@example.com",
                "category": "other",
                "message": "テスト",
            },
        ),
        _GateTargetEndpoint(
            "operator_applications",
            "/api/v1/operator-applications",
            _application_payload(email="gate-oa@example.com"),
        ),
        _GateTargetEndpoint(
            "cases",
            "/api/v1/cases",
            {
                "purpose": "遺品整理",
                "prefecture": "東京都",
                "city": "世田谷区",
                "photos": [],
                "items": [],
            },
            needs_auth=True,
        ),
        _GateTargetEndpoint(
            "analyze",
            "/api/v1/analyze",
            {"base_image": "data:image/png;base64,iVBORw0KGgo="},
            needs_auth=True,
        ),
    ]


class TestPerEndpointGateBeforeCounting:
    @pytest.mark.parametrize(
        "content_type",
        [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"],
        ids=["no_content_type", "text_plain", "form_urlencoded", "multipart"],
    )
    @pytest.mark.parametrize("endpoint", _gate_target_endpoints(), ids=lambda e: e.case_id)
    async def test_non_json_content_type_rejected_before_counting(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        store: InMemoryRateLimitStore,
        endpoint: _GateTargetEndpoint,
        content_type: str | None,
    ) -> None:
        """本文の検証（422）より前に 415 で止まり、IP 軸を1件も消費しない。

        末尾で陽性対照（Content-Type: application/json・本文 ``[]``）を送り、
        このテスト環境で IP 軸が生きており JSON の要求は数えられることを
        併せて確認する（ガードの付け忘れをこの対照が無いと検出できないため）。
        """
        headers: dict[str, str] = {}
        if endpoint.needs_auth:
            user = await _create_test_user(db_session, f"gate-{endpoint.case_id}@example.com")
            headers.update(_bearer(_user_token(user)))
        if content_type is not None:
            headers["Content-Type"] = content_type
        body_bytes = json.dumps(endpoint.body).encode("utf-8")

        last_response = None
        for _ in range(3):
            last_response = await client.post(endpoint.path, content=body_bytes, headers=headers)
            assert last_response.status_code == 415, last_response.text
            assert last_response.json() == {"detail": _UNSUPPORTED_MEDIA_TYPE_DETAIL}
        assert last_response is not None
        if content_type is None:
            # httpx は content= の bytes 送信では Content-Type を自動付与しない
            # （json= や data= の dict とは異なる）ことを確認する。
            assert "content-type" not in last_response.request.headers
        assert len(store) == 0

        json_headers = {**headers, "Content-Type": "application/json"}
        r1 = await client.post(endpoint.path, content=b"[]", headers=json_headers)
        assert r1.status_code == 422, r1.text
        r2 = await client.post(endpoint.path, content=b"[]", headers=json_headers)
        assert r2.status_code == 422, r2.text
        r3 = await client.post(endpoint.path, content=b"[]", headers=json_headers)
        assert r3.status_code == 429, r3.text

    async def test_duplicate_content_type_lines_match_how_fastapi_reads_the_body(
        self, client: AsyncClient, store: InMemoryRateLimitStore
    ) -> None:
        """Content-Type が複数行の要求で、ゲートの判定と FastAPI の本文の読み方が一致する。

        text/plain が先頭なら数えずに 415。application/json が先頭ならゲートを通り、
        FastAPI も同じ先頭の値で本文を JSON として読む（正しい本文なら 201 で登録される）。
        """
        body = json.dumps(
            {"email": "gate-dup-ct@example.com", "password": "password123", "name": "テスト太郎"}
        ).encode("utf-8")

        r = await client.post(
            "/api/v1/auth/signup",
            content=body,
            headers=[("Content-Type", "text/plain"), ("Content-Type", "application/json")],
        )
        assert r.status_code == 415, r.text
        assert len(store) == 0

        r = await client.post(
            "/api/v1/auth/signup",
            content=body,
            headers=[("Content-Type", "application/json"), ("Content-Type", "text/plain")],
        )
        assert r.status_code == 201, r.text
        assert len(store) == 1


# ──────────────────────────── (d) 未認証は数えない（/cases・/analyze） ────────────────────────────


class TestUnauthenticatedRequestsAreNotCounted:
    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (
                "/api/v1/cases",
                {
                    "purpose": "遺品整理",
                    "prefecture": "東京都",
                    "city": "世田谷区",
                    "photos": [],
                    "items": [],
                },
            ),
            ("/api/v1/analyze", {"base_image": "data:image/png;base64,iVBORw0KGgo="}),
        ],
        ids=["cases", "analyze"],
    )
    async def test_unauthenticated_and_invalid_token_never_count(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        store: InMemoryRateLimitStore,
        path: str,
        body: dict,
    ) -> None:
        body_bytes = json.dumps(body).encode("utf-8")
        json_headers = {"Content-Type": "application/json"}

        # Authorization なし × 3 → すべて 401。認証（get_current_user）がガードより
        # 先に宣言されているため、このゲートにもレート制限にも到達しない。
        for _ in range(3):
            r = await client.post(path, content=body_bytes, headers=json_headers)
            assert r.status_code == 401, r.text

        # Bearer invalid-token × 3 → すべて 401。
        for _ in range(3):
            r = await client.post(
                path, content=body_bytes, headers={**json_headers, **_bearer("invalid-token")}
            )
            assert r.status_code == 401, r.text
        assert len(store) == 0

        # 未認証で text/plain を送っても 401（認証が JSON ゲートより先に判定される）。
        r = await client.post(path, content=body_bytes, headers={"Content-Type": "text/plain"})
        assert r.status_code == 401, r.text
        assert len(store) == 0

        # 陽性対照: 認証付きで [] を送ると 422 になり、IP 軸が1件だけ数えられる。
        user = await _create_test_user(
            db_session, f"gate-unauth-{path.rsplit('/', 1)[-1]}@example.com"
        )
        r = await client.post(
            path,
            content=b"[]",
            headers={**json_headers, **_bearer(_user_token(user))},
        )
        assert r.status_code == 422, r.text
        assert len(store) == 1


class TestLoginNonJsonBodiesAreNotCountedAsFailures:
    """login（失敗のみカウント）は JSON 必須ゲートの対象外。ガードは件数を見るだけで、
    数えるのは本文の検証を通ったハンドラ内の ``record_failure``。現状は FastAPI の既定
    （``strict_content_type=True``）により JSON 以外の本文は JSON として読まれず 422 で
    止まるため、第三者のページからは失敗を数えさせられない。この性質を固定する
    （FastAPI の版や設定が変わって本文が読まれるようになると、訪問者の IP と狙った
    アカウントの失敗を数えさせられるようになる。login にもゲートを付けた場合は 415 に
    なり、このテストはそのまま通る）。"""

    @pytest.mark.parametrize(
        "content_type",
        [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"],
        ids=["no_content_type", "text_plain", "form_urlencoded", "multipart"],
    )
    @pytest.mark.parametrize(
        "path", ["/api/v1/auth/login", "/api/v1/auth/operator/login"], ids=["user", "operator"]
    )
    async def test_non_json_login_is_not_counted(
        self,
        client: AsyncClient,
        store: InMemoryRateLimitStore,
        path: str,
        content_type: str | None,
    ) -> None:
        body = json.dumps({"email": "victim@example.com", "password": "wrong-password"}).encode(
            "utf-8"
        )
        headers = {} if content_type is None else {"Content-Type": content_type}
        for _ in range(3):
            r = await client.post(path, content=body, headers=headers)
            assert r.status_code in (415, 422), r.text
        assert len(store) == 0

        # 陽性対照: JSON の誤ったパスワードは失敗として数えられる（IP 軸とアカウント軸の2件）。
        r = await client.post(path, content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 401, r.text
        assert len(store) == 2


# ──────────────────────────── (e) 配置規約の構造検査（CI での付け忘れ防止） ────────────────────────────


#: 認証必須のエンドポイントで、認証依存はガードより前にあるべきという規約の検査対象
#: （app.api.deps 参照。名前・シグネチャは変えない前提で別セッションと確認済み）。
_AUTH_DEPENDENCY_FUNCS = (
    get_current_user,
    get_current_user_claims,
    get_current_operator,
    get_verified_operator,
    get_current_actor,
    get_case_viewer_actor,
    get_current_admin,
    get_ops_or_admin,
)

#: ``_scope_spec`` の呼び出し専用のダミー設定（構造検査は値そのものを使わない。
#: ip_rule/account_rule/count_all の「有無・真偽」だけを見るため、全スコープで
#: 同一のダミールールを渡せば十分）。
_STRUCTURAL_CHECK_RULE = RateLimitRule(1, 1)
_STRUCTURAL_CHECK_CONFIG = RateLimitConfig(
    enabled=True,
    login_account=_STRUCTURAL_CHECK_RULE,
    login_ip=_STRUCTURAL_CHECK_RULE,
    sensitive_account=_STRUCTURAL_CHECK_RULE,
    signup_ip=_STRUCTURAL_CHECK_RULE,
    line_ip=_STRUCTURAL_CHECK_RULE,
    max_keys=10000,
    case_create_ip=_STRUCTURAL_CHECK_RULE,
    case_create_account=_STRUCTURAL_CHECK_RULE,
    public_read_ip=_STRUCTURAL_CHECK_RULE,
    operator_application_ip=_STRUCTURAL_CHECK_RULE,
)

#: 空振り防止: この7本が必ず検査対象（IP軸・count_all・本文あり）に入ること。
_EXPECTED_GATED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/auth/signup"),
        ("POST", "/api/v1/auth/operator/signup"),
        ("POST", "/api/v1/auth/line/exchange"),
        ("POST", "/api/v1/contact"),
        ("POST", "/api/v1/operator-applications"),
        ("POST", "/api/v1/cases"),
        ("POST", "/api/v1/analyze"),
    }
)

#: 空振り防止: 認証規則の検査対象にこの2本が必ず入ること。
_EXPECTED_AUTH_CHECKED_PATHS: frozenset[str] = frozenset({"/api/v1/cases", "/api/v1/analyze"})


#: 本文を持たないのが正常なメソッド（本文なしの IP 軸・全件カウントを許す）。
_BODYLESS_METHODS = frozenset({"GET", "HEAD"})


def _has_request_parameters(dependant: Dependant) -> bool:
    """依存がリクエスト由来の引数（パス・クエリ・ヘッダ・Cookie・本文）やサブ依存を持つか。"""
    return bool(
        dependant.path_params
        or dependant.query_params
        or dependant.header_params
        or dependant.cookie_params
        or dependant.body_params
        or dependant.dependencies
    )


def _dependency_execution_order(dependant: Dependant) -> list[Dependant]:
    """``route.dependant`` を「サブ依存を先に解決→サブ依存自身を呼ぶ」の後行順 DFS で
    辿り、FastAPI 本体（``fastapi.dependencies.utils.solve_dependencies``）と同じ
    実行順で ``Dependant`` を並べて返す。

    宣言順は ``dependant.dependencies`` のリスト順そのもの（デコレータの
    ``dependencies=`` が ``APIRoute.__init__`` で先頭に挿入されるため、エンドポイント
    自身の引数より先に来る）。戻り値には ``route.dependant`` 自身（エンドポイント
    関数本体）は含まない（Depends 経由の依存だけを対象にする）。
    """
    order: list[Dependant] = []
    for sub in dependant.dependencies:
        order.extend(_dependency_execution_order(sub))
        order.append(sub)
    return order


def find_json_gate_violations(
    app: FastAPI, *, gate: Callable[..., Any] = require_json_body
) -> tuple[list[str], set[tuple[str, str]], set[str]]:
    """JSON 必須ゲートの配置規約（``app.api.json_body_deps`` docstring 参照）を
    実アプリの全ルートに対して機械的に検査する。

    対象は、全リクエストを IP 軸でカウントするスコープ
    （``_scope_spec(...).ip_rule is not None and count_all``）のガードを持つルート。
    この条件は ``RateLimitGuard`` の scope 定義から機械的に決まるため、新しい
    スコープを追加した際の付け忘れもここで検知できる。本文を持たない GET・HEAD
    （public_read）は対象外（クロスサイト要求ゲートの構造検査
    ``tests/test_cross_site_guard.py`` の対象）、本文を持たないそれ以外のメソッドと本文がフォームの
    ルートは、JSON ゲートでは守れないので違反として報告する。本文が JSON のルートは、
    ゲート（``gate``。自己検査で差し替えるための引数）がガードより前にあり、ゲートが
    リクエスト由来の引数を持たず、認証依存があればそれもガードより前にあること。

    Returns:
        ``(violations, checked_routes, auth_checked_paths)``。
        ``violations`` が空なら規約に適合している。``checked_routes`` は検査対象に
        なった ``(method, path)`` の集合、``auth_checked_paths`` は認証依存の
        前後関係を検査した path の集合（いずれも空振り防止の検証に使う）。
    """
    violations: list[str] = []
    checked_routes: set[tuple[str, str]] = set()
    auth_checked_paths: set[str] = set()

    for route in effective_api_routes(app):
        order = _dependency_execution_order(route.dependant)
        for guard_index, dep in enumerate(order):
            if not isinstance(dep.call, RateLimitGuard):
                continue
            guard = dep.call
            spec = _scope_spec(guard._scope, _STRUCTURAL_CHECK_CONFIG)
            if not (spec.ip_rule is not None and spec.count_all):
                continue
            if route.body_field is None:
                if set(route.methods or ()) <= _BODYLESS_METHODS:
                    # 本文を持たない GET（public_read）はこのゲートでは守れない対象外。
                    # クロスサイト要求ゲート（app.api.cross_site_deps）が守り、付け忘れは
                    # tests/test_cross_site_guard.py の構造検査が落とす。
                    continue
                violations.append(
                    f"{route.path}: 本文のない {sorted(route.methods or ())} が IP 軸を全件"
                    "カウントしています。第三者のページの <form> 等は本文なしでも送れるため、"
                    f"JSON ゲートでは守れません（scope={guard._scope!r}）。"
                )
                continue
            for method in sorted(route.methods or ()):
                checked_routes.add((method, route.path))

            if isinstance(route.body_field.field_info, fastapi_params.Form):
                violations.append(
                    f"{route.path}: 本文が Form のため JSON ゲートでは守れません"
                    f"（フォームは第三者ページから送れます。scope={guard._scope!r}）。"
                )
                continue

            gate_name = getattr(gate, "__name__", repr(gate))
            json_gate_indexes = [i for i, d in enumerate(order) if d.call is gate]
            if not json_gate_indexes or json_gate_indexes[0] > guard_index:
                violations.append(
                    f"{route.path}: {gate_name} が RateLimitGuard"
                    f"（scope={guard._scope!r}）より前にありません。"
                )
            elif _has_request_parameters(order[json_gate_indexes[0]]):
                # 引数の検証に失敗した依存は呼ばれずに飛ばされ、後続のガードは数える
                # （fastapi.dependencies.utils.solve_dependencies）。順序が正しくても素通りになる。
                violations.append(
                    f"{route.path}: {gate_name} が Request 以外の引数を持っています"
                    "（検証エラーの要求ではゲートが飛ばされ、ガードが数えます）。"
                )

            for auth_dep in _AUTH_DEPENDENCY_FUNCS:
                auth_indexes = [i for i, d in enumerate(order) if d.call is auth_dep]
                if not auth_indexes:
                    continue
                auth_checked_paths.add(route.path)
                if auth_indexes[0] > guard_index:
                    violations.append(
                        f"{route.path}: 認証依存 {auth_dep.__name__} が RateLimitGuard"
                        f"（scope={guard._scope!r}）より前にありません。"
                    )

    return violations, checked_routes, auth_checked_paths


class _DummySignupBody(BaseModel):
    """自己検査用のダミー本文モデル。

    ``from __future__ import annotations``（本ファイル冒頭）下では、FastAPI は
    文字列化されたアノテーションをエンドポイント関数の ``__globals__``
    （モジュールレベルの名前空間）だけで解決する（ローカルスコープは見ない。
    ``fastapi.dependencies.utils.get_typed_annotation`` 参照）。テストメソッドの
    中に本文モデルをローカル定義すると、解決に失敗して ``route.body_field`` が
    黙って ``None`` になり検査対象から漏れてしまうため、モジュールレベルに置く
    （エンドポイント関数自体はテストメソッド内にネストしても ``__globals__`` は
    常にモジュール側になるため問題ない）。
    """

    email: str = "dummy@example.com"


async def _gate_with_header_parameter(content_type: str = Header()) -> None:
    """自己検査用: 引数の検証を持つ（＝検証エラーの要求では飛ばされる）ゲートの悪い例。"""


async def _dependency_wrapping_a_guard(
    _rl: object = Depends(RateLimitGuard("signup")),
) -> None:
    """自己検査用: 別の依存の内側に入れ子になったガード。"""


class TestJsonGatePlacementConvention:
    def test_real_app_has_no_violations_and_covers_expected_routes(self) -> None:
        app = create_app()
        violations, checked_routes, auth_checked_paths = find_json_gate_violations(app)
        assert violations == []
        # 空振り防止: 検査対象に上記7本が含まれること（今後の追加漏れも検知できる
        # ようにするため、完全一致ではなく部分集合で確認する）。
        assert _EXPECTED_GATED_ROUTES <= checked_routes
        assert _EXPECTED_AUTH_CHECKED_PATHS <= auth_checked_paths

    def test_detects_guard_declared_before_the_gate(self) -> None:
        """自己検査: ガードを JSON ゲートより前に宣言したダミールートは違反として
        報告される（検査関数自体が偽陰性を出さないことの確認）。"""

        dummy_app = FastAPI()

        @dummy_app.post("/dummy-wrong-order")
        async def _dummy_endpoint(
            body: _DummySignupBody,
            _rl: object = Depends(RateLimitGuard("signup")),
            _json_only: None = Depends(require_json_body),
        ) -> dict:
            return {"ok": True}

        violations, _checked_routes, _auth_checked_paths = find_json_gate_violations(dummy_app)
        assert violations != []
        assert any("/dummy-wrong-order" in v for v in violations)

    def test_detects_form_body_on_counted_scope(self) -> None:
        """自己検査: 全件カウントの IP 軸スコープで本文がフォームのルートは、ゲートの
        有無に関わらず違反として報告される（フォームは第三者のページからプリフライト
        なしで送れるため、JSON ゲートでは守れない）。"""

        dummy_app = FastAPI()

        @dummy_app.post("/dummy-form-body")
        async def _dummy_endpoint(
            email: str = Form(),
            _json_only: None = Depends(require_json_body),
            _rl: object = Depends(RateLimitGuard("signup")),
        ) -> dict:
            return {"ok": True}

        violations, checked_routes, _auth_checked_paths = find_json_gate_violations(dummy_app)
        assert ("POST", "/dummy-form-body") in checked_routes
        assert any("/dummy-form-body" in v and "Form" in v for v in violations)

    def test_detects_auth_dependency_declared_after_the_guard(self) -> None:
        """自己検査: 認証依存をガードより後に宣言したルート（未認証の要求がガードで
        数えられてしまう配置）は違反として報告される。"""

        dummy_app = FastAPI()

        @dummy_app.post("/dummy-auth-after-guard")
        async def _dummy_endpoint(
            body: _DummySignupBody,
            _json_only: None = Depends(require_json_body),
            _rl: object = Depends(RateLimitGuard("case_create")),
            user: User = Depends(get_current_user),
        ) -> dict:
            return {"ok": True}

        violations, _checked_routes, auth_checked_paths = find_json_gate_violations(dummy_app)
        assert "/dummy-auth-after-guard" in auth_checked_paths
        assert any(
            "/dummy-auth-after-guard" in v and "get_current_user" in v for v in violations
        )

    def test_detects_bodiless_post_but_not_bodiless_get(self) -> None:
        """自己検査: 本文のない POST が IP 軸を全件カウントしていれば違反（第三者のページの
        ``<form>`` は本文なしでも送れる）。本文のない GET（public_read と同じ形）は対象外。"""

        dummy_app = FastAPI()

        @dummy_app.post("/dummy-bodiless-post")
        async def _dummy_post(
            _json_only: None = Depends(require_json_body),
            _rl: object = Depends(RateLimitGuard("line_exchange")),
        ) -> dict:
            return {"ok": True}

        @dummy_app.get("/dummy-bodiless-get")
        async def _dummy_get(_rl: object = Depends(RateLimitGuard("public_read"))) -> dict:
            return {"ok": True}

        violations, _checked_routes, _auth_checked_paths = find_json_gate_violations(dummy_app)
        assert any("/dummy-bodiless-post" in v and "本文のない" in v for v in violations)
        assert not any("/dummy-bodiless-get" in v for v in violations)

    def test_detects_gate_with_request_parameters(self) -> None:
        """自己検査: ゲートがヘッダ等の引数を持つと、検証エラーの要求ではゲートが飛ばされて
        ガードが数えるため、順序が正しくても違反として報告される。"""

        dummy_app = FastAPI()

        @dummy_app.post("/dummy-gate-with-header")
        async def _dummy_endpoint(
            body: _DummySignupBody,
            _json_only: None = Depends(_gate_with_header_parameter),
            _rl: object = Depends(RateLimitGuard("signup")),
        ) -> dict:
            return {"ok": True}

        violations, _checked_routes, _auth_checked_paths = find_json_gate_violations(
            dummy_app, gate=_gate_with_header_parameter
        )
        assert any(
            "/dummy-gate-with-header" in v and "Request 以外の引数" in v for v in violations
        )

    def test_detects_guard_in_decorator_dependencies_or_nested_in_another_dependency(
        self,
    ) -> None:
        """自己検査: デコレータの ``dependencies=`` のガード（シグネチャの依存より先に実行
        される）と、別の依存の内側に入れ子になったガードも、ゲートより前なら違反。ゲートも
        ``dependencies=`` でガードより前に置いたルートは適合。"""

        dummy_app = FastAPI()

        @dummy_app.post(
            "/dummy-decorator-guard", dependencies=[Depends(RateLimitGuard("signup"))]
        )
        async def _dummy_decorator_guard(
            body: _DummySignupBody,
            _json_only: None = Depends(require_json_body),
        ) -> dict:
            return {"ok": True}

        @dummy_app.post("/dummy-nested-guard")
        async def _dummy_nested_guard(
            body: _DummySignupBody,
            _wrapped: None = Depends(_dependency_wrapping_a_guard),
            _json_only: None = Depends(require_json_body),
        ) -> dict:
            return {"ok": True}

        @dummy_app.post(
            "/dummy-decorator-gate-first",
            dependencies=[Depends(require_json_body), Depends(RateLimitGuard("signup"))],
        )
        async def _dummy_decorator_gate_first(body: _DummySignupBody) -> dict:
            return {"ok": True}

        violations, checked_routes, _auth_checked_paths = find_json_gate_violations(dummy_app)
        assert any("/dummy-decorator-guard" in v for v in violations)
        assert any("/dummy-nested-guard" in v for v in violations)
        assert ("POST", "/dummy-decorator-gate-first") in checked_routes
        assert not any("/dummy-decorator-gate-first" in v for v in violations)
