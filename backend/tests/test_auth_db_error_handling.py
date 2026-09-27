"""auth.py の DB 例外の扱い（2026-09-27・INC-2026-09-27-2 の続き）。

- user_signup（commit）・operator_signup（flush〜commit）は、同じメールアドレス・同じ招待コードの同時
  登録で事前確認（SELECT）をすり抜けた後発が一意制約に当たると、未処理例外（500）になり、例外の
  DETAIL（メールアドレス・招待コード）がログと運営アラートに残っていた。事前確認と同じ応答（メールは
  409・招待コードは 403・文言も同じ）にし、ログは型・SQLSTATE・制約名だけにする。それ以外の整合性
  違反は 409 に偽装せず 500 のまま（未処理例外のアラートに載る。本文は要約済み）。
- LINE ログインの新規作成（line_exchange）の一意制約違反のログも同じく値を出さない。

PostgreSQL は本番と同じ連鎖の例外（tests/pg_error_chain.py）で、SQLite は本物の一意制約違反で確かめる。
レート制限（signup は入口で全リクエストを数える方式）は事前確認の 409 と同じく追加の加算・払い戻しが
無いこと＝ハンドラが rate_limit の文脈に触れないことを、既存の tests/test_rate_limit_api.py の signup の
検査とあわせて担保する。
"""
from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import auth as auth_endpoint
from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from tests.pg_error_chain import (
    CHECK_ROW_FIELDS,
    PROBE_EMAIL,
    PROBE_INVITE_CODE,
    PROBE_LINE_USER_ID,
    PROBE_NAME,
    assert_no_probe_values,
    failing,
    pg_server_error,
    production_log_output,
    unique_violation_fields,
    unique_violation_summary,
)

_AUTH_LOGGER = "app.api.v1.endpoints.auth"
_EMAIL_TAKEN = {"detail": "このメールアドレスは既に登録されています。"}
_INVITE_UNAVAILABLE = {"detail": "招待コードが無効、または既に使用されています。"}
_OPERATOR_SIGNUP = {
    "company_name": "漏洩確認片付け株式会社",
    "email": PROBE_EMAIL,
    "password": "operatorpass1",
    "license_number": "第123456789012号",
    "agreed": True,
}


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    # 一意制約以外の IntegrityError は未処理例外（500）として送出し直す。その応答を検査できるようにする。
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == _AUTH_LOGGER]


# ──────────────── user_signup ────────────────


async def test_user_signup_concurrent_duplicate_email_returns_the_precheck_409_on_postgres(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    fields = unique_violation_fields("users", "uq_users_email", "email", PROBE_EMAIL)
    monkeypatch.setattr(db_session, "commit", failing(pg_server_error(fields)))
    with caplog.at_level(logging.WARNING, logger=_AUTH_LOGGER):
        r = await client.post(
            "/api/v1/auth/signup", json={"email": PROBE_EMAIL, "password": "password123", "name": PROBE_NAME}
        )
    assert r.status_code == 409, r.text
    assert r.json() == _EMAIL_TAKEN
    records = _auth_records(caplog)
    assert [record.getMessage() for record in records] == [
        "auth/signup: 同じメールアドレスの同時登録を一意制約で拒否 - "
        + unique_violation_summary("users", "uq_users_email")
    ]
    assert_no_probe_values(production_log_output(records))


async def test_user_signup_precheck_and_race_give_the_same_response(client: AsyncClient):
    """事前確認で弾く通常の重複（従来の経路）と応答が同じであること。"""
    body = {"email": "precheck-dup@example.com", "password": "password123", "name": "先発"}
    assert (await client.post("/api/v1/auth/signup", json=body)).status_code == 201
    r = await client.post("/api/v1/auth/signup", json=body)
    assert r.status_code == 409
    assert r.json() == _EMAIL_TAKEN


async def test_user_signup_concurrent_duplicate_email_returns_409_on_sqlite(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """本物の SQLite の一意制約違反（文言で判別する経路）。先発の登録が commit の直前に入った状態を作る。"""
    email = "race-sqlite@example.com"
    real_commit = db_session.commit

    async def _commit_after_the_first_signup() -> None:
        db_session.add(
            User(email=email, password_hash=hash_password("password123"), name="先発", role="user")
        )
        await real_commit()

    monkeypatch.setattr(db_session, "commit", _commit_after_the_first_signup)
    r = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "password123", "name": "後発"}
    )
    assert r.status_code == 409, r.text
    assert r.json() == _EMAIL_TAKEN
    # 後発の分は巻き戻されている（中途半端な行を残さない）。
    count = await db_session.scalar(select(func.count()).select_from(User).where(User.email == email))
    assert count == 0


