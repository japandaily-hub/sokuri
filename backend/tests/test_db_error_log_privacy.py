"""DB 例外の文言（PostgreSQL の DETAIL・SQL の引数）がログと運営アラートに残らないことの結合テスト。

INC-2026-09-27-2 の続き（2026-09-27 のログ点検で判明した残りの穴）。PostgreSQL の例外文は DETAIL
（一意制約違反のキーの値・CHECK 違反の行全体）を含み、hide_parameters では消えない。各経路で本番と
同じ連鎖の例外（tests/pg_error_chain.py）を起こし、次を確かめる:

- 呼び出し側がログの本文に渡す文字列（record.getMessage()）が型・SQLSTATE・制約名だけであること
- 本番の出力（AppLogFormatter＝トレースバックを含む）に値が残らず、発生箇所のトレースバックは残ること
- 運営アラートの本文（alerts.send_alert の引数＝LINE・メールへそのまま送られる）に値が無いこと

auth.py（signup の同時登録・LINE の新規作成）は tests/test_auth_db_error_handling.py。
検査に使う値は定数に置き、raise の行に直書きしない（トレースバックはソースの行を表示するため）。
"""
from __future__ import annotations

import asyncio
import io
import logging
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main_module
from app.api.v1.endpoints import contact as contact_endpoint
from app.api.v1.router import api_router
from app.core import app_logging
from app.core.alert_middleware import ServerErrorAlertMiddleware
from app.core.app_logging import AppLogFormatter
from app.db.session import get_session
from app.services import alerts, reminders
from tests.pg_error_chain import (
    CHECK_ROW_FIELDS,
    CHECK_ROW_SUMMARY,
    PROBE_ADDRESS,
    PROBE_EMAIL,
    PROBE_LINE_USER_ID,
    PROBE_NAME,
    PROBE_PHONE,
    assert_no_probe_values,
    failing,
    pg_server_error,
    production_log_output,
)


def _records(caplog: pytest.LogCaptureFixture, logger_name: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == logger_name]


@pytest.fixture
def sent_alerts(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """運営アラートの送信内容（LINE・メールへそのまま送られる本文）を記録する。"""
    sent: list[dict] = []

    def _record_alert(title: str, body: str, *, severity: str = "critical", key: str | None = None):
        sent.append({"title": title, "body": body, "severity": severity, "key": key})

        async def _done() -> bool:
            return True

        return _done()

    monkeypatch.setattr(alerts, "send_alert", _record_alert)
    return sent


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ──────────────── 出力直前の安全網（app/core/app_logging.py） ────────────────


def test_formatter_summarizes_db_error_arguments_and_traceback():
    """呼び出し側が例外オブジェクトをそのまま渡しても、本文とトレースバックの両方から値が消える。"""
    exc = pg_server_error(CHECK_ROW_FIELDS, params=(PROBE_EMAIL, PROBE_NAME), hide_parameters=False)
    exc_info = (type(exc), exc, exc.__traceback__)
    record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "保存に失敗 - %s", (exc,), exc_info)
    output = AppLogFormatter().format(record)
    assert_no_probe_values(output)
    lines = output.split("\n")
    assert lines[0] == f"ERROR [app.x] 保存に失敗 - {CHECK_ROW_SUMMARY}"
    assert lines[1] == "  | Traceback (most recent call last):"
    assert lines[-1] == (
        "  | sqlalchemy.exc.IntegrityError: orig=IntegrityError driver=CheckViolationError"
        " sqlstate=23514 constraint=ck_users_role table=users"
    )
    # 本文そのものが例外、辞書形式の引数（logger.error("%(error)s", {"error": exc}) と同じ形）でも同じ。
    for msg, args in ((exc, ()), ("失敗 %(error)s", ({"error": exc},))):
        rendered = AppLogFormatter().format(
            logging.LogRecord("app.x", logging.ERROR, __file__, 1, msg, args, None)
        )
        assert_no_probe_values(rendered)
        assert CHECK_ROW_SUMMARY in rendered


def test_formatter_does_not_reuse_a_raw_traceback_cached_by_another_formatter():
    """先に別の書式（標準の Formatter）が record.exc_text に生のトレースバックを入れていても使い回さない。"""
    exc = pg_server_error(CHECK_ROW_FIELDS)
    record = logging.LogRecord(
        "app.x", logging.ERROR, __file__, 1, "失敗", (), (type(exc), exc, exc.__traceback__)
    )
    logging.Formatter().format(record)
    assert PROBE_ADDRESS in (record.exc_text or "")  # 前提: 標準の書式は DETAIL をそのまま出す
    output = AppLogFormatter().format(record)
    assert_no_probe_values(output)
    assert "sqlstate=23514 constraint=ck_users_role" in output


