"""共有 HTTPException インスタンスによるトレースバック蓄積（メモリ増加）の回帰テスト。

モジュールレベルで 1 回だけ生成した ``HTTPException`` を ``raise _XXX`` で使い回すと、
CPython は raise のたびに新しいトレースバックを既存の ``__traceback__`` の前へ連結する。
共有インスタンスはプロセス終了まで生き続けるため、連結されたフレームとそのローカル変数
（request・DB セッション・ORM オブジェクト）も解放されず、401/404 を返すだけの通常
トラフィックや未認証の攻撃者のリクエストでメモリが単調に増えていた（2026-09-25 実測:
不正トークン 100 回で ``deps._CRED_EXC`` に 1000 フレーム、``GET /files/<不正キー>``
100 回で ``case_photos._FILE_NOT_FOUND`` に 500 フレーム）。

本ファイルで固定する契約:

- ``app/`` 配下で、関数本体の外（モジュール・クラス直下、if/try の中、dict 等への
  ネスト、デフォルト引数）に例外インスタンスの生成が無く、モジュールレベルで代入した
  名前をそのまま ``raise`` していないこと（静的検査）。定型の応答は
  ``app.core.http_errors.http_exception_factory`` で「呼ぶたびに新しいインスタンスを
  返す関数」として定義する。例外クラスの判定は型解決ではなく名前（``*Exception`` /
  ``*Error``・その import 別名・派生クラス）による。
- import 済みの ``app.*`` モジュールのグローバル（とその中の dict・list 等）に例外
  インスタンスが存在しないこと。
- ファクトリは呼ぶたびに別インスタンスを返し、status_code・detail・headers は従来の
  定数と同一（headers の dict も共有しない）。
- 代表経路（不正トークンの 401、``/files`` の 404、任意認証付きの ``/files``、内部で
  捕捉される raise）を繰り返しても、生存している HTTPException のトレースバックの
  フレーム数が増えないこと。
"""

from __future__ import annotations

import ast
import gc
import pathlib
import sys
from types import TracebackType
from typing import AsyncIterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.v1.router import api_router
from app.core.http_errors import http_exception_factory
from app.db.session import get_session

_APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
# deps._CRED_EXC の応答契約（web はこの status・ヘッダでサインアウトへ遷移する）。
_CRED_DETAIL = "Invalid credentials. Please log in again."
# case_photos._FILE_NOT_FOUND の応答契約。
_FILE_NOT_FOUND_DETAIL = "ファイルが見つかりません。"
_INVALID_TOKEN = "Bearer not-a-valid-jwt"
_INVALID_STORAGE_KEY = "not-a-valid-storage-key"
# 1 回目の計測を済ませた後に重ねて叩く回数。旧実装では 1 回ごとに 5〜10 フレーム増えていた。
_REPEAT = 20


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


def _traceback_frame_count(tb: TracebackType | None) -> int:
    count = 0
    while tb is not None:
        count += 1
        tb = tb.tb_next
    return count


def _live_http_exception_frames() -> int:
    """GC 後も生存している全 HTTPException のトレースバックのフレーム数の合計を返す。

    共有インスタンスがあれば raise のたびにこの値が単調に増える。raise ごとに新しい
    インスタンスを作っていれば、応答後に参照が切れて回収されるため増えない。
    （最長値ではなく合計を見る: 最長値だと、先行テストで肥大化した別の共有インスタンスが
    基準値を支配し、対象経路の蓄積を見逃すため。）
    """
    gc.collect()
    return sum(
        _traceback_frame_count(obj.__traceback__)
        for obj in gc.get_objects()
        if isinstance(obj, HTTPException)
    )


# ──────────────────────── 静的検査（再発防止のガード） ────────────────────────


