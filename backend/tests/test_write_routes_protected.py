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

from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.api import deps
from app.api.rate_limit_deps import RateLimitGuard, _scope_spec, get_rate_limiter
from app.config import Settings
from app.main import create_app

_STRONG_JWT_SECRET = "a" * 64  # test_main.py と同じダミー強鍵（長さのみ検証対象）。

#: 必須認証の依存関数（関数オブジェクトの同一性で判定する。名前の文字列比較はしない）。
#: app/api/deps.py に新しい必須認証の依存関数を追加したら、ここにも追記すること
#: （追記漏れだと、認証済みのルートが「保護なし」として落ちる）。
#: get_current_user_claims は署名・typ しか見ず、退会・停止・失効を判定しないため含めない。
#: 任意認証（トークンが無くても None を返して通す）の get_optional_user /
#: get_optional_operator は「未ログインでも通る」経路のため、意図的に含めない。
_REQUIRED_AUTH_DEPENDENCY_FUNCS: frozenset[Any] = frozenset(
    {
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
        "口のため認証は要求しない。注意: その IP は X-Forwarded-For の先頭（利用者が書ける値）"
        "から取るため偽装で回避できる。修正（cb98349・IPv6 3段化 1d14e6f）は別ブランチにあり、"
        "main に合流するまで実効性は限定的（この許可リストの完了条件に紐づける）。"
    ),
    ("POST", "/api/v1/auth/login"): (
        "RateLimitGuard('login') は事前の確認だけで数えない（count_all=False）。失敗時の "
        "record_failure をハンドラ内で呼ぶ作り。振る舞いは tests/test_rate_limit_api.py 等で固定。"
    ),
    ("POST", "/api/v1/auth/operator/login"): (
        "同上（業者ログイン。アカウント軸のキーは operator: で名前空間分離）。"
    ),
}


def _iter_dependant_nodes(dependant: Dependant) -> Iterator[Dependant]:
    """dependant 木を自身から再帰的に辿る（本体・サブ依存・入れ子のサブ依存すべて）。"""
    yield dependant
    for sub_dependant in dependant.dependencies:
        yield from _iter_dependant_nodes(sub_dependant)


def _counts_every_request_by_ip(guard: RateLimitGuard) -> bool:
    """ガード単体で全リクエストを IP 軸でカウントするスコープか。

    IP 軸が無いスコープ（password_change 等）や、失敗時だけ数えるスコープ（login。実カウントは
    ハンドラの record_failure）は、ガードを付けただけでは匿名の連投を止めない。それらを流用した
    だけで合格にしないよう、保護として数えない（security review M-1）。
    """
    spec = _scope_spec(guard._scope, get_rate_limiter().config)
    return spec.ip_rule is not None and spec.count_all


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
        if isinstance(call, RateLimitGuard) and _counts_every_request_by_ip(call):
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
    foreign = [
        r for r in app.routes
        if not isinstance(r, APIRoute) and (
            type(r).__name__ in {"Mount", "WebSocketRoute"}
            or (getattr(r, "methods", None) and set(r.methods) & _MUTATING_METHODS)
        )
    ]
    assert not foreign, f"APIRoute 以外の書き込み口（mount 等）は検査できません: {foreign}"

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
                    "Depends(get_current_user) 等を追加するか、IP 軸で全件数える RateLimitGuard"
                    "（signup・contact 等）を付けてください。認証済みなのに落ちる場合は、"
                    "新しい必須認証の依存関数を _REQUIRED_AUTH_DEPENDENCY_FUNCS に追記し忘れて"
                    "いないか確認。やむを得ない場合のみ理由付きで _ALLOWLIST に登録すること。"
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


def test_self_check_real_app_signup_is_detected_as_rate_limited() -> None:
    """本物のアプリで POST /api/v1/auth/signup が「全件数える RateLimitGuard あり」と判定される
    （陽性対照。認証前のエンドポイントのため auth 判定は付かない）。"""
    reasons = _protection_reasons(_find_route(_production_app(), "POST", "/api/v1/auth/signup"))
    assert reasons == {"rate_limit"}


def test_self_check_real_app_login_is_not_counted_by_guard_alone() -> None:
    """login は失敗時にハンドラが数える作りで、ガード単体では保護と数えない（許可リスト側で扱う）。"""
    route = _find_route(_production_app(), "POST", "/api/v1/auth/login")
    assert _protection_reasons(route) == set()


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
    """全件を IP 軸で数えるスコープの RateLimitGuard を持つ POST は保護ありと判定される。"""
    app = FastAPI()

    @app.post("/mutate")
    async def mutate(  # pragma: no cover - 呼び出さない
        _rl: Any = Depends(RateLimitGuard("signup")),
    ) -> dict[str, bool]:
        return {"ok": True}

    assert _protection_reasons(_find_route(app, "POST", "/mutate")) == {"rate_limit"}


def test_self_check_guard_without_ip_counting_is_a_violation() -> None:
    """IP 軸が無い・失敗時しか数えないスコープ（password_change・login）の流用は違反と判定される。"""
    for scope in ("password_change", "login"):
        app = FastAPI()

        @app.post("/mutate")
        async def mutate(  # pragma: no cover - 呼び出さない
            _rl: Any = Depends(RateLimitGuard(scope)),
        ) -> dict[str, bool]:
            return {"ok": True}

        assert not _is_protected(_find_route(app, "POST", "/mutate")), scope


def test_self_check_route_level_and_router_level_dependencies_are_detected() -> None:
    """デコレータの dependencies=[...] と APIRouter(dependencies=[...]) も依存木に入って検出される。"""
    app = FastAPI()

    @app.post("/route-level", dependencies=[Depends(deps.get_current_user)])
    async def route_level() -> dict[str, bool]:  # pragma: no cover - 呼び出さない
        return {"ok": True}

    router = APIRouter(dependencies=[Depends(deps.get_current_admin)])

    @router.post("/router-level")
    async def router_level() -> dict[str, bool]:  # pragma: no cover - 呼び出さない
        return {"ok": True}

    app.include_router(router)
    assert _protection_reasons(_find_route(app, "POST", "/route-level")) == {"auth"}
    assert _protection_reasons(_find_route(app, "POST", "/router-level")) == {"auth"}


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
