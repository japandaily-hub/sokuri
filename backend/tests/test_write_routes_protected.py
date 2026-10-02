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
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi import routing as fastapi_routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute, Route

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


@dataclass(frozen=True)
class _EffectiveApiRoute:
    """include_router の prefix・dependencies を反映した「実際に受け付ける」APIRoute の姿。

    fastapi 0.136 系までは include_router が APIRoute を prefix・依存込みで複製して
    ``app.routes`` に平坦に積んでいたため、``app.routes`` の APIRoute をそのまま見ればよかった。
    fastapi 0.142 系では include_router が ``_IncludedRouter``（遅延ラッパ）を1件積むだけになり、
    中の APIRoute は prefix 無しの元のまま。実効のパス・依存木は ``iter_route_contexts`` が返す
    コンテキスト側にしか無いため、両方の版をこの形に揃えてから検査する。
    """

    path: str
    methods: frozenset[str]
    dependant: Dependant


def _iter_original_and_effective(app: FastAPI) -> Iterator[tuple[BaseRoute, Any]]:
    """アプリの全ルートを (元のルート, 実効ルート) の組で平坦に返す。

    新しい fastapi（``iter_route_contexts`` を持つ版）は include 済みルーターを再帰的に展開し、
    実効ルートは prefix・include 時の依存を反映した ``RouteContext``。古い fastapi は
    ``app.routes`` が既に平坦で、元のルート＝実効ルート。
    """
    iter_route_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    if iter_route_contexts is None:
        for route in app.routes:
            yield route, route
        return
    for route_context in iter_route_contexts(app.routes):
        yield route_context.original_route, route_context


def _api_routes(app: FastAPI) -> list[_EffectiveApiRoute]:
    routes: list[_EffectiveApiRoute] = []
    for original, effective in _iter_original_and_effective(app):
        if not isinstance(original, APIRoute):
            continue
        assert effective.dependant is not None, f"依存木の無い APIRoute: {effective.path}"
        routes.append(
            _EffectiveApiRoute(
                path=effective.path,
                methods=frozenset(effective.methods or ()),
                dependant=effective.dependant,
            )
        )
    return routes


def _foreign_routes(app: FastAPI) -> list[BaseRoute]:
    """APIRoute 以外で、読み取り専用（GET/HEAD のみの素の Route。/docs 等）と言い切れないもの。

    Mount・WebSocketRoute・書き込みメソッドを持つ Route に加え、展開できなかった未知の
    ラッパ型（将来の fastapi が include_router の表現をまた変えた場合など）も検出する。
    これらは依存木を検査できないため、存在した時点で失敗させる。
    """
    foreign: list[BaseRoute] = []
    for original, effective in _iter_original_and_effective(app):
        if isinstance(original, APIRoute):
            continue
        methods = set(getattr(effective, "methods", None) or ())
        if type(original) is Route and methods and methods <= {"GET", "HEAD"}:
            continue
        foreign.append(original)
    return foreign


def _protection_reasons(route: _EffectiveApiRoute) -> set[str]:
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


def _is_protected(route: _EffectiveApiRoute) -> bool:
    return bool(_protection_reasons(route))


def _mutating_routes(app: FastAPI) -> list[_EffectiveApiRoute]:
    return [route for route in _api_routes(app) if route.methods & _MUTATING_METHODS]


def _find_route(app: FastAPI, method: str, path: str) -> _EffectiveApiRoute:
    for route in _api_routes(app):
        if route.path == path and method in route.methods:
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
    foreign = _foreign_routes(app)
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


def test_self_check_include_router_prefix_and_dependencies_are_reflected() -> None:
    """include_router(prefix=..., dependencies=[...]) で付けた prefix・依存も実効ルートに反映される。

    fastapi 0.142 系は include_router を遅延ラッパで表現し、元の APIRoute は prefix も include 時の
    依存も持たない。元のルートだけを見ると「パスが見つからない」「保護なし」と誤判定する
    （2026-10 の CI 失敗の再発防止）。入れ子の include も同様に展開されること。
    """
    inner = APIRouter()

    @inner.post("/mutate")
    async def mutate() -> dict[str, bool]:  # pragma: no cover - 呼び出さない
        return {"ok": True}

    outer = APIRouter()
    outer.include_router(inner, prefix="/inner", dependencies=[Depends(deps.get_current_user)])
    unprotected = APIRouter()

    @unprotected.post("/open")
    async def open_mutate() -> dict[str, bool]:  # pragma: no cover - 呼び出さない
        return {"ok": True}

    app = FastAPI()
    app.include_router(outer, prefix="/api")
    app.include_router(unprotected, prefix="/api")

    assert _protection_reasons(_find_route(app, "POST", "/api/inner/mutate")) == {"auth"}
    assert not _is_protected(_find_route(app, "POST", "/api/open"))
    assert {r.path for r in _mutating_routes(app)} == {"/api/inner/mutate", "/api/open"}
    assert not _foreign_routes(app)


def test_self_check_mount_and_unknown_route_types_are_foreign() -> None:
    """Mount・include 済みルーター内の Mount・展開できない未知のルート型は「検査不能」として検出される。"""
    from starlette.applications import Starlette

    app = FastAPI()
    app.mount("/sub", Starlette())
    nested = APIRouter()
    nested.mount("/nested-sub", Starlette())
    app.include_router(nested, prefix="/api")

    class _UnknownWrapper(BaseRoute):
        """将来の fastapi が導入するかもしれない未知のラッパ型の代役。"""

    unknown = _UnknownWrapper()
    app.router.routes.append(unknown)

    foreign = _foreign_routes(app)
    # 旧 fastapi の include_router は内側ルーターの Mount を複製しない（到達不能なので検査不要）。
    # 新 fastapi は遅延ラッパ経由で到達可能になるため、検出されなければならない。
    expected_mounts = 2 if hasattr(fastapi_routing, "iter_route_contexts") else 1
    assert sum(type(r).__name__ == "Mount" for r in foreign) == expected_mounts
    assert unknown in foreign


def test_allowlisted_login_routes_keep_login_rate_limit_guard() -> None:
    """許可リスト（ガード単体は数えない login 系）でも、事前確認のガードは外せない。

    許可リストの理由は「record_failure をハンドラで数える」ことだが、テストはガードの有無を
    見ないため、ガードを消しても合格してしまう（security review M-1）。ここで存在を固定する。
    """
    app = _production_app()
    for path in ("/api/v1/auth/login", "/api/v1/auth/operator/login"):
        route = _find_route(app, "POST", path)
        scopes = {
            node.call._scope
            for node in _iter_dependant_nodes(route.dependant)
            if isinstance(node.call, RateLimitGuard)
        }
        assert "login" in scopes, f"POST {path} から RateLimitGuard('login') が外れています: {scopes}"