def test_uvicorn_unhandled_exception_traceback_hides_db_values():
    """未処理例外のトレースバック（uvicorn.error の "Exception in ASGI application"）。"""
    exc = pg_server_error(CHECK_ROW_FIELDS, params=(PROBE_EMAIL, PROBE_NAME), hide_parameters=False)
    record = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        __file__,
        1,
        "Exception in ASGI application\n",
        (),
        (type(exc), exc, exc.__traceback__),
    )
    assert app_logging._UvicornTracebackFilter().filter(record) is True
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s:    %(message)s"))
    handler.handle(record)
    output = stream.getvalue()
    assert_no_probe_values(output)
    assert output.startswith("ERROR:    Exception in ASGI application")
    assert "  | sqlalchemy.exc.IntegrityError: orig=IntegrityError" in output


def test_probe_errors_really_carry_the_values_in_their_text():
    """ここで使う例外は、要約しなければ値が出る（各テストが漏れを検出できることの前提）。"""
    exc = pg_server_error(CHECK_ROW_FIELDS)
    stream = io.StringIO()
    record = logging.LogRecord(
        "app.x", logging.ERROR, __file__, 1, "%s", (exc,), (type(exc), exc, exc.__traceback__)
    )
    logging.StreamHandler(stream).handle(record)
    assert PROBE_ADDRESS in stream.getvalue()
    # asyncpg の例外の文言（DETAIL）には版によらず入る。SQLAlchemy 2.0 は SQLAlchemy の例外の文言にも
    # 入れるが、2.1 の asyncpg アダプタは入れない（DETAIL はアダプタ例外の detail 属性に移った）。
    assert PROBE_PHONE in str(exc.orig.__cause__)


# ──────────────── 未処理例外のアラート（app/core/alert_middleware.py） ────────────────


class _ProfileOut(BaseModel):
    email: str
    name: str


async def test_unhandled_db_error_and_response_validation_alerts_have_no_values(sent_alerts: list[dict]):
    app = FastAPI()

    @app.get("/boom")
    async def _boom() -> None:
        raise pg_server_error(CHECK_ROW_FIELDS, params=(PROBE_EMAIL, PROBE_NAME), hide_parameters=False)

    @app.get("/profile", response_model=_ProfileOut)
    async def _profile() -> dict:
        # 応答モデルの検証失敗。FastAPI の ResponseValidationError は欠けた項目の親（行）を丸ごと抱える。
        return {"email": PROBE_EMAIL, "address": PROBE_ADDRESS, "phone": PROBE_PHONE}

    app.add_middleware(ServerErrorAlertMiddleware)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/boom")).status_code == 500
        assert (await client.get("/profile")).status_code == 500
    await asyncio.sleep(0)

    unhandled = [alert for alert in sent_alerts if alert["title"] == "未処理の例外が発生しました"]
    assert [alert["body"] for alert in unhandled] == [
        f"GET /boom\n{CHECK_ROW_SUMMARY}",
        "GET /profile\nResponseValidationError errors=1 at=response.name:missing",
    ]
    for alert in sent_alerts:
        assert_no_probe_values(alert["body"])


# ──────────────── 保存失敗のログ（users.py ほか同じ書き方の各所の代表） ────────────────


