"""DB 例外を扱う except 節で、例外の文言をそのままログ・アラート本文・応答へ出していないことの静的検査。

2026-09-27（INC-2026-09-27-2 の続き）: PostgreSQL の例外文は DETAIL（一意制約違反のキーの値・CHECK
違反の行全体）を含み、``logger.error("... %s", exc)`` やアラート本文の ``str(exc)[:200]`` を通って
Render のログ・LINE・メールへ残っていた。要約は app/core/error_summary.py の describe_exception
（DB 例外は型・SQLSTATE・制約名だけ）を通すこと。本検査は、その書き方が崩れたら CI で落とす。

対象の except 節（名前を付けて捕まえるもの）:
- DB 例外の型（IntegrityError・DBAPIError・SQLAlchemyError 等）を捕まえる節
- try の本体が DB を触る節（session・engine・接続の操作、DB を使う起動時・定期処理の呼び出し）と、
  アプリ全体の未処理例外を受ける ASGI ミドルウェア（``self.app(...)`` を包む節）

禁止: 捕まえた例外（``exc`` と、``exc.orig`` 等その属性）を、要約関数（describe_exception 等）・
``type()`` を通さずに「出口」へ渡すこと。出口＝ログ呼び出しの引数（本文を含む）・運営アラート
（send_alert / resolve_alert）の引数・HTTPException の引数・f-string・``%`` 書式・``.format()``。
分類のために文言を読むだけ（``"idempotency_key" in str(exc.orig)`` 等、出口へ渡さないもの）は対象外。
出力直前の安全網（app/core/app_logging.py）は例外オブジェクトの引数を要約に差し替えるが、APP_LOG_LEVEL
が無いと効かず、``str(exc)`` 済みの文字列は救えないため、呼び出し側で要約を渡すことを正とする。
"""
from __future__ import annotations

import ast
import pathlib
import re

_APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"

_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
_LOGGER_RECEIVER_RE = re.compile(r"(^|\.)_?(logger|log|_logger)$")
#: 例外を通してよい要約・判定の関数（中を通った例外の文言は出口へ出ない）。
_ALLOWED_WRAPPERS = {
    "type",
    "isinstance",
    "id",
    "describe_exception",
    "describe_db_error",
    "db_error_info",
    "is_db_exception",
    "is_unique_violation",
    "_classify_integrity_error",
    "_operator_signup_conflict",
}
#: 出口とみなす呼び出し（ログ以外）。
_SINK_CALLS = {"send_alert", "resolve_alert", "HTTPException"}
_DB_EXCEPTION_TYPES_RE = re.compile(
    r"IntegrityError|DBAPIError|SQLAlchemyError|StatementError|OperationalError|DataError"
    r"|ProgrammingError|InterfaceError|PendingRollbackError|DatabaseError|asyncpg"
)
_DB_TRY_BODY_RE = re.compile(
    r"\bsession\b|session_factory|\bengine\b|\bconn\b|\.commit\(|\.flush\(|\.execute\(|\.scalars?\("
    r"|\.refresh\(|run_reminders|seed_channels_and_rules|sweep_stale_pending_ai|self\.app\("
)

#: 対象の節のうち、例外の文言をそのまま出している既知の箇所（理由を必ず書く）。増やさないこと。
_ALLOWED_SITES: dict[tuple[str, str], str] = {
    ("main.py", "readyz"): (
        "/readyz の DB 到達性（SELECT 1）とスキーマ状態（alembic_version）の確認。パラメータも行の値も"
        "持たない問い合わせで、DETAIL に利用者の値は入らない。別セッション（I8）が /readyz を改修中の"
        "ため触らない。本番では出力直前の安全網（AppLogFormatter の引数の差し替え）で要約される。"
    ),
}


def _func_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_log_call(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _LOG_METHODS
        and bool(_LOGGER_RECEIVER_RE.search(ast.unparse(func.value)))
    )


def _raw_uses(expr: ast.AST, name: str) -> list[ast.Name]:
    """``expr`` の中で、許可された関数を通らずに現れる ``name`` の出現。"""
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(expr):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    raw: list[ast.Name] = []
    for node in ast.walk(expr):
        if not (isinstance(node, ast.Name) and node.id == name):
            continue
        current: ast.AST | None = node
        allowed = False
        while current is not None and current is not expr:
            current = parents.get(current)
            if isinstance(current, ast.Call) and _func_name(current.func) in _ALLOWED_WRAPPERS:
                allowed = True
                break
        if not allowed:
            raw.append(node)
    return raw


