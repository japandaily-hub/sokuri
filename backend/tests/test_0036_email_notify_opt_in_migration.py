"""0036_email_notify_opt_in: users への列追加とデフォルト値の回帰テスト。

test_0035_bids_pending_backfill.py と同じ理由（alembic の env.py が内部で
``asyncio.run()`` を呼ぶため ``async def`` にはできない）。

0033/0035 と異なり本バージョンは backfill の UPDATE を伴わない
（``server_default=true`` で全既存行が列追加と同時に true を持つ）ため、
検証すべきは「既存行が NULL のまま残らないこと」「downgrade で列が消えること」
「head まで単独チェーンとして到達すること」の3点。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

# 0035 適用済み相当の最小スキーマ（0036 の upgrade() が add_column するのに
# 必要な users テーブルのみ）。
_PRE_0036_SCHEMA_SQL = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


def test_upgrade_defaults_existing_rows_to_opt_in_true(tmp_path, monkeypatch):
    """適用前から存在する行も email_notify_opt_in=true・updated_at=NULL で埋まる。"""
    db_path = tmp_path / "0036_email_notify_opt_in.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0036_SCHEMA_SQL)
            existing_user_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users (id, email) VALUES (?, ?)",
                (existing_user_id, "existing@example.com"),
            )
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0035_bids_pending_reminder")

        command.upgrade(cfg, "0036_email_notify_opt_in")

        conn = sqlite3.connect(str(db_path))
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info('users')")}
            assert "email_notify_opt_in" in columns
            assert "email_notify_updated_at" in columns

            row = conn.execute(
                "SELECT email_notify_opt_in, email_notify_updated_at FROM users WHERE id = ?",
                (existing_user_id,),
            ).fetchone()
            assert row is not None
            # SQLite は Boolean を 0/1 の INTEGER として保存する。
            assert row[0] == 1, "既存ユーザーが opt-in=true のまま維持されていない"
            assert row[1] is None, "未選択の既存ユーザーの updated_at は NULL のままであるべき"

            # 新規挿入時（列を明示しない INSERT）も NOT NULL 違反にならず true が入る。
            new_user_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users (id, email) VALUES (?, ?)",
                (new_user_id, "new@example.com"),
            )
            conn.commit()
            new_row = conn.execute(
                "SELECT email_notify_opt_in FROM users WHERE id = ?", (new_user_id,)
            ).fetchone()
            assert new_row[0] == 1
        finally:
            conn.close()

        command.downgrade(cfg, "0035_bids_pending_reminder")
        conn = sqlite3.connect(str(db_path))
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info('users')")}
            assert "email_notify_opt_in" not in columns
            assert "email_notify_updated_at" not in columns
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0036_is_chained_from_0035_on_a_single_head():
    """0036 が 0035 に正しく連鎖し、履歴が単一の head に収束していること（分岐の防止）。

    head そのものの検証は最新リビジョンのテスト（test_0037_0038_migrations.py）が持つ
    （0037 以降の追加で本テストが head 固定のまま壊れないようにする）。
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    revision = script.get_revision("0036_email_notify_opt_in")
    assert revision.down_revision == "0035_bids_pending_reminder"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(revision.revision) <= 32