async def test_bank_account_save_failure_log_keeps_traceback_without_db_values(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": "bank-privacy@example.com", "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    monkeypatch.setattr(db_session, "commit", failing(pg_server_error(CHECK_ROW_FIELDS)))
    payload = {
        "bank_name": "カタヅケ銀行",
        "branch_name": "本店",
        "account_type": "普通",
        "account_number": "1234567",
        "account_holder_kana": "カタヅケ タロウ",
        "current_password": "password123",
    }
    with caplog.at_level(logging.ERROR, logger="app.api.v1.endpoints.users"):
        r = await client.put(
            "/api/v1/users/me/bank-account", json=payload, headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 500, r.text

    records = _records(caplog, "app.api.v1.endpoints.users")
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("users/me/bank-account PUT: 保存に失敗 - user_id=")
    assert message.endswith(f" - {CHECK_ROW_SUMMARY}")
    assert records[0].exc_info is not None  # 発生箇所のトレースバックは残す
    output = production_log_output(records)
    assert_no_probe_values(output)
    assert "1234567" not in output
    assert "  | Traceback (most recent call last):" in output


async def test_contact_save_failure_log_and_alert_have_no_db_values(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sent_alerts: list[dict],
):
    contact_endpoint._recent_notification_timestamps.clear()
    monkeypatch.setattr(db_session, "commit", failing(pg_server_error(CHECK_ROW_FIELDS)))
    payload = {
        "name": PROBE_NAME,
        "email": PROBE_EMAIL,
        "category": "trouble",
        "message": f"住所は{PROBE_ADDRESS}です",
    }
    try:
        with caplog.at_level(logging.ERROR, logger="app.api.v1.endpoints.contact"):
            r = await client.post("/api/v1/contact", json=payload)
    finally:
        contact_endpoint._recent_notification_timestamps.clear()
    assert r.status_code == 202, r.text  # 保存に失敗してもメール送信と 202 は維持する（従来どおり）

    records = [
        record
        for record in _records(caplog, "app.api.v1.endpoints.contact")
        if "お問い合わせの保存に失敗しました" in record.getMessage()
    ]
    assert [record.getMessage() for record in records] == [
        f"contact: お問い合わせの保存に失敗しました（メール送信は継続） - {CHECK_ROW_SUMMARY}"
    ]
    assert_no_probe_values(production_log_output(records))
    persist_alerts = [alert for alert in sent_alerts if alert["key"] == "contact-persist-failed"]
    assert len(persist_alerts) == 1
    assert persist_alerts[0]["body"].endswith(f"直近のエラー: {CHECK_ROW_SUMMARY}")
    assert_no_probe_values(persist_alerts[0]["body"])


# ──────────────── 起動時・定期処理（main.py・services/reminders.py） ────────────────


async def test_seed_and_startup_sweep_failure_logs_have_no_db_values(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(main_module, "seed_channels_and_rules", failing(pg_server_error(CHECK_ROW_FIELDS)))
    monkeypatch.setattr(main_module, "sweep_stale_pending_ai", failing(pg_server_error(CHECK_ROW_FIELDS)))
    with caplog.at_level(logging.ERROR, logger="app.main"):
        await main_module._run_seed()
        await main_module._run_stale_pending_ai_sweep()
    records = [record for record in _records(caplog, "app.main") if record.levelno >= logging.ERROR]
    assert [record.getMessage() for record in records] == [
        f"seed: チャネルシード失敗（サービスは継続） - {CHECK_ROW_SUMMARY}",
        f"cases: 起動時 pending スイープ失敗（サービスは継続） - {CHECK_ROW_SUMMARY}",
    ]
    assert all(record.exc_info is not None for record in records)
    assert_no_probe_values(production_log_output(records))


async def test_reminder_loop_failure_log_and_alert_have_no_db_values(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sent_alerts: list[dict],
):
    monkeypatch.setattr(main_module, "run_reminders", failing(pg_server_error(CHECK_ROW_FIELDS)))

    async def _stop_after_first_round(_seconds: float) -> None:
        raise asyncio.CancelledError

    # main.py の asyncio 参照だけを差し替えて1周で止める（asyncio モジュール自体は触らない）。
    monkeypatch.setattr(
        main_module,
        "asyncio",
        SimpleNamespace(sleep=_stop_after_first_round, CancelledError=asyncio.CancelledError),
    )
    with caplog.at_level(logging.ERROR, logger="app.main"), pytest.raises(asyncio.CancelledError):
        await main_module._run_reminder_loop(SimpleNamespace(reminder_interval_seconds=3600))

    records = [record for record in _records(caplog, "app.main") if record.levelno >= logging.ERROR]
    assert [record.getMessage() for record in records] == [
        f"reminders: 定期実行に失敗（次周期で再試行） - {CHECK_ROW_SUMMARY}"
    ]
    assert_no_probe_values(production_log_output(records))
    loop_alerts = [alert for alert in sent_alerts if alert["key"] == "reminders_loop_failed"]
    assert len(loop_alerts) == 1
    assert loop_alerts[0]["body"].endswith(f"直近のエラー: {CHECK_ROW_SUMMARY}")
    assert_no_probe_values(loop_alerts[0]["body"])


async def test_reminder_dispatch_failure_log_and_alert_have_no_db_values(
    caplog: pytest.LogCaptureFixture, sent_alerts: list[dict]
):
    dispatch = failing(pg_server_error(CHECK_ROW_FIELDS))
    with caplog.at_level(logging.ERROR, logger="app.services.reminders"):
        await reminders._dispatch_or_warn(
            dispatch, PROBE_LINE_USER_ID, PROBE_EMAIL, context="bids_pending case_id=c-1"
        )
    records = _records(caplog, "app.services.reminders")
    assert [record.getMessage() for record in records] == [
        "reminders: 通知の送信に失敗（マーカー確定済みのため再送しない） - bids_pending case_id=c-1"
        f" - {CHECK_ROW_SUMMARY}"
    ]
    assert_no_probe_values(production_log_output(records))
    assert [alert["body"] for alert in sent_alerts] == [
        "掘り起こし通知が1件届いていない可能性があります（再送はされません）。"
        f"対象: bids_pending case_id=c-1 / エラー: {CHECK_ROW_SUMMARY}"
    ]