def _sink_expressions(body: list[ast.stmt]) -> list[ast.AST]:
    """except 節の本体にある「出口」へ渡る式。"""
    sinks: list[ast.AST] = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            if _is_log_call(node):
                sinks.extend(node.args)
                sinks.extend(
                    keyword.value
                    for keyword in node.keywords
                    if keyword.arg not in {"exc_info", "stack_info", "stacklevel"}
                )
            elif _func_name(node.func) in _SINK_CALLS:
                sinks.extend(node.args)
                sinks.extend(keyword.value for keyword in node.keywords)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                sinks.extend(node.args)
                sinks.extend(keyword.value for keyword in node.keywords)
        elif isinstance(node, ast.JoinedStr):
            sinks.extend(value.value for value in node.values if isinstance(value, ast.FormattedValue))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            sinks.append(node.right)
    return sinks


def _in_scope(try_node: ast.Try, handler: ast.ExceptHandler) -> bool:
    if handler.type is not None and _DB_EXCEPTION_TYPES_RE.search(ast.unparse(handler.type)):
        return True
    return bool(_DB_TRY_BODY_RE.search("\n".join(ast.unparse(stmt) for stmt in try_node.body)))


def _enclosing_functions(tree: ast.AST) -> dict[ast.AST, str]:
    owner: dict[ast.AST, str] = {}

    def _visit(node: ast.AST, current: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = current
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            owner[child] = name
            _visit(child, name)

    _visit(tree, "<module>")
    return owner


def _violations_in_source(source: str, filename: str) -> list[tuple[str, str, int, str]]:
    """(ファイル, 関数名, 行, 式) の一覧。"""
    tree = ast.parse(source, filename=filename)
    owner = _enclosing_functions(tree)
    found: list[tuple[str, str, int, str]] = []
    for try_node in ast.walk(tree):
        if not isinstance(try_node, ast.Try):
            continue
        for handler in try_node.handlers:
            if handler.name is None or not _in_scope(try_node, handler):
                continue
            for sink in _sink_expressions(handler.body):
                for use in _raw_uses(sink, handler.name):
                    found.append((filename, owner.get(handler, "<module>"), use.lineno, ast.unparse(sink)))
    return found


def _scan_app() -> list[tuple[str, str, int, str]]:
    violations: list[tuple[str, str, int, str]] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        relative = path.relative_to(_APP_DIR).as_posix()
        violations.extend(_violations_in_source(path.read_text(encoding="utf-8"), relative))
    return violations


def test_db_exception_handlers_do_not_emit_raw_exception_text():
    unexpected = [v for v in _scan_app() if (v[0], v[1]) not in _ALLOWED_SITES]
    assert unexpected == [], (
        "DB 例外を扱う except 節で、例外の文言をそのまま出口（ログ・アラート・応答・書式）へ渡しています。"
        " describe_exception(exc) を通してください（app/core/error_summary.py）: "
        + "; ".join(f"{f}:{line} in {func}(): {expr}" for f, func, line, expr in unexpected)
    )


def test_allowed_sites_are_still_needed():
    """許可リストが古くならないこと（直したら外す）。"""
    present = {(v[0], v[1]) for v in _scan_app()}
    assert set(_ALLOWED_SITES) <= present, sorted(set(_ALLOWED_SITES) - present)


def test_guard_detects_the_patterns_it_is_meant_to_forbid():
    """陽性対照: 以前の書き方（2026-09-27 に直した各所の元の形）を検出し、直した形は検出しない。"""
    source = '''
async def save(session, logger, alerts):
    try:
        await session.commit()
    except Exception as exc:
        logger.error("保存に失敗 - %s", exc, exc_info=True)
        logger.error("保存に失敗 - %s: %s", type(exc).__name__, str(exc)[:200])
        logger.error(f"保存に失敗 - {exc!r}")
        logger.error("保存に失敗 - %s" % exc.orig)
        alerts.send_alert("失敗", f"直近のエラー: {type(exc).__name__}: {str(exc)[:200]}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

async def classify(session):
    try:
        await session.flush()
    except IntegrityError as exc:
        if "idempotency_key" in str(exc.orig):
            return 409
        raise

async def fixed(session, logger, alerts):
    try:
        await session.commit()
    except Exception as exc:
        logger.error("保存に失敗 - %s", describe_exception(exc), exc_info=True)
        logger.error("error=%s cause=%s", type(exc).__name__, type(exc.orig).__name__)
        alerts.send_alert("失敗", f"直近のエラー: {describe_exception(exc)}")
        raise HTTPException(status_code=500, detail="保存に失敗しました。") from exc

async def not_db(client, logger):
    try:
        await client.post("https://api.line.me/v2/bot/message/push")
    except Exception as exc:
        logger.error("LINE Push送信失敗 - %s", exc)
'''
    found = _violations_in_source(source, "probe.py")
    assert {(func, line) for _, func, line, _ in found} == {
        ("save", 6),
        ("save", 7),
        ("save", 8),
        ("save", 9),
        ("save", 10),
        ("save", 11),
    }