_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _iter_nodes_outside_functions(node: ast.AST):
    """関数本体（と lambda）の中を除いた全ノードを列挙する。

    モジュール本体・クラス本体の直下だけでなく、if / try ブロックの中や dict・tuple 等に
    ネストした式も対象にする（そこで生成した値は import 時に 1 回だけ作られ共有される）。
    関数本体の中は呼び出しごとに新しいインスタンスになるため対象外。
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCTION_NODES):
            # デフォルト引数・デコレータは定義時に 1 回だけ評価されるため対象に含める。
            if not isinstance(child, ast.Lambda):
                for expr in [*child.decorator_list, *child.args.defaults, *child.args.kw_defaults]:
                    if expr is not None:
                        yield expr
                        yield from _iter_nodes_outside_functions(expr)
            continue
        yield child
        yield from _iter_nodes_outside_functions(child)


def _exception_class_names(tree: ast.Module) -> set[str]:
    """このモジュールで例外クラスとみなす名前（命名規約＋import の別名＋自前の派生クラス）。

    型の解決はせず名前で判定する（``*Exception`` / ``*Error`` と、その import 別名、
    それらを継承したクラス）。命名規約から外れた例外クラスの共有インスタンスは
    ``test_no_module_level_name_is_raised`` 側で検出する。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name.endswith(("Exception", "Error")):
                    names.add(alias.asname or alias.name.rsplit(".", 1)[-1])
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name not in names:
                bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases}
                if node.name.endswith(("Exception", "Error")) or bases & names or any(
                    b.endswith(("Exception", "Error")) for b in bases
                ):
                    names.add(node.name)
                    changed = True
    return names


