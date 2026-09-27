"""書き込み系ルートの認証・レート制限を構造的に検査する回帰テスト。

2026-09-27 に撤去した旧 AssetWise の査定 API（``POST /api/v1/estimate`` /
``POST /api/v1/assessments/{id}/defects``）は、認証もレート制限も無い書き込み口の
まま本番に残っていた。web からの呼び出し元も本番利用も無かったが、第三者が自由に
叩ける INSERT 経路が長期間存在していたこと自体が問題であり、削除して終わりにすると
将来また同じ型の穴（認証もレート制限も持たない書き込みエンドポイント）を作り込んで
しまいかねない。

そこで、アプリに登録された全ルートのうち書き込み系（POST/PUT/PATCH/DELETE）を対象に、
それぞれが以下のいずれかを満たすことを機械的に検査する:

1. ``app.api.deps`` の必須認証依存（``get_optional_*`` を除く）を持つ
2. ``app.api.rate_limit_deps.RateLimitGuard`` への依存を持つ

どちらも満たさないルートは、理由付きの許可リスト（``_ALLOWLIST``）に明示的に
登録されていない限り失敗させる。許可リストは陳腐化を検知するため、実在しない
エントリや、実際には保護が付いたエントリも失敗にする。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.api import deps
from app.api.rate_limit_deps import RateLimitGuard
from app.config import Settings
from app.main import create_app

_STRONG_JWT_SECRET = "a" * 64  # test_main.py と同じダミー強鍵（長さのみ検証対象）。

#: 必須認証の依存関数（関数オブジェクトの同一性で判定する。名前の文字列比較はしない）。
#: 任意認証（トークンが無くても None を返して通す）の get_optional_user /
#: get_optional_operator は「未ログインでも通る」経路のため、意図的に含めない。
_REQUIRED_AUTH_DEPENDENCY_FUNCS: frozenset[Any] = frozenset(
    {
        deps.get_current_user_claims,
        deps.get_current_user,
        deps.get_current_admin,
        deps.get_ops_or_admin,
        deps.get_current_operator,
        deps.get_verified_operator,
        deps.get_current_actor,
        deps.get_case_viewer_actor,
    }
)

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: 保護（必須認証 / RateLimitGuard）が無いことを理由付きで許容するルート。
#: ここに載っていて、かつ実際に保護が付いていないルートだけが検査を通過する。
#: 許可リストの陳腐化（実在しないエントリ・既に保護が付いたエントリ）も検出する。
_ALLOWLIST: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/operator-applications"): (
        "app/api/v1/endpoints/operator_applications.py の create_operator_application が、"
        "operator_applications テーブルの直近1時間・同一IPの件数を DB で数える独自のレート"
        "制限（_RATE_LIMIT_MAX_PER_IP_PER_WINDOW）を持つ。/business フォームからの公開申込"
        "口のため認証は要求しない。"
    ),
}


def _iter_dependant_nodes(dependant: Dependant) -> Iterator[Dependant]:
    """dependant 木を自身から再帰的に辿る（本体・サブ依存・入れ子のサブ依存すべて）。"""
    yield dependant
    for sub_dependant in dependant.dependencies:
        yield from _iter_dependant_nodes(sub_dependant)


def _protection_reasons(route: APIRoute) -> set[str]:
    """ルートが持つ保護の種類（"auth" / "rate_limit"）を集める。

    ``Dependant.call`` は ``Depends(...)`` に渡した callable そのもの
    （``app.dependency_overrides`` が識別に使うのと同じ属性）。名前の文字列では
    比較せず、関数オブジェクト／インスタンスの同一性・型で判定する。
    """
    reasons: set[str] = set()
    for node in _iter_dependant_nodes(route.dependant):
        call = node.call
        if call in _REQUIRED_AUTH_DEPENDENCY_FUNCS:
            reasons.add("auth")
        if isinstance(call, RateLimitGuard):
            reasons.add("rate_limit")
    return reasons


def _is_protected(route: APIRoute) -> bool:
    return bool(_protection_reasons(route))


def _mutating_routes(app: FastAPI) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.methods and route.methods & _MUTATING_METHODS
    ]


def _find_route(app: FastAPI, method: str, path: str) -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    raise AssertionError(f"ルートが見つかりません: {method} {path}")


def _production_app() -> FastAPI:
    """本番相当設定（tests/test_main.py の test_production_with_strong_secret_succeeds と同一）。"""
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        jwt_secret=_STRONG_JWT_SECRET,
        ALLOWED_ORIGINS="https://sokuri.vercel.app",
    )
    return create_app(settings)


# ──────────────────────────── 本検査（全書き込みルート） ────────────────────────────


def test_all_mutating_routes_require_auth_or_rate_limit_or_are_allowlisted() -> None:
    """POST/PUT/PATCH/DELETE の全ルートが、必須認証・RateLimitGuard・許可リストのいずれかを持つ。"""
    app = _production_app()
    routes = _mutating_routes(app)
    assert routes, "検査対象の書き込みルートが1件も見つからない（アプリの組み立てを確認）。"

    matched_allowlist_keys: set[tuple[str, str]] = set()
    violations: list[str] = []

    for route in routes:
        protected = _is_protected(route)
        for method in sorted(route.methods & _MUTATING_METHODS):
            key = (method, route.path)
            if key in _ALLOWLIST:
                matched_allowlist_keys.add(key)
                if protected:
                    violations.append(
                        f"{method} {route.path}: 許可リストに理由が登録されていますが、"
                        "実際には認証 or RateLimitGuard による保護が付いています。"
                        "許可リストが陳腐化しているため _ALLOWLIST から削除してください。"
                    )
                continue
            if not protected:
                violations.append(
                    f"{method} {route.path}: 認証（app.api.deps の必須認証依存）も "
                    "app.api.rate_limit_deps.RateLimitGuard への依存もありません。"
                    "Depends(get_current_user) 等を追加するか RateLimitGuard(scope) を"
                    "付けてください。やむを得ない場合のみ理由付きで _ALLOWLIST に登録すること。"
                )

    stale_allowlist_keys = set(_ALLOWLIST) - matched_allowlist_keys
    for method, path in sorted(stale_allowlist_keys):
        violations.append(
            f"{method} {path}: _ALLOWLIST に登録されていますが、アプリに実在するルートに"
            "一致しませんでした。許可リストが陳腐化しています（パス修正 or 削除してください）。"
        )

    assert not violations, "認証・回数制限の無い書き込みルートを検出しました:\n- " + "\n- ".join(
        violations
    )


# ──────────────────────── 自己検査: 陽性対照（本物のアプリ） ────────────────────────


def test_self_check_real_app_case_create_is_detected_as_authenticated() -> None:
    """本物のアプリで POST /api/v1/cases が「認証あり」と判定される（陽性対照）。"""
    route = _find_route(_production_app(), "POST", "/api/v1/cases")
    assert "auth" in _protection_reasons(route)


def test_self_check_real_app_auth_login_is_detected_as_rate_limited() -> None:
    """本物のアプリで POST /api/v1/auth/login が「RateLimitGuard あり」と判定される
    （陽性対照。ログイン自体は認証前のエンドポイントのため auth 判定は付かない）。"""
    reasons = _protection_reasons(_find_route(_production_app(), "POST", "/api/v1/auth/login"))
    assert "rate_limit" in reasons
    assert "auth" not in reasons


# ──────────────────────── 自己検査: 陰性対照（小さな自作アプリ） ────────────────────────


def test_self_check_dependency_free_post_is_a_violation() -> None:
    """依存なしの POST は保護なし（違反）と判定される。"""
    app = FastAPI()

    @app.post("/mutate")
    async def mutate() -> dict[str, bool]:  # pragma: no cover - 呼び出さない
        return {"ok": True}

    assert not _is_protected(_find_route(app, "POST", "/mutate"))


def test_self_check_nested_required_auth_dependency_is_detected() -> None:
    """別の依存関数の中で Depends(get_current_user) している（入れ子の）POST は
    「認証あり」と判定される。"""

    async def _wraps_required_auth(user: Any = Depends(deps.get_current_user)) -> Any:
        return user

    app = FastAPI()

    @app.post("/mutate")
    async def mutate(  # pragma: no cover - 呼び出さない
        user: Any = Depends(_wraps_required_auth),
    ) -> dict[str, bool]:
        return {"ok": True}

    assert _protection_reasons(_find_route(app, "POST", "/mutate")) == {"auth"}


def test_self_check_rate_limit_guard_dependency_is_detected() -> None:
    """Depends(RateLimitGuard("login")) を持つ POST は「RateLimitGuard あり」と判定される。"""
    app = FastAPI()

    @app.post("/mutate")
    async def mutate(  # pragma: no cover - 呼び出さない
        _rl: Any = Depends(RateLimitGuard("login")),
    ) -> dict[str, bool]:
        return {"ok": True}

    assert _protection_reasons(_find_route(app, "POST", "/mutate")) == {"rate_limit"}


def test_self_check_optional_auth_only_is_a_violation() -> None:
    """get_optional_user だけの POST は「保護なし」（違反）と判定される
    （任意認証は「未ログインでも通る」経路のため必須認証として数えない）。"""
    app = FastAPI()

    @app.post("/mutate")
    async def mutate(  # pragma: no cover - 呼び出さない
        user: Any = Depends(deps.get_optional_user),
    ) -> dict[str, bool]:
        return {"ok": True}

    assert not _is_protected(_find_route(app, "POST", "/mutate"))
