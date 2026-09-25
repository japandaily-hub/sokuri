"""0039_sessions_revoked_at: users / operators への失効境界の列追加と、適用時点で停止中の
アカウントへの境界設定（backfill）の回帰テスト。

test_0037_0038_migrations.py と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を
呼ぶため ``async def`` にはできない）で同期テストにしている。

- 両テーブルに sessions_revoked_at（NULL 可）が追加される。
- 適用時点で停止中（is_suspended=true）の行だけに適用時刻（アプリ側の UTC）が入り、
  停止していない行は NULL のまま（デプロイ前から停止中のアカウントも、解除後に停止前の
  トークンが復活しない）。既存の列の値は変わらない。件数は監査ログに残る。
- downgrade で列が消える。
- head が 0039 の単独チェーン（0039 → 0038）で、リビジョン ID が 32 文字以内。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_REVISION = "0039_sessions_revoked_at"
_DOWN_REVISION = "0038_clear_deleted_op_line_ids"

# 0038 適用済み相当の最小スキーマ（0039 が触る2テーブルの、判定に使う列のみ）。
_PRE_0039_SCHEMA_SQL = """
CREATE TABLE users (
    id CHAR(32) PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    is_suspended BOOLEAN NOT NULL DEFAULT 0
);
CREATE TABLE operators (
    id CHAR(32) PRIMARY KEY,
    contact_email TEXT NOT NULL UNIQUE,
    is_suspended BOOLEAN NOT NULL DEFAULT 0
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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')")}


def _stored_utc(raw: str) -> datetime:
    """SQLite に保存された tz なしの UTC 文字列を aware な datetime に戻す。"""
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


def test_0039_adds_columns_and_backfills_only_currently_suspended_accounts(
    tmp_path, monkeypatch, caplog
):
    db_path = tmp_path / "0039_sessions_revoked_at.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=f"alembic.versions.{_REVISION}")
    get_settings.cache_clear()
    try:
        suspended_user, active_user = uuid.uuid4().hex, uuid.uuid4().hex
        suspended_op, active_op = uuid.uuid4().hex, uuid.uuid4().hex
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0039_SCHEMA_SQL)
            conn.executemany(
                "INSERT INTO users (id, email, is_suspended) VALUES (?, ?, ?)",
                [
                    (suspended_user, "suspended@example.com", True),
                    (active_user, "active@example.com", False),
                ],
            )
            conn.executemany(
                "INSERT INTO operators (id, contact_email, is_suspended) VALUES (?, ?, ?)",
                [
                    (suspended_op, "suspended-op@example.com", True),
                    (active_op, "active-op@example.com", False),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, _DOWN_REVISION)
        before = datetime.now(timezone.utc)
        command.upgrade(cfg, _REVISION)
        after = datetime.now(timezone.utc)

        conn = sqlite3.connect(str(db_path))
        try:
            for table in ("users", "operators"):
                assert "sessions_revoked_at" in _columns(conn, table), table

            users = {
                row[0]: row[1:]
                for row in conn.execute("SELECT id, sessions_revoked_at, is_suspended, email FROM users")
            }
            operators = {
                row[0]: row[1:]
                for row in conn.execute(
                    "SELECT id, sessions_revoked_at, is_suspended, contact_email FROM operators"
                )
            }
            # 停止していない行は境界なし（一度も停止されていない扱い）のまま。
            assert users[active_user] == (None, 0, "active@example.com")
            assert operators[active_op] == (None, 0, "active-op@example.com")
            # 停止中の行だけに適用時刻が入り、停止状態などの既存の値は変わらない。
            for boundary_raw, is_suspended, _ in (users[suspended_user], operators[suspended_op]):
                assert boundary_raw is not None, "停止中のアカウントに失効境界が設定されていない"
                assert before <= _stored_utc(boundary_raw) <= after
                assert is_suspended == 1
            assert users[suspended_user][2] == "suspended@example.com"
            assert operators[suspended_op][2] == "suspended-op@example.com"
        finally:
            conn.close()

        audit_logs = [
            r.getMessage() for r in caplog.records if r.name == f"alembic.versions.{_REVISION}"
        ]
        assert len(audit_logs) == 1
        assert "依頼者 1 件" in audit_logs[0]
        assert "業者 1 件" in audit_logs[0]

        command.downgrade(cfg, _DOWN_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            for table in ("users", "operators"):
                assert "sessions_revoked_at" not in _columns(conn, table), table
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone() == (2,)
            assert conn.execute("SELECT COUNT(*) FROM operators").fetchone() == (2,)
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0039_is_the_single_head_chained_from_0038():
    """0039 が単独の head として 0038 に正しく連鎖していること（分岐の防止）。

    新しいリビジョンを足すときは、本テストの head 固定を「単一 head のみ」の検証へ緩め、
    厳密な head の検証は新しいリビジョンのテストへ移す（0036・0038 のテストと同じ運用）。
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    # head そのものの固定は最新リビジョンのテストへ移設（0040_review_verdict 以降の追加で本テストが
    # 壊れないようにする。test_0037_0038_migrations.py と同じ流儀）。ここでは分岐が無いことだけを見る。
    assert len(script.get_heads()) == 1
    revision = script.get_revision(_REVISION)
    assert revision.down_revision == _DOWN_REVISION
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(revision.revision) <= 32
