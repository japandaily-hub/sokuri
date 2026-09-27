"""例外をログ・運営アラートへ載せるときの要約（例外が抱えている「値」を出さない）。

背景（2026-09-27 のログ点検・INC-2026-09-27-2 の続き）:
    PostgreSQL の例外文は DETAIL を含む（asyncpg/exceptions/_base.py の ``PostgresError.__str__``）。
    一意制約違反は ``Key (email)=(taro@example.com) already exists.``、CHECK・NOT NULL 違反は
    ``Failing row contains (...)``＝行全体（氏名・住所・電話番号・パスワードのハッシュを含みうる）。
    22 系（``invalid input syntax for type uuid: "..."`` 等）は本文そのものに入力値が入る。asyncpg が
    クライアント側で出す DataError も ``invalid input for query argument $1: '<値の先頭40字>' (...)``
    を含む。SQLAlchemy の例外文はこれらをそのまま抱え（``orig`` と ``__cause__`` の3段とも同じ文言）、
    app/db/session.py の hide_parameters が消すのは ``[parameters: ...]`` だけなので、
    ``logger.error("... %s", exc)``・トレースバック・未処理例外のアラート本文を通って値が残っていた。

方針:
    - DB 例外（SQLAlchemy の StatementError＝DBAPIError を含む・PendingRollbackError・ドライバの例外）は
      「例外の型・orig（DBAPI 例外）の型・ドライバ例外の型・SQLSTATE・制約名」と、あれば表名・列名だけに
      する（:func:`describe_db_error`）。表・列・制約はスキーマの識別子で値ではない（NOT NULL 違反は
      制約名が無く、列名が唯一の手掛かり）。文言は種類を問わず出さない（本文に値が入る 22 系や、
      トリガーの RAISE の文言があるため、安全な文言だけを選り分けることはしない）。原因の切り分けは
      SQLSTATE・制約名とトレースバックの発生箇所で行い、値が要るときは DB を直接見る。
    - 入力値を文言に抱える検証エラー（pydantic の ValidationError、FastAPI の ResponseValidationError
      等）も同じ扱いにする。応答モデルの検証失敗は、欠けた項目の親オブジェクト（利用者の行を丸ごと）を
      ``input`` に入れて文言に出すため、DB の DETAIL と同じ種類の漏れになる。件数と「どの項目がどの
      種類の誤りか」だけを残す。
    - それ以外の例外は従来どおり「型: 文言」にする（:func:`describe_exception`）。アプリや外部 API の
      クライアントが書く定型の文言で、行や入力を丸ごと抱える作りではなく、外部 API の失敗理由などは
      文言が無いと切り分けられない。ログへは出力直前の安全網（app/core/app_logging.py の
      mask_sensitive_in_text）も掛かる。
    - トレースバックは :func:`format_exception_for_log` で、上の2種類の文言だけを要約に差し替えて
      整形する（発生箇所のフレームは残す）。DB 例外の ``__cause__``（asyncpg が値の変換に失敗したときの
      TypeError 等）もドライバ内部の一部として文言を出さない。
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from fastapi.exceptions import ValidationException as _FastAPIValidationException
from pydantic import ValidationError as _PydanticValidationError
from sqlalchemy.exc import PendingRollbackError, StatementError

#: ドライバ（DBAPI）層の例外が定義されているモジュール。SQLAlchemy の asyncpg アダプタが包み直した
#: 例外（AsyncAdapt_asyncpg_dbapi.IntegrityError 等）は ``sqlalchemy.dialects`` 配下にある。
_DRIVER_MODULE_PREFIXES: tuple[str, ...] = (
    "asyncpg",
    "sqlite3",
    "aiosqlite",
    "psycopg",
    "psycopg2",
    "sqlalchemy.dialects",
    "sqlalchemy.connectors",
)

#: 一意制約違反の SQLSTATE（PostgreSQL の unique_violation）。
PG_UNIQUE_VIOLATION = "23505"

#: 識別子（制約・表・列・検証エラーの種類）として出してよい形。スキーマの識別子はすべてこの形で、
#: 外れる値（引用符付きの識別子・想定外の文字列）は ``?`` に置き換える（値を運ぶ経路にしない）。
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_$.\-]{1,63}", re.ASCII)
_SQLSTATE_RE = re.compile(r"[0-9A-Z]{5}", re.ASCII)
#: 検証エラーの位置（loc）のうち、項目名として出してよい形（dict のキー等の入力値は ``?`` にする）。
_LOC_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}", re.ASCII)

#: 検証エラーの要約に並べる項目の上限（超えた分は件数だけ）。
_MAX_VALIDATION_ITEMS = 10
#: DB 例外の ``__cause__`` をたどる上限（アダプタ→ドライバ→値の変換エラーの3段で足りる）。
_MAX_CAUSE_DEPTH = 8
#: exception group の入れ子をたどる上限（標準の traceback と同じ値）。
_MAX_GROUP_DEPTH = 10

_CAUSE_HEADER = "\nThe above exception was the direct cause of the following exception:\n\n"
_CONTEXT_HEADER = "\nDuring handling of the above exception, another exception occurred:\n\n"
_REDACTED_CAUSE = "（DB 例外の原因のため文言を省略）"


@dataclass(frozen=True)
class DbErrorInfo:
    """DB 例外から取り出した、値を含まない情報（型名と識別子だけ）。"""

    error_type: str
    orig_type: str | None
    driver_type: str | None
    sqlstate: str | None
    constraint: str | None
    table: str | None
    column: str | None

    def fields_text(self) -> str:
        """``orig=... driver=... sqlstate=... constraint=...``（表・列はあるときだけ）。"""
        parts: list[str] = []
        if self.orig_type is not None:
            parts.append(f"orig={self.orig_type}")
        if self.driver_type is not None:
            parts.append(f"driver={self.driver_type}")
        parts.append(f"sqlstate={self.sqlstate or '-'}")
        parts.append(f"constraint={self.constraint or '-'}")
        if self.table is not None:
            parts.append(f"table={self.table}")
        if self.column is not None:
            parts.append(f"column={self.column}")
        return " ".join(parts)

    def __str__(self) -> str:
        return f"{self.error_type} {self.fields_text()}"


def _is_driver_exception(exc: BaseException) -> bool:
    module = type(exc).__module__ or ""
    return any(module == prefix or module.startswith(prefix + ".") for prefix in _DRIVER_MODULE_PREFIXES)


def _is_asyncpg_exception(exc: BaseException) -> bool:
    module = type(exc).__module__ or ""
    return module == "asyncpg" or module.startswith("asyncpg.")


def is_db_exception(exc: object) -> bool:
    """文言に DB の値（DETAIL・SQL のパラメータ・入力値）を抱えうる例外か。

    SQLAlchemy の StatementError（DBAPIError とその下の IntegrityError 等を含む）、
    PendingRollbackError（本文に「元の例外」の文言を丸ごと入れる）、ドライバ層の例外。
    """
    if not isinstance(exc, BaseException):
        return False
    return isinstance(exc, (StatementError, PendingRollbackError)) or _is_driver_exception(exc)


def is_validation_error(exc: object) -> bool:
    """入力値を文言に抱える検証エラー（pydantic の ValidationError・FastAPI の検証例外）か。"""
    return isinstance(exc, (_PydanticValidationError, _FastAPIValidationException))


def is_value_bearing_exception(exc: object) -> bool:
    """文言をそのまま出すと値が漏れる例外か（DB 例外または検証エラー）。"""
    return is_db_exception(exc) or is_validation_error(exc)


def _identifier(value: object) -> str | None:
    """識別子として出してよい文字列ならそのまま、None は None、それ以外は ``?``。"""
    if value is None:
        return None
    if isinstance(value, str) and _IDENTIFIER_RE.fullmatch(value):
        return value
    return "?"


def _sqlstate(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _SQLSTATE_RE.fullmatch(value):
        return value
    return "?"


def _find_driver_exception(exc: BaseException, orig: BaseException | None) -> BaseException | None:
    """asyncpg の例外（SQLSTATE・制約名・表名・列名を持つ）を ``__cause__`` の連鎖から探す。

    SQLAlchemy の asyncpg アダプタは ``raise translated_error from error`` で元の asyncpg 例外を
    ``orig.__cause__`` に付ける（sqlalchemy/dialects/postgresql/asyncpg.py の _handle_exception）。
    """
    seen: set[int] = set()
    for start in (exc, orig):
        current: BaseException | None = start
        depth = 0
        while current is not None and id(current) not in seen and depth < _MAX_CAUSE_DEPTH:
            seen.add(id(current))
            if _is_asyncpg_exception(current):
                return current
            current = current.__cause__
            depth += 1
    return None


def _first_attr(names: Iterable[str], *objects: object) -> object:
    for obj in objects:
        if obj is None:
            continue
        for name in names:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return None


def db_error_info(exc: BaseException) -> DbErrorInfo | None:
    """DB 例外から型名と識別子だけを取り出す（DB 例外でなければ None）。

    - orig: SQLAlchemy の例外が包む DBAPI 例外（asyncpg 経由ではアダプタの IntegrityError 等）。
    - driver: asyncpg の例外（UniqueViolationError・DataError 等。種類が最も具体的に分かる）。
    - sqlstate: orig の sqlstate / pgcode（アダプタが asyncpg から写す）か asyncpg の sqlstate。
    - constraint / table / column: asyncpg がサーバのエラー項目（n / t / c）から入れる値。
    """
    if not is_db_exception(exc):
        return None
    orig = exc.orig if isinstance(exc, StatementError) else None
    if not isinstance(orig, BaseException):
        orig = None
    driver = _find_driver_exception(exc, orig)
    return DbErrorInfo(
        error_type=type(exc).__name__,
        orig_type=type(orig).__name__ if orig is not None else None,
        driver_type=type(driver).__name__ if driver is not None and driver is not exc else None,
        sqlstate=_sqlstate(_first_attr(("sqlstate", "pgcode"), orig, driver, exc)),
        constraint=_identifier(_first_attr(("constraint_name",), driver, orig, exc)),
        table=_identifier(_first_attr(("table_name",), driver)),
        column=_identifier(_first_attr(("column_name",), driver)),
    )


def describe_db_error(exc: BaseException) -> str:
    """DB 例外を ``IntegrityError orig=IntegrityError driver=UniqueViolationError sqlstate=23505
    constraint=uq_users_email table=users`` の形の1行にする（文言・SQL・パラメータは出さない）。

    DB 例外でないものを渡したときは型名だけを返す（値を出す側に倒さない）。
    """
    info = db_error_info(exc)
    return str(info) if info is not None else type(exc).__name__


def _loc_text(loc: object) -> str:
    if not isinstance(loc, (tuple, list)) or not loc:
        return "?"
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int) and not isinstance(part, bool):
            parts.append(str(part))
        elif isinstance(part, str) and _LOC_NAME_RE.fullmatch(part):
            parts.append(part)
        else:
            parts.append("?")
    return ".".join(parts)


def _validation_fields_text(exc: BaseException) -> str:
    """``model=Out errors=2 at=response.email:value_error, response.name:missing``（入力値・文言は出さない）。"""
    try:
        errors = list(exc.errors())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- 要約のために元の処理を壊さない
        return "errors=?"
    items = [
        f"{_loc_text(error.get('loc'))}:{_identifier(error.get('type')) or '?'}"
        for error in errors[:_MAX_VALIDATION_ITEMS]
        if isinstance(error, dict)
    ]
    text = f"errors={len(errors)} at={', '.join(items) or '-'}"
    if len(errors) > _MAX_VALIDATION_ITEMS:
        text += f"（ほか {len(errors) - _MAX_VALIDATION_ITEMS} 件）"
    if isinstance(exc, _PydanticValidationError):
        text = f"model={_identifier(exc.title) or '?'} {text}"
    return text


def _safe_str(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:  # noqa: BLE001 -- __str__ が壊れた例外でも要約は返す
        return f"<{type(exc).__name__} の文言を取得できません>"


def describe_exception(exc: BaseException, *, limit: int = 200) -> str:
    """ログ・運営アラートの本文に載せる例外の説明。

    - DB 例外: :func:`describe_db_error`（型・orig の型・ドライバ例外の型・SQLSTATE・制約名・表・列）
    - 検証エラー: ``ResponseValidationError errors=1 at=response.email:missing`` の形（入力値を出さない）
    - それ以外: 従来どおり ``型: 文言``（文言は先頭 ``limit`` 字）
    """
    if is_db_exception(exc):
        return describe_db_error(exc)
    if is_validation_error(exc):
        return f"{type(exc).__name__} {_validation_fields_text(exc)}"
    return f"{type(exc).__name__}: {_safe_str(exc)[:limit]}"


def is_unique_violation(
    exc: BaseException, constraint_names: Collection[str], *, sqlite_columns: str
) -> bool:
    """``constraint_names`` のいずれかの一意制約の違反か。

    PostgreSQL: SQLSTATE 23505 かつ制約名（asyncpg の constraint_name）が一致。
    SQLite（テスト）: SQLSTATE も制約名も返さないため、文言 ``UNIQUE constraint failed: <sqlite_columns>``
    との完全一致で判別する（sqlite3 の文言は SQL・値を含まない。一致を見るだけで外へは出さない）。
    """
    info = db_error_info(exc)
    if info is None:
        return False
    if info.sqlstate is not None:
        return info.sqlstate == PG_UNIQUE_VIOLATION and info.constraint in constraint_names
    orig = exc.orig if isinstance(exc, StatementError) else exc
    return _safe_str(orig).strip() == f"UNIQUE constraint failed: {sqlite_columns}"


# ──────────────── トレースバック ────────────────


def _qualified_type_name(exc: BaseException) -> str:
    """標準のトレースバックと同じ ``モジュール.型`` の表記（builtins は型名だけ）。"""
    exc_type = type(exc)
    module = exc_type.__module__
    if module in ("__main__", "builtins") or not isinstance(module, str):
        return exc_type.__qualname__
    return f"{module}.{exc_type.__qualname__}"


def _exception_only_lines(exc: BaseException, *, redact: bool) -> list[str]:
    """トレースバック末尾の「型: 文言」の行。DB 例外・検証エラー・DB 例外の原因は文言を差し替える。"""
    name = _qualified_type_name(exc)
    info = db_error_info(exc)
    if info is not None:
        return [f"{name}: {info.fields_text()}\n"]
    if redact:
        return [f"{name}: {_REDACTED_CAUSE}\n"]
    if is_validation_error(exc):
        return [f"{name}: {_validation_fields_text(exc)}\n"]
    return list(traceback.format_exception_only(exc))


def _format_single(exc: BaseException, *, redact: bool, seen: set[int], depth: int) -> list[str]:
    parts: list[str] = []
    if exc.__traceback__ is not None:
        parts.append("Traceback (most recent call last):\n")
        parts.extend(traceback.format_tb(exc.__traceback__))
    parts.extend(_exception_only_lines(exc, redact=redact))
    if isinstance(exc, BaseExceptionGroup):
        if depth >= _MAX_GROUP_DEPTH:
            parts.append("  ...（exception group の入れ子が深いため以降を省略）\n")
        else:
            for index, sub_exc in enumerate(exc.exceptions, 1):
                parts.append(f"  +---------------- {index} ----------------\n")
                sub_text = "".join(_format_chain(sub_exc, seen=seen, depth=depth + 1))
                parts.extend("    " + line for line in sub_text.splitlines(keepends=True))
    return parts


def _format_chain(exc: BaseException, *, seen: set[int], depth: int) -> list[str]:
    """``__cause__`` / ``__context__`` の連鎖を、標準のトレースバックと同じく古いものから並べる。"""
    # (例外, その例外の後に置く見出し, 文言を伏せるか) を新しい順に集める。見出しは「この例外が次に
    # 新しい例外の原因（cause）か、処理中に起きたか（context）」。DB 例外の cause はドライバ内部の
    # 一部（asyncpg が値の変換に失敗した TypeError 等）なので文言を伏せる。context は別の出来事なので伏せない。
    chain: list[tuple[BaseException, str | None, bool]] = []
    current: BaseException | None = exc
    header: str | None = None
    redact = False
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append((current, header, redact))
        if current.__cause__ is not None:
            header = _CAUSE_HEADER
            redact = redact or is_db_exception(current)
            current = current.__cause__
        elif current.__context__ is not None and not current.__suppress_context__:
            header = _CONTEXT_HEADER
            redact = False
            current = current.__context__
        else:
            current = None
    parts: list[str] = []
    for item, item_header, item_redact in reversed(chain):
        parts.extend(_format_single(item, redact=item_redact, seen=seen, depth=depth))
        if item_header is not None:
            parts.append(item_header)
    return parts


def _format_types_only(exc: BaseException) -> str:
    """整形に失敗したときの代わり（型名の並びだけ。文言は出さない）。"""
    names: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(names) < 16:
        seen.add(id(current))
        names.append(_qualified_type_name(current))
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return "（トレースバックを整形できなかったため例外の型だけを記録）" + " <- ".join(names)


def format_exception_for_log(exc: BaseException | None) -> str:
    """ログ用のトレースバック。標準の ``traceback.format_exception`` と同じ並び・フレームで、
    DB 例外・検証エラー・DB 例外の原因の文言だけを要約に差し替える。末尾の改行は付けない。

    ログの書式から呼ぶため例外は出さない（整形に失敗したら型名の並びだけを返す）。
    """
    if exc is None:
        return "NoneType: None"
    try:
        text = "".join(_format_chain(exc, seen=set(), depth=0))
    except Exception:  # noqa: BLE001 -- ログのために処理を止めない（隠す側に倒す）
        text = _format_types_only(exc)
    return text[:-1] if text.endswith("\n") else text
