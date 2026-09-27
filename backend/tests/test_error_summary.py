"""例外の要約（app/core/error_summary.py）の単体テスト。

PostgreSQL の例外は tests/pg_error_chain.py で本番と同じクラス・同じ連鎖（asyncpg → SQLAlchemy の
asyncpg アダプタ → SQLAlchemy）にして作る。検査に使う値（メール・氏名・住所・電話番号）は下の定数に
置き、raise の行に直書きしない（トレースバックが表示するソースの行に値が入ると検査が意味を失う）。
"""
from __future__ import annotations

import traceback

import pytest
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel, EmailStr, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import error_summary
from app.core.error_summary import (
    describe_db_error,
    describe_exception,
    format_exception_for_log,
    is_db_exception,
    is_unique_violation,
    is_validation_error,
)
from tests.pg_error_chain import asyncpg_argument_data_error, pg_server_error

_EMAIL = "leak-probe@example.com"
_NAME = "漏洩確認太郎"
_ADDRESS = "東京都千代田区永田町1-7-1"
_PHONE = "090-9876-5432"
_RAW_VALUES = (_EMAIL, "leak-probe", _NAME, _ADDRESS, "永田町", _PHONE, "9876-5432")

_UNIQUE_FIELDS = {
    "S": "ERROR",
    "C": "23505",
    "M": 'duplicate key value violates unique constraint "uq_users_email"',
    "D": f"Key (email)=({_EMAIL}) already exists.",
    "s": "public",
    "t": "users",
    "n": "uq_users_email",
}
_CHECK_FIELDS = {
    "S": "ERROR",
    "C": "23514",
    "M": 'new row for relation "users" violates check constraint "ck_users_role"',
    "D": f"Failing row contains ({_EMAIL}, {_NAME}, {_ADDRESS}, {_PHONE}, $2b$12$hash).",
    "s": "public",
    "t": "users",
    "n": "ck_users_role",
}
_NOT_NULL_FIELDS = {
    "S": "ERROR",
    "C": "23502",
    "M": 'null value in column "name" of relation "users" violates not-null constraint',
    "D": f"Failing row contains ({_EMAIL}, null, {_ADDRESS}).",
    "s": "public",
    "t": "users",
    "c": "name",
}
# 22 系は本文そのものに入力値が入る（DETAIL だけ消しても漏れる）。
_INVALID_TEXT_FIELDS = {
    "S": "ERROR",
    "C": "22P02",
    "M": f'invalid input syntax for type uuid: "{_EMAIL}"',
}
_PARAMS = (_EMAIL, _NAME, _ADDRESS, _PHONE)


def _assert_no_raw_values(output: str) -> None:
    for raw in _RAW_VALUES:
        assert raw not in output, f"{raw!r} が出力に残っている: {output!r}"


# ──────────────── DB 例外の要約 ────────────────


@pytest.mark.parametrize("hide_parameters", [True, False])
def test_unique_violation_is_summarized_to_types_and_identifiers(hide_parameters: bool):
    exc = pg_server_error(_UNIQUE_FIELDS, params=_PARAMS, hide_parameters=hide_parameters)
    # 前提: 例外の文字列そのものには DETAIL の値が入っている（本番で漏れていた経路の再現になっている）。
    assert _EMAIL in str(exc)
    assert _EMAIL in str(exc.orig)
    assert _EMAIL in str(exc.orig.__cause__)
    assert (_NAME in str(exc)) is not hide_parameters

    summary = describe_exception(exc)
    assert summary == (
        "IntegrityError orig=IntegrityError driver=UniqueViolationError"
        " sqlstate=23505 constraint=uq_users_email table=users"
    )
    assert describe_db_error(exc) == summary
    _assert_no_raw_values(summary)


def test_check_violation_row_is_not_kept():
    """CHECK 違反の DETAIL は行全体（氏名・住所・電話番号・パスワードのハッシュ）。"""
    exc = pg_server_error(_CHECK_FIELDS, params=_PARAMS)
    assert _ADDRESS in str(exc)
    summary = describe_exception(exc)
    assert summary == (
        "IntegrityError orig=IntegrityError driver=CheckViolationError"
        " sqlstate=23514 constraint=ck_users_role table=users"
    )
    assert "$2b$" not in summary
    _assert_no_raw_values(summary)


