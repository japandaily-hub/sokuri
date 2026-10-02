"""クロスサイト要求ゲート（``app.api.cross_site_deps.reject_cross_site_browser_request``）の
単体・統合・構造検査テスト。

構成:
    (a) 判定（``_rejection_reason``）と依存そのものの単体テスト。ブラウザが実際に付ける
        ヘッダの組み合わせ（正規の web・同一オリジン・アドレスバー・SSR/スクリプト・
        旧ブラウザ・第三者ページの img/script/iframe/fetch）ごとに、通すか拒否するか。
    (b) 拒否時の WARNING ログが理由ごとにスロットリングされ、形式の正しいオリジン以外の
        生の値を含まないこと。
    (c) 実ルート（GET /vendors・GET /vendors/{operator_id}）で、第三者のページが送らせた
        要求がレート制限を1件も消費せずに 403 になり、上限を超えて送らせても同じ IP の
        正規の要求は 429 にならないこと（陽性対照で IP 軸が生きていることも確認する）。
    (d) 許可オリジンの正本（``get_settings().allowed_origins``）が ``CORSMiddleware`` の
        許可リストと一致し、CORS に別の許可経路（正規表現等）が無いこと。
    (e) 「IP 軸で全件カウントする GET・HEAD 専用のルートは、このゲートをガードより前に
        置く」という配置規約（``app.api.cross_site_deps`` モジュール docstring 参照）を、
        実アプリの全ルートに対して静的に検証する（CI での付け忘れ防止）。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable, Iterator

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import cross_site_deps
from app.api.cross_site_deps import (
    REASON_CROSS_SITE_WITHOUT_ORIGIN,
    REASON_DUPLICATE_HEADER,
    REASON_ORIGIN_NOT_ALLOWED,
    _rejection_reason,
    reject_cross_site_browser_request,
)
from app.api.rate_limit_deps import RateLimitGuard, _scope_spec, get_rate_limiter
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
)
from app.db.session import get_session
from app.main import create_app
from tests.effective_routes import effective_api_routes
from tests.test_json_body_guard import (
    _BODYLESS_METHODS,
    _STRUCTURAL_CHECK_CONFIG,
    _dependency_execution_order,
    _has_request_parameters,
)

_FORBIDDEN_DETAIL = "他のサイトから送られたリクエストは受け付けていません。"

#: 統合・依存の単体テストで許可オリジンとして差し込む値（本番の https://sokuri.vercel.app に相当）。
_WEB_ORIGIN = "https://web.example"
_FOREIGN_ORIGIN = "https://evil.example"

# ASGITransport 経由では request.client.host が常にループバックになり IP 軸がスキップ
# されるため、XFF で公開 IP を1段だけ付ける（テスト環境の TRUSTED_PROXY_HOPS は既定 1。
# tests/test_json_body_guard.py の _XFF_HEADERS と同じ理由）。
_XFF_HEADERS = {"X-Forwarded-For": "198.51.100.201"}

_UNKNOWN_OPERATOR_ID = "123e4567-e89b-12d3-a456-426614174000"

#: 実ルートと、ゲートとガードを通過したときのステータス（業者0件の一覧は 200、
#: 存在しない業者のプロフィールは 404。どちらもガードが数えた後に返る）。
_PUBLIC_READ_ENDPOINTS = [
    pytest.param("/api/v1/vendors", 200, id="list_vendors"),
    pytest.param(f"/api/v1/vendors/{_UNKNOWN_OPERATOR_ID}", 404, id="vendor_profile"),
]

# ── ブラウザが実際に付けるヘッダ（Chrome 系の値。判定に使うのは Origin と Sec-Fetch-Site だけ）──

#: 正規の web の業者一覧・プロフィール取得。web の request()（web/src/lib/katadzuke-api.ts）は
#: GET でも Content-Type: application/json を付けるため、ブラウザはプリフライトを経てから
#: CORS モードで送り、クロスオリジンなので必ず Origin が付く。
_LEGIT_WEB_FETCH = {
    "Origin": _WEB_ORIGIN,
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Content-Type": "application/json",
}
#: backend 自身のページ（/docs 等）からの同一オリジンの fetch（GET には Origin が付かない）。
_SAME_ORIGIN_FETCH = {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
#: アドレスバーへの直接入力・ブックマーク。
_ADDRESS_BAR = {
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
}
#: SSR・スクリプト・監視（ブラウザ固有のヘッダを付けない）。
_NO_BROWSER_HEADERS: dict[str, str] = {}

#: 第三者のページが訪問者のブラウザから送らせる要求（すべて拒否・数えない）。
_THIRD_PARTY_REQUESTS = [
    pytest.param(
        {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"},
        id="img",
    ),
    pytest.param(
        {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "script"},
        id="script",
    ),
    pytest.param(
        {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "empty"},
        id="fetch_no_cors",
    ),
    pytest.param(
        {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe"},
        id="iframe",
    ),
    pytest.param(
        {
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-User": "?1",
        },
        id="top_level_link",
    ),
    pytest.param(
        {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"},
        id="same_site_img",
    ),
    pytest.param(
        {
            "Origin": _FOREIGN_ORIGIN,
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
        id="cors_simple_get_from_foreign_origin",
    ),
    pytest.param(
        {
            "Origin": "null",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
        id="sandboxed_iframe_null_origin",
    ),
    # Fetch Metadata 非対応の旧ブラウザでも、CORS モードの要求には Origin が付く。
    pytest.param({"Origin": _FOREIGN_ORIGIN}, id="legacy_browser_cors_from_foreign_origin"),
]


def _config(*, enabled: bool = True) -> RateLimitConfig:
    """public_read の IP 軸を 2 回/60 秒に絞ったテスト専用設定（陽性対照の3回目で 429）。"""
    return RateLimitConfig(
        enabled=enabled,
        login_account=RateLimitRule(5, 900),
        login_ip=RateLimitRule(20, 900),
        sensitive_account=RateLimitRule(5, 900),
        signup_ip=RateLimitRule(2, 3600),
        line_ip=RateLimitRule(2, 900),
        max_keys=10000,
        case_create_ip=RateLimitRule(2, 3600),
        case_create_account=RateLimitRule(10, 3600),
        public_read_ip=RateLimitRule(2, 60),
    )


def _build_test_app(
    session: AsyncSession, store: InMemoryRateLimitStore, *, rate_limit_enabled: bool = True
) -> FastAPI:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    limiter = RateLimiter(config=_config(enabled=rate_limit_enabled), store=store)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture
def store() -> InMemoryRateLimitStore:
    """``len(store)`` でカウント済みキー数を確認するため、テストで参照を保持する。"""
    return InMemoryRateLimitStore()


@pytest.fixture
def allowed_web_origin(monkeypatch: pytest.MonkeyPatch) -> str:
    """ゲートが読む許可オリジンを ``_WEB_ORIGIN`` だけにする（実行環境の ALLOWED_ORIGINS に
    依存させない。ガード側の get_settings は差し替えない）。"""
    monkeypatch.setattr(
        cross_site_deps, "get_settings", lambda: SimpleNamespace(allowed_origins=[_WEB_ORIGIN])
    )
    return _WEB_ORIGIN


@pytest.fixture
async def client(
    db_session: AsyncSession, store: InMemoryRateLimitStore, allowed_web_origin: str
) -> AsyncIterator[AsyncClient]:
    test_app = _build_test_app(db_session, store)
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers=_XFF_HEADERS,
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_cross_site_log_throttles() -> Iterator[None]:
    """拒否ログのスロットル状態（理由ごとに3つ）をテスト前後で初期化する。"""
    throttles = (
        cross_site_deps._duplicate_header_reject_throttle,
        cross_site_deps._origin_reject_throttle,
        cross_site_deps._cross_site_reject_throttle,
    )
    for throttle in throttles:
        throttle.reset()
    yield
    for throttle in throttles:
        throttle.reset()


def _make_request(headers: list[tuple[str, str]], path: str = "/api/v1/dummy") -> Request:
    """``reject_cross_site_browser_request`` を HTTP なしで直接 await するための最小 ASGI scope
    （同名のヘッダを複数行にできるよう、タプルのリストで受け取る）。"""
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "scheme": "https",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    return Request(scope)


# ──────────────────────────── (a) 判定と依存の単体 ────────────────────────────


class TestRejectionReason:
    @pytest.mark.parametrize(
        ("origins", "sites"),
        [
            pytest.param([_WEB_ORIGIN], ["cross-site"], id="web_cross_site_cors"),
            pytest.param([_WEB_ORIGIN], ["same-site"], id="web_same_site_cors_local_dev"),
            pytest.param([_WEB_ORIGIN], [], id="web_from_legacy_browser"),
            pytest.param([], ["same-origin"], id="same_origin_get"),
            # 同一オリジンの POST（/docs 等）は backend 自身の Origin を付けるが、許可リストに無くても通す。
            pytest.param(["https://api.example"], ["same-origin"], id="same_origin_post"),
            pytest.param([], ["none"], id="address_bar"),
            pytest.param([], [], id="ssr_script_or_legacy_browser"),
        ],
    )
    def test_allows(self, origins: list[str], sites: list[str]) -> None:
        assert _rejection_reason(origins, sites, [_WEB_ORIGIN]) is None

    @pytest.mark.parametrize(
        ("origins", "sites", "expected"),
        [
            pytest.param([], ["cross-site"], REASON_CROSS_SITE_WITHOUT_ORIGIN, id="cross_site_no_origin"),
            pytest.param([], ["same-site"], REASON_CROSS_SITE_WITHOUT_ORIGIN, id="same_site_no_origin"),
            # 仕様の値は小文字のトークンだけ。未知の値・空文字は通さない。
            pytest.param([], ["Cross-Site"], REASON_CROSS_SITE_WITHOUT_ORIGIN, id="unknown_case"),
            pytest.param([], ["bogus"], REASON_CROSS_SITE_WITHOUT_ORIGIN, id="unknown_value"),
            pytest.param([], [""], REASON_CROSS_SITE_WITHOUT_ORIGIN, id="empty_site"),
            pytest.param([_FOREIGN_ORIGIN], ["cross-site"], REASON_ORIGIN_NOT_ALLOWED, id="foreign"),
            pytest.param([_FOREIGN_ORIGIN], [], REASON_ORIGIN_NOT_ALLOWED, id="foreign_legacy"),
            pytest.param([_FOREIGN_ORIGIN], ["none"], REASON_ORIGIN_NOT_ALLOWED, id="foreign_none"),
            pytest.param(["null"], ["cross-site"], REASON_ORIGIN_NOT_ALLOWED, id="null"),
            pytest.param([""], [], REASON_ORIGIN_NOT_ALLOWED, id="empty_origin"),
            # CORS と同じく完全一致（末尾スラッシュ・大文字・別ポートは別のオリジン）。
            pytest.param([_WEB_ORIGIN + "/"], ["cross-site"], REASON_ORIGIN_NOT_ALLOWED, id="slash"),
            pytest.param(["HTTPS://WEB.EXAMPLE"], ["cross-site"], REASON_ORIGIN_NOT_ALLOWED, id="case"),
            pytest.param([_WEB_ORIGIN + ":8443"], ["cross-site"], REASON_ORIGIN_NOT_ALLOWED, id="port"),
            pytest.param(
                [_WEB_ORIGIN, _FOREIGN_ORIGIN], ["cross-site"], REASON_DUPLICATE_HEADER, id="two_origins"
            ),
            pytest.param(
                [_WEB_ORIGIN, _WEB_ORIGIN], ["cross-site"], REASON_DUPLICATE_HEADER, id="same_origin_twice"
            ),
            pytest.param(
                [], ["same-origin", "cross-site"], REASON_DUPLICATE_HEADER, id="two_sites"
            ),
            pytest.param([], ["none", "none"], REASON_DUPLICATE_HEADER, id="same_site_value_twice"),
        ],
    )
    def test_rejects(self, origins: list[str], sites: list[str], expected: str) -> None:
        assert _rejection_reason(origins, sites, [_WEB_ORIGIN]) == expected

    def test_null_is_rejected_even_if_the_allowlist_contains_it(self) -> None:
        """null は設定の段階で許可リストから除外されるが、判定でも独立に拒否する。"""
        assert _rejection_reason(["null"], [], ["null"]) == REASON_ORIGIN_NOT_ALLOWED
        assert _rejection_reason(["NULL"], [], ["NULL"]) == REASON_ORIGIN_NOT_ALLOWED


class TestRejectCrossSiteBrowserRequestUnit:
    async def test_reads_every_header_line_not_just_the_first(
        self, allowed_web_origin: str
    ) -> None:
        """複数行の Origin は先頭が許可オリジンでも拒否する（getlist で全行を読む）。"""
        request = _make_request([("Origin", allowed_web_origin), ("Origin", _FOREIGN_ORIGIN)])
        with pytest.raises(HTTPException) as exc_info:
            await reject_cross_site_browser_request(request)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == _FORBIDDEN_DETAIL

    async def test_passes_allowed_origin_and_rejects_foreign_origin(
        self, allowed_web_origin: str
    ) -> None:
        await reject_cross_site_browser_request(
            _make_request([("Origin", allowed_web_origin), ("Sec-Fetch-Site", "cross-site")])
        )
        with pytest.raises(HTTPException) as exc_info:
            await reject_cross_site_browser_request(
                _make_request([("Origin", _FOREIGN_ORIGIN), ("Sec-Fetch-Site", "cross-site")])
            )
        assert exc_info.value.status_code == 403

    async def test_every_configured_allowed_origin_passes_with_real_settings(self) -> None:
        """差し替えなしの実設定で、許可オリジンのどれから来た CORS 要求も通る。"""
        origins = get_settings().allowed_origins
        assert origins, "許可オリジンが空だと、このテストは何も確かめていない"
        for origin in origins:
            await reject_cross_site_browser_request(
                _make_request(
                    [
                        ("Origin", origin),
                        ("Sec-Fetch-Site", "cross-site"),
                        ("Sec-Fetch-Mode", "cors"),
                    ]
                )
            )


# ──────────────────────────── (b) 拒否時ログ ────────────────────────────


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.api.cross_site_deps"]


class TestRejectionLogging:
    async def test_origin_rejection_logs_well_formed_origin_once_per_window(
        self, caplog: pytest.LogCaptureFixture, allowed_web_origin: str
    ) -> None:
        """形式の正しいオリジンはそのまま出す（ALLOWED_ORIGINS の設定漏れの特定に使う）。"""
        request = _make_request(
            [("Origin", "https://katazuke-new.example"), ("Sec-Fetch-Site", "cross-site")],
            path="/api/v1/vendors",
        )
        with caplog.at_level(logging.WARNING, logger="app.api.cross_site_deps"):
            for _ in range(2):  # スロットル窓内（既定60秒）の2回目は出ない。
                with pytest.raises(HTTPException):
                    await reject_cross_site_browser_request(request)

        records = _records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert "origin=https://katazuke-new.example" in message
        assert "sec_fetch_site=cross-site" in message
        assert "path=/api/v1/vendors" in message

    @pytest.mark.parametrize(
        "raw_origin",
        [
            "https://evil.example/path-marker-123",
            "javascript:alert(1)//marker-123",
            "https://evil.example?marker-123",
            "https://" + "a" * 400 + ".example",
        ],
        ids=["with_path", "javascript_scheme", "with_query", "too_long"],
    )
    async def test_malformed_origin_is_not_logged_raw(
        self, caplog: pytest.LogCaptureFixture, allowed_web_origin: str, raw_origin: str
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="app.api.cross_site_deps"):
            with pytest.raises(HTTPException):
                await reject_cross_site_browser_request(_make_request([("Origin", raw_origin)]))

        records = _records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert "origin=invalid" in message
        assert "marker-123" not in message
        assert "a" * 100 not in message

    async def test_cross_site_rejection_logs_only_known_fetch_metadata_values(
        self, caplog: pytest.LogCaptureFixture, allowed_web_origin: str
    ) -> None:
        request = _make_request(
            [
                ("Sec-Fetch-Site", "cross-site"),
                ("Sec-Fetch-Mode", "no-cors"),
                ("Sec-Fetch-Dest", "x-marker-dest-123"),
            ],
            path=f"/api/v1/vendors/{_UNKNOWN_OPERATOR_ID}",
        )
        request.scope["route"] = SimpleNamespace(path="/api/v1/vendors/{operator_id}")
        with caplog.at_level(logging.WARNING, logger="app.api.cross_site_deps"):
            with pytest.raises(HTTPException):
                await reject_cross_site_browser_request(request)

        records = _records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert "sec_fetch_site=cross-site" in message
        assert "sec_fetch_mode=no-cors" in message
        assert "sec_fetch_dest=other" in message
        assert "marker-dest-123" not in message
        # 実際のパス（ID を含む）ではなくルートのテンプレートを出す。
        assert "path=/api/v1/vendors/{operator_id}" in message
        assert _UNKNOWN_OPERATOR_ID not in message

    async def test_throttles_are_independent_per_reason(
        self, caplog: pytest.LogCaptureFixture, allowed_web_origin: str
    ) -> None:
        """継続中の攻撃（Origin なしのクロスサイト）のログが、許可オリジン外の Origin
        （設定漏れの兆候）や重複行のログを抑え込まない。"""
        with caplog.at_level(logging.WARNING, logger="app.api.cross_site_deps"):
            for headers in (
                [("Sec-Fetch-Site", "cross-site")],
                [("Sec-Fetch-Site", "cross-site")],
                [("Origin", _FOREIGN_ORIGIN)],
                [("Origin", _FOREIGN_ORIGIN), ("Origin", _FOREIGN_ORIGIN)],
            ):
                with pytest.raises(HTTPException):
                    await reject_cross_site_browser_request(_make_request(headers))

        messages = [r.getMessage() for r in _records(caplog)]
        assert len(messages) == 3
        assert any("Origin の無い要求" in m for m in messages)
        assert any("許可オリジン以外" in m for m in messages)
        assert any("複数行" in m and "origin_lines=2" in m for m in messages)

    async def test_allowed_requests_do_not_log(
        self, caplog: pytest.LogCaptureFixture, allowed_web_origin: str
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="app.api.cross_site_deps"):
            await reject_cross_site_browser_request(
                _make_request([("Origin", allowed_web_origin), ("Sec-Fetch-Site", "cross-site")])
            )
            await reject_cross_site_browser_request(_make_request([]))
        assert _records(caplog) == []


# ──────────────────────────── (c) 実ルート: 数える前に 403 ────────────────────────────


class TestPublicReadRoutes:
    @pytest.mark.parametrize("third_party_headers", _THIRD_PARTY_REQUESTS)
    @pytest.mark.parametrize(("path", "_passed_status"), _PUBLIC_READ_ENDPOINTS)
    async def test_third_party_request_rejected_before_counting(
        self,
        client: AsyncClient,
        store: InMemoryRateLimitStore,
        path: str,
        _passed_status: int,
        third_party_headers: dict[str, str],
    ) -> None:
        for _ in range(3):  # 上限（2）を超えて送っても数えない。
            response = await client.get(path, headers=third_party_headers)
            assert response.status_code == 403, response.text
            assert response.json() == {"detail": _FORBIDDEN_DETAIL}
        assert len(store) == 0

    @pytest.mark.parametrize(("path", "passed_status"), _PUBLIC_READ_ENDPOINTS)
    async def test_flood_from_third_party_page_does_not_block_legit_web_on_same_ip(
        self,
        client: AsyncClient,
        store: InMemoryRateLimitStore,
        path: str,
        passed_status: int,
    ) -> None:
        """本題: 第三者のページが同じ IP から上限の何倍も送らせた後でも、正規の web の要求は
        429 にならない。末尾の陽性対照で、正規の要求は数えられ上限で 429 になることを
        確かめる（ゲートがガードごと素通りさせていないことの確認）。"""
        for param in _THIRD_PARTY_REQUESTS:
            for _ in range(5):
                response = await client.get(path, headers=param.values[0])
                assert response.status_code == 403, response.text
        assert len(store) == 0

        first = await client.get(path, headers=_LEGIT_WEB_FETCH)
        assert first.status_code == passed_status, first.text
        second = await client.get(path, headers=_LEGIT_WEB_FETCH)
        assert second.status_code == passed_status, second.text
        assert len(store) == 1
        third = await client.get(path, headers=_LEGIT_WEB_FETCH)
        assert third.status_code == 429, third.text

    @pytest.mark.parametrize(
        "allowed_headers",
        [
            pytest.param(_LEGIT_WEB_FETCH, id="legit_web_fetch"),
            pytest.param(_SAME_ORIGIN_FETCH, id="same_origin_fetch"),
            pytest.param(_ADDRESS_BAR, id="address_bar"),
            pytest.param(_NO_BROWSER_HEADERS, id="ssr_or_script"),
        ],
    )
    @pytest.mark.parametrize(("path", "passed_status"), _PUBLIC_READ_ENDPOINTS)
    async def test_allowed_requests_pass_and_are_counted(
        self,
        client: AsyncClient,
        store: InMemoryRateLimitStore,
        path: str,
        passed_status: int,
        allowed_headers: dict[str, str],
    ) -> None:
        response = await client.get(path, headers=allowed_headers)
        assert response.status_code == passed_status, response.text
        assert len(store) == 1

    async def test_gate_still_rejects_when_rate_limiting_is_disabled(
        self, db_session: AsyncSession, allowed_web_origin: str
    ) -> None:
        """緊急停止スイッチ（RATE_LIMIT_ENABLED=false）はゲートを止めない（docstring の運用上の注意）。"""
        store = InMemoryRateLimitStore()
        app = _build_test_app(db_session, store, rate_limit_enabled=False)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=_XFF_HEADERS
        ) as ac:
            rejected = await ac.get(
                "/api/v1/vendors",
                headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"},
            )
            allowed = await ac.get("/api/v1/vendors", headers=_LEGIT_WEB_FETCH)
        assert rejected.status_code == 403, rejected.text
        assert allowed.status_code == 200, allowed.text


# ──────────────────────────── (d) CORS との一致 ────────────────────────────


class TestAllowedOriginsMatchCors:
    def test_gate_source_equals_cors_allow_origins_without_other_paths(self) -> None:
        """ゲートの許可オリジン（get_settings().allowed_origins）と CORSMiddleware の許可
        リストが同一で、CORS に正規表現・全許可の経路が無いこと。CORS に別の許可経路を
        足したら、このゲートも同じ判定に揃えること（cross_site_deps の docstring 参照）。"""
        app = create_app()
        cors_middlewares = [m for m in app.user_middleware if m.cls is CORSMiddleware]
        assert len(cors_middlewares) == 1
        kwargs = cors_middlewares[0].kwargs
        assert kwargs.get("allow_origin_regex") is None
        assert "*" not in kwargs["allow_origins"]
        assert list(kwargs["allow_origins"]) == get_settings().allowed_origins


# ──────────────────────────── (e) 配置規約の構造検査（CI での付け忘れ防止） ────────────────────────────


#: 空振り防止: この2本が必ず検査対象（GET・IP 軸・全件カウント）に入ること。
_EXPECTED_GATED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/vendors"),
        ("GET", "/api/v1/vendors/{operator_id}"),
    }
)


def find_cross_site_gate_violations(
    app: FastAPI, *, gate: Callable[..., Any] = reject_cross_site_browser_request
) -> tuple[list[str], set[tuple[str, str]]]:
    """クロスサイト要求ゲートの配置規約（``app.api.cross_site_deps`` docstring 参照）を
    実アプリの全ルートに対して機械的に検査する。

    対象は、GET・HEAD だけを受けるルートのうち、全リクエストを IP 軸でカウントする
    スコープ（``_scope_spec(...).ip_rule is not None and count_all``）のガードを持つもの。
    この条件は ``RateLimitGuard`` の scope 定義から機械的に決まるため、新しいスコープや
    GET のルートを追加した際の付け忘れもここで検知できる。GET・HEAD 以外のメソッドを
    受けるルートは JSON 必須ゲートの構造検査（``tests/test_json_body_guard.py``）の対象。
    ゲート（``gate``。自己検査で差し替えるための引数）は、ガードより前にあり、
    リクエスト由来の引数を持たないこと。

    Returns:
        ``(violations, checked_routes)``。``violations`` が空なら規約に適合している。
        ``checked_routes`` は検査対象になった ``(method, path)`` の集合（空振り防止の
        検証に使う）。
    """
    violations: list[str] = []
    checked_routes: set[tuple[str, str]] = set()
    gate_name = getattr(gate, "__name__", repr(gate))

    for route in effective_api_routes(app):
        methods = set(route.methods or ())
        if not methods or not methods <= _BODYLESS_METHODS:
            continue
        order = _dependency_execution_order(route.dependant)
        for guard_index, dep in enumerate(order):
            if not isinstance(dep.call, RateLimitGuard):
                continue
            guard = dep.call
            spec = _scope_spec(guard._scope, _STRUCTURAL_CHECK_CONFIG)
            if not (spec.ip_rule is not None and spec.count_all):
                continue
            for method in sorted(methods):
                checked_routes.add((method, route.path))

            gate_indexes = [i for i, d in enumerate(order) if d.call is gate]
            if not gate_indexes or gate_indexes[0] > guard_index:
                violations.append(
                    f"{route.path}: {gate_name} が RateLimitGuard"
                    f"（scope={guard._scope!r}）より前にありません。"
                )
            elif _has_request_parameters(order[gate_indexes[0]]):
                # 引数の検証に失敗した依存は呼ばれずに飛ばされ、後続のガードは数える
                # （fastapi.dependencies.utils.solve_dependencies）。順序が正しくても素通りになる。
                violations.append(
                    f"{route.path}: {gate_name} が Request 以外の引数を持っています"
                    "（検証エラーの要求ではゲートが飛ばされ、ガードが数えます）。"
                )

    return violations, checked_routes


async def _gate_with_header_parameter(origin: str = Header()) -> None:
    """自己検査用: 引数の検証を持つ（＝検証エラーの要求では飛ばされる）ゲートの悪い例。"""


async def _dependency_wrapping_a_public_read_guard(
    _rl: object = Depends(RateLimitGuard("public_read")),
) -> None:
    """自己検査用: 別の依存の内側に入れ子になったガード。"""


class TestCrossSiteGatePlacementConvention:
    def test_real_app_has_no_violations_and_covers_expected_routes(self) -> None:
        app = create_app()
        violations, checked_routes = find_cross_site_gate_violations(app)
        assert violations == []
        # 空振り防止: 検査対象に上記2本が含まれること（今後の追加も検知できるよう部分集合で確認）。
        assert _EXPECTED_GATED_ROUTES <= checked_routes

    def test_detects_missing_gate_and_guard_declared_before_the_gate(self) -> None:
        """自己検査: ゲートの無いルートと、ガードをゲートより前に宣言したルートは違反。"""

        dummy_app = FastAPI()

        @dummy_app.get("/dummy-no-gate")
        async def _dummy_no_gate(_rl: object = Depends(RateLimitGuard("public_read"))) -> dict:
            return {"ok": True}

        @dummy_app.get("/dummy-wrong-order")
        async def _dummy_wrong_order(
            _rl: object = Depends(RateLimitGuard("public_read")),
            _no_cross_site: None = Depends(reject_cross_site_browser_request),
        ) -> dict:
            return {"ok": True}

        @dummy_app.get("/dummy-right-order")
        async def _dummy_right_order(
            _no_cross_site: None = Depends(reject_cross_site_browser_request),
            _rl: object = Depends(RateLimitGuard("public_read")),
        ) -> dict:
            return {"ok": True}

        violations, checked_routes = find_cross_site_gate_violations(dummy_app)
        assert any("/dummy-no-gate" in v for v in violations)
        assert any("/dummy-wrong-order" in v for v in violations)
        assert ("GET", "/dummy-right-order") in checked_routes
        assert not any("/dummy-right-order" in v for v in violations)

    def test_detects_gate_with_request_parameters(self) -> None:
        """自己検査: ゲートがヘッダ等の引数を持つと、検証エラーの要求ではゲートが飛ばされて
        ガードが数えるため、順序が正しくても違反として報告される。"""

        dummy_app = FastAPI()

        @dummy_app.get("/dummy-gate-with-header")
        async def _dummy_endpoint(
            _no_cross_site: None = Depends(_gate_with_header_parameter),
            _rl: object = Depends(RateLimitGuard("public_read")),
        ) -> dict:
            return {"ok": True}

        violations, _checked_routes = find_cross_site_gate_violations(
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

        @dummy_app.get(
            "/dummy-decorator-guard", dependencies=[Depends(RateLimitGuard("public_read"))]
        )
        async def _dummy_decorator_guard(
            _no_cross_site: None = Depends(reject_cross_site_browser_request),
        ) -> dict:
            return {"ok": True}

        @dummy_app.get("/dummy-nested-guard")
        async def _dummy_nested_guard(
            _wrapped: None = Depends(_dependency_wrapping_a_public_read_guard),
            _no_cross_site: None = Depends(reject_cross_site_browser_request),
        ) -> dict:
            return {"ok": True}

        @dummy_app.get(
            "/dummy-decorator-gate-first",
            dependencies=[
                Depends(reject_cross_site_browser_request),
                Depends(RateLimitGuard("public_read")),
            ],
        )
        async def _dummy_decorator_gate_first() -> dict:
            return {"ok": True}

        violations, checked_routes = find_cross_site_gate_violations(dummy_app)
        assert any("/dummy-decorator-guard" in v for v in violations)
        assert any("/dummy-nested-guard" in v for v in violations)
        assert ("GET", "/dummy-decorator-gate-first") in checked_routes
        assert not any("/dummy-decorator-gate-first" in v for v in violations)

    def test_ignores_scopes_that_do_not_count_every_request_on_ip(self) -> None:
        """自己検査: IP 軸を持たないスコープ（アカウント軸だけ）の GET は検査対象外。"""

        dummy_app = FastAPI()

        @dummy_app.get("/dummy-account-axis-only")
        async def _dummy_endpoint(
            _rl: object = Depends(RateLimitGuard("password_change")),
        ) -> dict:
            return {"ok": True}

        violations, checked_routes = find_cross_site_gate_violations(dummy_app)
        assert violations == []
        assert ("GET", "/dummy-account-axis-only") not in checked_routes
