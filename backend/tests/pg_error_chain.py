"""PostgreSQL（asyncpg）経由の DB 例外を、本番と同じ連鎖・同じクラスで作るテスト用の部品。

本番の連鎖（2026-09-27 時点の SQLAlchemy 2.0 / asyncpg 0.31 で確認）:

    asyncpg の例外（文言に DETAIL を含む。asyncpg/exceptions/_base.py の PostgresError.__str__）
      ↑ __cause__（sqlalchemy/dialects/postgresql/asyncpg.py の _handle_exception:
      │            ``raise translated_error from error``。sqlstate を pgcode / sqlstate に写す）
    AsyncAdapt_asyncpg_dbapi.<IntegrityError 等>（文言は ``"<class ...>: <asyncpg の文言>"``）
      ↑ __cause__（sqlalchemy/engine/base.py の _handle_dbapi_exception）
    sqlalchemy.exc.<IntegrityError 等>（文言に orig の文言・SQL・パラメータ）

値の変換に失敗したとき（asyncpg/protocol/prepared_stmt.pyx）は ``asyncpg.exceptions.DataError``
（SQLSTATE 22000）が ``invalid input for query argument $1: '<値の repr の先頭40字>' (<元の例外>)`` の
文言で ``from e``（元の TypeError / ValueError。こちらの文言にも値が入りうる）付きで送出される。

テストの値は呼び出し側でモジュールの定数に置くこと（トレースバックはソースの行を表示するため、
値を raise の行に直書きすると「実行時の値」ではなく「ソースの行」としてログに出てしまい、検査が
意味を失う）。
"""

from __future__ import annotations

import logging

import asyncpg
from asyncpg.exceptions import DataError as AsyncpgDataError
from asyncpg.exceptions import PostgresError
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
from sqlalchemy.exc import DBAPIError

from app.core.app_logging import AppLogFormatter

_DBAPI = AsyncAdapt_asyncpg_dbapi(asyncpg)

# ──────────────── 検査に使う値（ログ・アラートに出てはいけないもの） ────────────────

PROBE_EMAIL = "leak-probe@example.com"
PROBE_NAME = "漏洩確認太郎"
PROBE_ADDRESS = "東京都千代田区永田町1-7-1"
PROBE_PHONE = "090-9876-5432"
PROBE_LINE_USER_ID = "U" + "5a" * 16
PROBE_INVITE_CODE = "INVITE-LEAK-PROBE-7788"
#: 出力に部分でも残ってはいけない文字列（メールのローカル部・住所の一部・電話番号の下8桁を含む）。
PROBE_RAW_VALUES = (
    PROBE_EMAIL,
    "leak-probe",
    PROBE_NAME,
    PROBE_ADDRESS,
    "永田町",
    PROBE_PHONE,
    "9876-5432",
    PROBE_LINE_USER_ID,
    PROBE_INVITE_CODE,
)

#: CHECK 違反（DETAIL は行全体＝メール・氏名・住所・電話番号）。
CHECK_ROW_FIELDS = {
    "S": "ERROR",
    "C": "23514",
    "M": 'new row for relation "users" violates check constraint "ck_users_role"',
    "D": f"Failing row contains ({PROBE_EMAIL}, {PROBE_NAME}, {PROBE_ADDRESS}, {PROBE_PHONE}).",
    "s": "public",
    "t": "users",
    "n": "ck_users_role",
}
CHECK_ROW_SUMMARY = (
    "IntegrityError orig=IntegrityError driver=CheckViolationError"
    " sqlstate=23514 constraint=ck_users_role table=users"
)


def unique_violation_fields(table: str, constraint: str, column: str, value: str) -> dict[str, str]:
    """一意制約違反（DETAIL は ``Key (<列>)=(<値>) already exists.``）。"""
    return {
        "S": "ERROR",
        "C": "23505",
        "M": f'duplicate key value violates unique constraint "{constraint}"',
        "D": f"Key ({column})=({value}) already exists.",
        "s": "public",
        "t": table,
        "n": constraint,
    }