async def test_user_signup_other_integrity_errors_stay_500(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """一意制約（users.email）以外の違反は 409 に偽装せず、障害として 500 のまま。"""
    monkeypatch.setattr(db_session, "commit", failing(pg_server_error(CHECK_ROW_FIELDS)))
    r = await client.post(
        "/api/v1/auth/signup", json={"email": PROBE_EMAIL, "password": "password123", "name": PROBE_NAME}
    )
    assert r.status_code == 500
    other_unique = unique_violation_fields("users", "ix_users_line_user_id", "line_user_id", PROBE_LINE_USER_ID)
    monkeypatch.setattr(db_session, "commit", failing(pg_server_error(other_unique)))
    r = await client.post(
        "/api/v1/auth/signup", json={"email": PROBE_EMAIL, "password": "password123", "name": PROBE_NAME}
    )
    assert r.status_code == 500


# ──────────────── operator_signup ────────────────


@pytest.mark.parametrize(
    ("fields", "status_code", "expected_body"),
    [
        (
            unique_violation_fields("operators", "uq_operators_contact_email", "contact_email", PROBE_EMAIL),
            409,
            _EMAIL_TAKEN,
        ),
        (
            unique_violation_fields(
                "operators", "uix_operators_invite_code_notnull", "invite_code", PROBE_INVITE_CODE
            ),
            403,
            _INVITE_UNAVAILABLE,
        ),
    ],
    ids=["contact_email", "invite_code"],
)
@pytest.mark.parametrize("failing_step", ["flush", "commit"])
async def test_operator_signup_concurrent_duplicates_return_the_precheck_response(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fields: dict[str, str],
    status_code: int,
    expected_body: dict,
    failing_step: str,
):
    monkeypatch.setattr(db_session, failing_step, failing(pg_server_error(fields)))
    with caplog.at_level(logging.WARNING, logger=_AUTH_LOGGER):
        r = await client.post("/api/v1/auth/operator/signup", json=_OPERATOR_SIGNUP)
    assert r.status_code == status_code, r.text
    assert r.json() == expected_body
    records = _auth_records(caplog)
    assert [record.getMessage() for record in records] == [
        "auth/operator/signup: 同時登録を一意制約で拒否 - " + unique_violation_summary("operators", fields["n"])
    ]
    assert_no_probe_values(production_log_output(records))


async def test_operator_signup_other_integrity_errors_stay_500(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    fields = unique_violation_fields("operators", "pk_operators", "id", str(uuid.uuid4()))
    monkeypatch.setattr(db_session, "flush", failing(pg_server_error(fields)))
    r = await client.post("/api/v1/auth/operator/signup", json=_OPERATOR_SIGNUP)
    assert r.status_code == 500


async def test_operator_signup_concurrent_duplicate_email_returns_409_on_sqlite(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    email = "race-operator@example.com"
    real_flush = db_session.flush

    async def _flush_after_the_first_signup(*args, **kwargs) -> None:
        db_session.add(
            Operator(
                company_name="先発",
                contact_email=email,
                password_hash=hash_password("operatorpass1"),
                vendor_status="pending",
            )
        )
        await real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", _flush_after_the_first_signup)
    r = await client.post("/api/v1/auth/operator/signup", json={**_OPERATOR_SIGNUP, "email": email})
    assert r.status_code == 409, r.text
    assert r.json() == _EMAIL_TAKEN
    count = await db_session.scalar(
        select(func.count()).select_from(Operator).where(Operator.contact_email == email)
    )
    assert count == 0


# ──────────────── LINE ログインの新規作成（line_exchange） ────────────────


async def test_line_exchange_new_user_conflict_log_has_no_line_user_id_or_email(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    async def _line_user_id(_token: str) -> str:
        return PROBE_LINE_USER_ID

    monkeypatch.setattr(auth_endpoint, "_fetch_line_user_id", _line_user_id)
    fields = unique_violation_fields("users", "ix_users_line_user_id", "line_user_id", PROBE_LINE_USER_ID)
    monkeypatch.setattr(db_session, "commit", failing(pg_server_error(fields)))
    with caplog.at_level(logging.ERROR, logger=_AUTH_LOGGER):
        r = await client.post("/api/v1/auth/line/exchange", json={"line_access_token": "token-x"})
    assert r.status_code == 409, r.text
    records = _auth_records(caplog)
    assert [record.getMessage() for record in records] == [
        "auth/line/exchange: 新規User作成が一意制約違反で失敗 - "
        + unique_violation_summary("users", "ix_users_line_user_id")
    ]
    assert_no_probe_values(production_log_output(records))