def _shared_exception_definitions(tree: ast.Module, path: pathlib.Path) -> list[str]:
    """関数本体の外で例外インスタンスを生成している箇所を列挙する。"""
    exception_names = _exception_class_names(tree)
    found: list[str] = []
    for node in _iter_nodes_outside_functions(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in exception_names or name.endswith(("Exception", "Error")):
            found.append(f"{path.relative_to(_APP_DIR.parent)}:{node.lineno} {name}(...)")
    return found


def _module_level_assigned_names(tree: ast.Module) -> set[str]:
    """関数本体の外で代入される名前（例外クラスの定義・import は含めない）。"""
    names: set[str] = set()
    for node in _iter_nodes_outside_functions(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    return names


def test_no_module_or_class_level_exception_instances_in_app() -> None:
    """共有の例外インスタンスを定義しないこと（``http_exception_factory`` を使う）。"""
    offenders: list[str] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(_shared_exception_definitions(tree, path))
    assert offenders == [], (
        "モジュール／クラスレベルで生成した例外インスタンスを raise で使い回すと、"
        "トレースバックが蓄積してメモリが増え続ける。app.core.http_errors."
        "http_exception_factory で定義し raise _XXX() とすること: " + ", ".join(offenders)
    )


def test_no_module_level_name_is_raised() -> None:
    """モジュールレベルで代入した名前をそのまま ``raise`` しないこと。

    例外クラス名の命名規約や import の別名に依らず、共有インスタンスの使い回しを
    raise 側から検出する（``raise _XXX()`` のように呼び出した結果を raise するのは可）。
    """
    offenders: list[str] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        shared_names = _module_level_assigned_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                target = node.exc
                if isinstance(target, ast.Name) and target.id in shared_names:
                    offenders.append(f"{path.relative_to(_APP_DIR.parent)}:{node.lineno} raise {target.id}")
    assert offenders == [], ", ".join(offenders)


def _contains_exception_instance(value: object, depth: int = 0) -> bool:
    if isinstance(value, BaseException):
        return True
    if depth >= 3:
        return False
    if isinstance(value, dict):
        return any(_contains_exception_instance(v, depth + 1) for v in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_exception_instance(v, depth + 1) for v in value)
    return False


def test_no_exception_instances_in_imported_app_module_globals() -> None:
    """ルーター経由で import される全モジュールのグローバル（とその中のコンテナ）に
    例外インスタンスが無いこと。"""
    offenders = [
        f"{module_name}.{attr}"
        for module_name, module in list(sys.modules.items())
        if module is not None and (module_name == "app" or module_name.startswith("app."))
        for attr, value in list(vars(module).items())
        if _contains_exception_instance(value)
    ]
    assert offenders == []


# ──────────────────────────── ファクトリの契約 ────────────────────────────


def test_factory_returns_new_instance_with_identical_contract() -> None:
    make = http_exception_factory(
        status_code=401,
        detail="Invalid credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    first, second = make(), make()

    assert first is not second
    for exc in (first, second):
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 401
        assert exc.detail == "Invalid credentials. Please log in again."
        assert exc.headers == {"WWW-Authenticate": "Bearer"}
        assert exc.__traceback__ is None
    # headers の dict も共有しない（片方を書き換えても次の応答へ波及しない）。
    assert first.headers is not second.headers
    first.headers["X-Mutated"] = "1"
    assert make().headers == {"WWW-Authenticate": "Bearer"}


def test_factory_does_not_alias_caller_headers() -> None:
    headers = {"WWW-Authenticate": "Bearer"}
    make = http_exception_factory(status_code=401, detail="x", headers=headers)
    headers["WWW-Authenticate"] = "Changed"
    assert make().headers == {"WWW-Authenticate": "Bearer"}


def test_factory_does_not_share_mutable_detail() -> None:
    detail = {"code": "x"}
    make = http_exception_factory(status_code=409, detail=detail)
    detail["code"] = "changed"
    first = make()
    first.detail["code"] = "mutated"
    assert make().detail == {"code": "x"}


def test_factory_without_headers_keeps_none() -> None:
    exc = http_exception_factory(status_code=404, detail="見つかりません。")()
    assert exc.status_code == 404
    assert exc.detail == "見つかりません。"
    assert exc.headers is None


def test_shared_constants_are_factories_with_unchanged_contract() -> None:
    """代表的な定数が呼び出し可能になり、応答契約（status・detail・headers）が不変であること。"""
    from app.api.v1.endpoints import case_photos

    cred = deps._CRED_EXC()
    assert (cred.status_code, cred.detail, cred.headers) == (
        401,
        _CRED_DETAIL,
        {"WWW-Authenticate": "Bearer"},
    )
    not_found = case_photos._FILE_NOT_FOUND()
    assert (not_found.status_code, not_found.detail, not_found.headers) == (
        404,
        _FILE_NOT_FOUND_DETAIL,
        None,
    )
    assert deps._CRED_EXC() is not cred
    assert case_photos._FILE_NOT_FOUND() is not not_found


# ─────────────────────── 実経路でフレームが蓄積しないこと ───────────────────────


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/users/me/profile"])
async def test_invalid_token_401_does_not_accumulate_traceback(
    client: AsyncClient, path: str
) -> None:
    """不正トークンの 401（未認証の攻撃者・期限切れトークンの通常トラフィック）。"""
    r = await client.get(path, headers={"Authorization": _INVALID_TOKEN})
    assert r.status_code == 401
    assert r.json()["detail"] == _CRED_DETAIL
    assert r.headers["www-authenticate"] == "Bearer"
    baseline = _live_http_exception_frames()

    for _ in range(_REPEAT):
        r = await client.get(path, headers={"Authorization": _INVALID_TOKEN})
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"

    assert _live_http_exception_frames() <= baseline


@pytest.mark.parametrize(
    "headers",
    [
        {},
        # 任意認証（get_optional_operator）が壊れたトークンを内部で None に倒す経路。
        {"Authorization": _INVALID_TOKEN},
    ],
    ids=["anonymous", "optional-auth-invalid-token"],
)
async def test_files_404_does_not_accumulate_traceback(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    """認証もレート制限も無い ``GET /files/<不正キー>`` の 404。"""
    url = f"/api/v1/files/{_INVALID_STORAGE_KEY}"
    r = await client.get(url, headers=headers)
    assert r.status_code == 404
    assert r.json()["detail"] == _FILE_NOT_FOUND_DETAIL
    baseline = _live_http_exception_frames()

    for _ in range(_REPEAT):
        r = await client.get(url, headers=headers)
        assert r.status_code == 404

    assert _live_http_exception_frames() <= baseline


def test_internally_caught_raise_gets_fresh_exception_each_time() -> None:
    """``except HTTPException`` で内部捕捉される経路でも、毎回別インスタンスで
    トレースバックが伸びないこと（例外ハンドラで ``__traceback__`` を消すだけでは
    防げない経路の代表）。"""
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-valid-jwt")
    caught: list[HTTPException] = []
    for _ in range(_REPEAT):
        try:
            deps._decode(credentials)
        except HTTPException as exc:
            caught.append(exc)

    assert len(caught) == _REPEAT
    assert len({id(exc) for exc in caught}) == _REPEAT
    frame_counts = {_traceback_frame_count(exc.__traceback__) for exc in caught}
    assert len(frame_counts) == 1
    assert all(exc.status_code == 401 and exc.detail == _CRED_DETAIL for exc in caught)