def unique_violation_summary(table: str, constraint: str) -> str:
    return (
        "IntegrityError orig=IntegrityError driver=UniqueViolationError"
        f" sqlstate=23505 constraint={constraint} table={table}"
    )


def assert_no_probe_values(output: str) -> None:
    for raw in PROBE_RAW_VALUES:
        assert raw not in output, f"{raw!r} が出力に残っている: {output!r}"


def production_log_output(records: list[logging.LogRecord]) -> str:
    """本番（APP_LOG_LEVEL あり）の app.* ハンドラと同じ書式（トレースバックを含む）で整形した出力。"""
    formatter = AppLogFormatter()
    return "\n".join(formatter.format(record) for record in records)


def failing(error: BaseException):
    """呼ばれたら ``error`` を送出する非同期関数（session.commit / flush 等の差し替え用）。"""

    async def _raise(*_args, **_kwargs):
        raise error

    return _raise


def _translate(driver_error: BaseException) -> Exception:
    """SQLAlchemy の asyncpg アダプタと同じ対応表・同じ文言で DBAPI 例外に包み直す。"""
    mapping = _DBAPI._asyncpg_error_translate
    for super_ in type(driver_error).__mro__:
        if super_ in mapping:
            translated = mapping[super_](f"{type(driver_error)}: {driver_error}")
            translated.pgcode = translated.sqlstate = getattr(driver_error, "sqlstate", None)
            return translated
    raise AssertionError(f"対応表に無い asyncpg の例外です: {type(driver_error)!r}")


def raise_through_sqlalchemy(
    driver_error: BaseException,
    *,
    statement: str,
    params: object,
    hide_parameters: bool,
) -> DBAPIError:
    """``driver_error`` を本番と同じ3段の連鎖で実際に送出し、捕まえた SQLAlchemy の例外を返す。

    各段は ``raise ... from ...`` で送出するので、``__traceback__``・``__cause__``・
    ``__context__`` も本番と同じ形になる（トレースバックの整形の検査に使える）。
    """
    try:
        try:
            try:
                raise driver_error
            except BaseException as caught:  # noqa: BLE001 -- 何でも包み直す（本番のアダプタと同じ）
                raise _translate(caught) from caught
        except AsyncAdapt_asyncpg_dbapi.Error as dbapi_error:
            raise DBAPIError.instance(
                statement,
                params,
                dbapi_error,
                AsyncAdapt_asyncpg_dbapi.Error,
                hide_parameters=hide_parameters,
            ) from dbapi_error
    except DBAPIError as sa_error:
        return sa_error
    raise AssertionError("到達しない")


def pg_server_error(
    fields: dict[str, str],
    *,
    statement: str = "INSERT INTO users (email, name) VALUES ($1, $2)",
    params: object = (),
    hide_parameters: bool = True,
) -> DBAPIError:
    """サーバが返したエラー（フィールド C=SQLSTATE・M=本文・D=DETAIL・n=制約名・t=表・c=列）を
    本番と同じ連鎖にした SQLAlchemy の例外。"""
    return raise_through_sqlalchemy(
        PostgresError.new(fields), statement=statement, params=params, hide_parameters=hide_parameters
    )


def asyncpg_argument_data_error(
    value: object,
    encoding_error: BaseException,
    *,
    statement: str = "SELECT * FROM users WHERE id = $1",
    hide_parameters: bool = True,
) -> DBAPIError:
    """asyncpg が問い合わせの引数の変換に失敗したときの例外（prepared_stmt.pyx と同じ文言・連鎖）。"""
    value_repr = repr(value)
    if len(value_repr) > 40:
        value_repr = value_repr[:40] + "..."
    try:
        raise encoding_error
    except BaseException as caught:  # noqa: BLE001 -- asyncpg と同じく何でも包む
        try:
            raise AsyncpgDataError(
                f"invalid input for query argument $1: {value_repr} ({caught})"
            ) from caught
        except AsyncpgDataError as data_error:
            return raise_through_sqlalchemy(
                data_error, statement=statement, params=(value,), hide_parameters=hide_parameters
            )