def test_not_null_violation_keeps_the_column_name_as_the_only_clue():
    exc = pg_server_error(_NOT_NULL_FIELDS, params=_PARAMS)
    assert describe_exception(exc) == (
        "IntegrityError orig=IntegrityError driver=NotNullViolationError"
        " sqlstate=23502 constraint=- table=users column=name"
    )


def test_data_error_message_itself_is_not_kept():
    """22P02 は本文（M）に入力値が入る。DB 例外の文言は種類を問わず出さない。"""
    exc = pg_server_error(_INVALID_TEXT_FIELDS, params=(_EMAIL,))
    assert _EMAIL in str(exc)
    summary = describe_exception(exc)
    assert summary == (
        "DBAPIError orig=Error driver=InvalidTextRepresentationError sqlstate=22P02 constraint=-"
    )
    _assert_no_raw_values(summary)


def test_asyncpg_argument_encoding_error_is_summarized():
    """asyncpg が引数の変換に失敗した DataError（"invalid input for query argument $1: '<値>'"）。"""
    exc = asyncpg_argument_data_error(
        _EMAIL, ValueError(f"invalid UUID {_EMAIL!r}: length must be between 32..36 characters")
    )
    assert _EMAIL in str(exc)
    summary = describe_exception(exc)
    assert summary == "DBAPIError orig=Error driver=DataError sqlstate=22000 constraint=-"
    _assert_no_raw_values(summary)


def test_pending_rollback_error_embeds_the_original_message_so_it_is_summarized():
    """PendingRollbackError は本文に「元の例外」の文言（DETAIL を含む）を丸ごと入れる。"""
    original = pg_server_error(_UNIQUE_FIELDS)
    exc = PendingRollbackError(
        "This Session's transaction has been rolled back due to a previous exception during flush."
        f" Original exception was: {original}"
    )
    assert _EMAIL in str(exc)
    assert is_db_exception(exc)
    assert describe_exception(exc) == "PendingRollbackError sqlstate=- constraint=-"


