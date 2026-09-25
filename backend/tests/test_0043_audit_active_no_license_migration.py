"""0043_audit_active_no_license（許可証未提出の active 業者の件数監査・読み取りのみ）の回帰テスト。

test_0042 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため
``async def`` にはできない）で同期テストにしている。

- 「vendor_status='active' かつ license_image_uploaded_at が NULL かつ deleted_at が NULL」の
  業者だけを数えて INFO に出す（pending・許可証提出済み・削除済みは数えない）。
- 値を一切変更しない（upgrade 前後で operators の全行が同じ。UPDATE/INSERT/DELETE・DDL を
  発行しない）。0 件でもログを出す。downgrade は no-op で、往復しても値は変わらない。
- head が 0043 の単独チェーンで、リビジョン ID が 32 文字以内（head の固定は最新リビジョンの
  テストである本ファイルが持つ）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_LOGGER_NAME = "alembic.versions.0043_audit_active_no_license"

# 0042 適用済み相当の最小スキーマ（0043 が読む operators の、判定に使う列のみ）。
_PRE_0043_SCHEMA_SQL = """
CREATE TABLE operators (
    id CHAR(32) PRIMARY KEY,
    vendor_status VARCHAR(20) NOT NULL,
    license_image_uploaded_at TIMESTAMP,
    deleted_at TIMESTAMP
);
"""


def _alembic_config() -> Config:
    # alembic.ini を読ませない理由は tests/test_0028_migration_dedup.py と同じ
    # （ConfigParser の既定 encoding が cp932 環境で ini 内の日本語を壊す）。
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("path_separator", "os")
    return cfg


def _run_capturing_sql(run) -> list[str]:
    """run() の間に実行された SQL 文を集める（env.py が作るエンジンも含め、全エンジンが対象）。"""
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _capture)
    try:
        run()
    finally:
        event.remove(Engine, "before_cursor_execute", _capture)
    return statements


def _operators(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, vendor_status, license_image_uploaded_at, deleted_at FROM operators ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _logs(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOGGER_NAME and r.levelno == logging.INFO
    ]


def _expected_log(count: int) -> str:
    return (
        f"0043: 許可証画像が未提出のまま active な業者（未削除・停止中を含む）は {count} 件でした"
        "（値は変更していません。1 件以上なら運営から許可証の提出を依頼すること）。"
    )


def _prepare(db_path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_PRE_0043_SCHEMA_SQL)
        conn.executemany(
            "INSERT INTO operators (id, vendor_status, license_image_uploaded_at, deleted_at)"
            " VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_0043_logs_count_of_active_operators_without_license_and_changes_nothing(
    tmp_path, monkeypatch, caplog
):
    db_path = tmp_path / "0043.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        uploaded = "2026-09-01 00:00:00"
        deleted = "2026-09-10 00:00:00"
        rows = [
            # 数える: active・許可証なし・未削除（旧仕様の招待コード即 active 登録を想定）。
            (uuid.uuid4().hex, "active", None, None),
            (uuid.uuid4().hex, "active", None, None),
            # 数えない: 許可証提出済みの active。
            (uuid.uuid4().hex, "active", uploaded, None),
            # 数えない: 削除済み（匿名化済みで入札できない）。
            (uuid.uuid4().hex, "active", None, deleted),
            # 数えない: active 以外（承認前・制限中・却下・停止）。
            (uuid.uuid4().hex, "pending", None, None),
            (uuid.uuid4().hex, "limited", None, None),
            (uuid.uuid4().hex, "rejected", None, None),
            (uuid.uuid4().hex, "suspended", None, None),
        ]
        _prepare(db_path, rows)
        before = _operators(db_path)

        cfg = _alembic_config()
        command.stamp(cfg, "0042_review_verdict_contract")
        statements = _run_capturing_sql(lambda: command.upgrade(cfg, "0043_audit_active_no_license"))

        assert _logs(caplog) == [_expected_log(2)]
        # 読み取りのみ: operators への書き込み・DDL を発行しない（alembic_version の更新は除く）。
        writes = [
            s
            for s in statements
            if "alembic_version" not in s.lower()
            and s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE", "ALTER", "CREATE", "DROP"))
        ]
        assert writes == []
        assert any("FROM operators" in s for s in statements), "件数の SELECT を捕捉できていること"
        assert _operators(db_path) == before, "値を変更しない"

        # downgrade は no-op、再 upgrade も同じ件数を出すだけで値は変わらない（冪等）。
        command.downgrade(cfg, "0042_review_verdict_contract")
        assert _operators(db_path) == before
        caplog.clear()
        command.upgrade(cfg, "0043_audit_active_no_license")
        assert _logs(caplog) == [_expected_log(2)]
        assert _operators(db_path) == before
    finally:
        get_settings.cache_clear()


def test_0043_logs_zero_when_no_active_operator_lacks_license(tmp_path, monkeypatch, caplog):
    """該当 0 件でも「確認した」事実を残すため INFO を出すこと。"""
    db_path = tmp_path / "0043_zero.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        _prepare(
            db_path,
            [
                (uuid.uuid4().hex, "active", "2026-09-01 00:00:00", None),
                (uuid.uuid4().hex, "pending", None, None),
            ],
        )
        cfg = _alembic_config()
        command.stamp(cfg, "0042_review_verdict_contract")
        command.upgrade(cfg, "0043_audit_active_no_license")
        assert _logs(caplog) == [_expected_log(0)]
    finally:
        get_settings.cache_clear()


def test_0043_is_the_single_head_chained_from_0042():
    """0043 が単独の head として 0042 に正しく連鎖していること（分岐の防止）。"""
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0043_audit_active_no_license"]
    rev_0043 = script.get_revision("0043_audit_active_no_license")
    assert rev_0043.down_revision == "0042_review_verdict_contract"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0043.revision) <= 32