async def test_sqlite_integrity_error_is_summarized_and_unique_violation_is_detected():
    """テストで使う SQLite の本物の例外（SQLSTATE・制約名は無い）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE people (email TEXT UNIQUE, name TEXT)"))
            values = {"email": _EMAIL, "name": _NAME}
            await conn.execute(text("INSERT INTO people VALUES (:email, :name)"), values)
            with pytest.raises(IntegrityError) as excinfo:
                await conn.execute(text("INSERT INTO people VALUES (:email, :name)"), values)
    finally:
        await engine.dispose()
    exc = excinfo.value
    assert _EMAIL in str(exc)  # hide_parameters が無いと SQL の引数が文言に入る
    assert describe_exception(exc) == "IntegrityError orig=IntegrityError sqlstate=- constraint=-"
    assert is_unique_violation(exc, {"uq_people_email"}, sqlite_columns="people.email")
    assert not is_unique_violation(exc, {"uq_people_email"}, sqlite_columns="people.name")
    # 列名の前方一致では判定しない（people.email_x 等を取り違えない）。
    assert not is_unique_violation(exc, {"uq_people_email"}, sqlite_columns="people.e")


def test_is_unique_violation_requires_the_sqlstate_and_the_constraint_name():
    unique = pg_server_error(_UNIQUE_FIELDS)
    assert is_unique_violation(unique, {"uq_users_email", "ix_users_email"}, sqlite_columns="users.email")
    assert not is_unique_violation(unique, {"uq_operators_contact_email"}, sqlite_columns="users.email")
    check = pg_server_error(_CHECK_FIELDS)
    assert not is_unique_violation(check, {"ck_users_role"}, sqlite_columns="users.email")
    assert not is_unique_violation(ValueError("x"), {"uq_users_email"}, sqlite_columns="users.email")


def test_identifiers_that_do_not_look_like_schema_names_are_not_echoed():
    """制約名・表名・SQLSTATE も、想定の形（ASCII の識別子・5 桁）でなければ ``?`` にする。"""
    exc = pg_server_error(
        {"C": "23505", "M": "x", "n": f'uq "{_EMAIL}"', "t": "利用者", "c": "a" * 64}
    )
    assert describe_exception(exc) == (
        "IntegrityError orig=IntegrityError driver=UniqueViolationError"
        " sqlstate=23505 constraint=? table=? column=?"
    )
    malformed = pg_server_error({"C": "23505", "M": "x", "n": "uq_users_email"})
    malformed.orig.sqlstate = "23505; DROP"
    assert "sqlstate=?" in describe_exception(malformed)


# ──────────────── 検証エラー・それ以外の例外 ────────────────


class _Probe(BaseModel):
    email: EmailStr
    name: str


def _probe_validation_error() -> ValidationError:
    try:
        _Probe.model_validate({"email": _PHONE, "address": _ADDRESS, _NAME: 1})
    except ValidationError as exc:
        return exc
    raise AssertionError("検証エラーにならなかった")


def test_pydantic_validation_error_keeps_only_locations_and_types():
    exc = _probe_validation_error()
    assert _PHONE in str(exc)
    summary = describe_exception(exc)
    assert summary == "ValidationError model=_Probe errors=2 at=email:value_error, name:missing"
    _assert_no_raw_values(summary)


def test_response_validation_error_does_not_echo_the_parent_object():
    """応答モデルの検証失敗は、欠けた項目の親オブジェクト（利用者の行）を input に丸ごと入れる。"""
    errors = [
        {"type": "missing", "loc": ("response", "name"), "msg": "Field required",
         "input": {"email": _EMAIL, "address": _ADDRESS, "phone": _PHONE}},
        # dict のキー（＝入力値）が位置に入る場合も項目名として出さない。
        {"type": "int_type", "loc": ("response", "items", _EMAIL, 0), "msg": "x", "input": _NAME},
    ]
    exc = ResponseValidationError(errors)
    assert _ADDRESS in str(exc)
    assert is_validation_error(exc)
    summary = describe_exception(exc)
    assert summary == "ResponseValidationError errors=2 at=response.name:missing, response.items.?.0:int_type"
    _assert_no_raw_values(summary)


def test_validation_summary_lists_at_most_ten_items():
    errors = [{"type": "missing", "loc": ("body", f"f{i}")} for i in range(12)]
    summary = describe_exception(ResponseValidationError(errors))
    assert summary.endswith("body.f9:missing（ほか 2 件）")
    assert "f10" not in summary


def test_other_exceptions_keep_type_and_message_as_before():
    """DB 例外・検証エラー以外は従来どおり「型: 文言」（外部 API の失敗理由などは文言が要る）。"""
    assert describe_exception(ValueError("Brevo 429 Too Many Requests")) == (
        "ValueError: Brevo 429 Too Many Requests"
    )
    assert describe_exception(RuntimeError("x" * 500)) == "RuntimeError: " + "x" * 200
    assert describe_exception(RuntimeError("x" * 500), limit=300) == "RuntimeError: " + "x" * 300

    class _BrokenStr(Exception):
        def __str__(self) -> str:
            raise RuntimeError("壊れた __str__")

    assert describe_exception(_BrokenStr()) == "_BrokenStr: <_BrokenStr の文言を取得できません>"


# ──────────────── トレースバック ────────────────


def test_traceback_keeps_frames_and_replaces_only_db_messages():
    exc = pg_server_error(_UNIQUE_FIELDS, params=_PARAMS, hide_parameters=False)
    text_out = format_exception_for_log(exc)
    _assert_no_raw_values(text_out)
    lines = text_out.splitlines()
    assert lines[0] == "Traceback (most recent call last):"
    assert text_out.count("The above exception was the direct cause of the following exception:") == 2
    assert "asyncpg.exceptions.UniqueViolationError: sqlstate=23505 constraint=uq_users_email table=users" in lines
    assert (
        "sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.IntegrityError:"
        " driver=UniqueViolationError sqlstate=23505 constraint=uq_users_email table=users"
    ) in lines
    assert lines[-1] == (
        "sqlalchemy.exc.IntegrityError: orig=IntegrityError driver=UniqueViolationError"
        " sqlstate=23505 constraint=uq_users_email table=users"
    )
    # 発生箇所（フレーム）は残る。
    assert 'pg_error_chain.py", line' in text_out
    assert not text_out.endswith("\n")


def test_traceback_hides_the_cause_of_a_db_error():
    """asyncpg が値の変換に失敗した元の例外（DataError の __cause__）も、文言に値が入るため伏せる。"""
    exc = asyncpg_argument_data_error(_EMAIL, ValueError(f"invalid UUID {_EMAIL!r}"))
    text_out = format_exception_for_log(exc)
    _assert_no_raw_values(text_out)
    assert "ValueError: （DB 例外の原因のため文言を省略）" in text_out.splitlines()
    assert "asyncpg.exceptions.DataError: sqlstate=22000 constraint=-" in text_out.splitlines()


def test_traceback_keeps_non_db_messages_in_the_chain():
    """DB 例外を処理中に起きた別の例外（context）や、DB 例外から送出した例外の文言は従来どおり。"""
    db_error = pg_server_error(_UNIQUE_FIELDS)
    try:
        try:
            raise db_error
        except IntegrityError:
            raise KeyError("profile")
    except KeyError as exc:
        text_out = format_exception_for_log(exc)
    _assert_no_raw_values(text_out)
    assert "During handling of the above exception, another exception occurred:" in text_out
    assert text_out.splitlines()[-1] == "KeyError: 'profile'"


def test_traceback_of_non_db_exceptions_is_identical_to_the_standard_one():
    try:
        try:
            raise ValueError("元の例外")
        except ValueError as cause:
            raise RuntimeError("包み直した例外") from cause
    except RuntimeError as exc:
        expected = "".join(traceback.format_exception(exc)).rstrip("\n")
        assert format_exception_for_log(exc) == expected


def test_traceback_summarizes_validation_errors():
    exc = _probe_validation_error()
    text_out = format_exception_for_log(exc)
    _assert_no_raw_values(text_out)
    assert text_out.splitlines()[-1] == (
        "pydantic_core._pydantic_core.ValidationError: model=_Probe errors=2"
        " at=email:value_error, name:missing"
    )


def test_traceback_renders_db_errors_inside_exception_groups():
    group = ExceptionGroup("バックグラウンド処理", [pg_server_error(_CHECK_FIELDS), ValueError("別件")])
    text_out = format_exception_for_log(group)
    _assert_no_raw_values(text_out)
    assert "ExceptionGroup: バックグラウンド処理 (2 sub-exceptions)" in text_out
    assert "sqlstate=23514 constraint=ck_users_role" in text_out
    assert "ValueError: 別件" in text_out


def test_traceback_stops_on_cycles_and_handles_none():
    first = ValueError("a")
    second = ValueError("b")
    first.__context__ = second
    second.__context__ = first
    assert format_exception_for_log(first).count("ValueError") == 2
    assert format_exception_for_log(None) == "NoneType: None"


def test_traceback_falls_back_to_type_names_when_formatting_fails(monkeypatch: pytest.MonkeyPatch):
    """ログの書式から呼ばれるため例外は出さない。失敗したら型名の並びだけ（隠す側に倒す）。"""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("format_tb failed")

    monkeypatch.setattr(error_summary.traceback, "format_tb", _boom)
    exc = pg_server_error(_UNIQUE_FIELDS, params=_PARAMS, hide_parameters=False)
    text_out = format_exception_for_log(exc)
    assert text_out == (
        "（トレースバックを整形できなかったため例外の型だけを記録）sqlalchemy.exc.IntegrityError"
        " <- sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.IntegrityError"
        " <- asyncpg.exceptions.UniqueViolationError"
    )
