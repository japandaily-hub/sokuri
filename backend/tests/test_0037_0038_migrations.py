"""0037_contact_messages_user_id / 0038_clear_deleted_op_line_ids の回帰テスト。

test_0036_email_notify_opt_in_migration.py と同じ理由（alembic の env.py が内部で
``asyncio.run()`` を呼ぶため ``async def`` にはできない）で同期テストにしている。

- 0037: contact_messages に user_id（NULL 可・users への FK・索引）が追加され、既存行は
  NULL のまま（紐付けの根拠が無いため遡って推定しない）。downgrade で列が消える。
- 0038: 論理削除済みの業者行に残った line_user_id だけを NULL に戻す（冪等）。
  有効な業者の連携には触れない。
- 0038 → 0037 → 0036 の単独チェーンで、リビジョン ID が 32 文字以内（head そのものの
  検証は最新リビジョンのテスト（test_0039_sessions_revoked_at_migration.py）が持つ）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

# 0036 適用済み相当の最小スキーマ（0037/0038 が触る3テーブルのみ）。
_PRE_0037_SCHEMA_SQL = """
CREATE TABLE users (
    id CHAR(32) PRIMARY KEY,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE contact_messages (
    id CHAR(32) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    category VARCHAR(32) NOT NULL,
    message TEXT NOT NULL,
    handled_at TIMESTAMP,
    handled_by_admin_id CHAR(32) REFERENCES users (id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operators (
    id CHAR(32) PRIMARY KEY,
    line_user_id VARCHAR(64) UNIQUE,
    deleted_at TIMESTAMP
);
CREATE TABLE bids (
    id CHAR(32) PRIMARY KEY,
    operator_id CHAR(32) NOT NULL REFERENCES operators (id)
);
CREATE TABLE transactions (
    id CHAR(32) PRIMARY KEY,
    bid_id CHAR(32) NOT NULL REFERENCES bids (id)
);
CREATE TABLE reviews (
    id CHAR(32) PRIMARY KEY,
    transaction_id CHAR(32) NOT NULL REFERENCES transactions (id),
    reviewer_type VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


def test_0037_adds_nullable_user_id_and_0038_clears_only_deleted_operators(
    tmp_path, monkeypatch, caplog
):
    db_path = tmp_path / "0037_0038.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger="alembic.versions.0038_clear_deleted_op_line_ids")
    get_settings.cache_clear()
    try:
        contact_id = uuid.uuid4().hex
        deleted_linked = uuid.uuid4().hex
        deleted_unlinked = uuid.uuid4().hex
        active_linked = uuid.uuid4().hex
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0037_SCHEMA_SQL)
            conn.execute(
                "INSERT INTO contact_messages (id, name, email, category, message) "
                "VALUES (?, ?, ?, ?, ?)",
                (contact_id, "既存 太郎", "old@example.com", "trouble", "既存の問い合わせ"),
            )
            conn.executemany(
                "INSERT INTO operators (id, line_user_id, deleted_at) VALUES (?, ?, ?)",
                [
                    (deleted_linked, "U-deleted-relinked", "2026-09-20 00:00:00"),
                    (deleted_unlinked, None, "2026-09-20 00:00:00"),
                    (active_linked, "U-active", None),
                ],
            )
            # 悪用の証跡の集計対象: 削除後に投稿された業者レビュー1件（数える）と、
            # 削除前の業者レビュー・依頼者レビュー（数えない）。
            bid_id, txn_id = uuid.uuid4().hex, uuid.uuid4().hex
            conn.execute("INSERT INTO bids (id, operator_id) VALUES (?, ?)", (bid_id, deleted_linked))
            conn.execute("INSERT INTO transactions (id, bid_id) VALUES (?, ?)", (txn_id, bid_id))
            conn.executemany(
                "INSERT INTO reviews (id, transaction_id, reviewer_type, created_at) VALUES (?, ?, ?, ?)",
                [
                    (uuid.uuid4().hex, txn_id, "operator", "2026-09-21 00:00:00"),
                    (uuid.uuid4().hex, txn_id, "operator", "2026-09-19 00:00:00"),
                    (uuid.uuid4().hex, txn_id, "user", "2026-09-21 00:00:00"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0036_email_notify_opt_in")
        command.upgrade(cfg, "0037_contact_messages_user_id")

        conn = sqlite3.connect(str(db_path))
        try:
            assert "user_id" in _columns(conn, "contact_messages")
            row = conn.execute(
                "SELECT user_id, name, message FROM contact_messages WHERE id = ?", (contact_id,)
            ).fetchone()
            assert row == (None, "既存 太郎", "既存の問い合わせ"), "既存行は紐付けず内容も不変"
            indexes = {r[1] for r in conn.execute("PRAGMA index_list('contact_messages')")}
            assert "ix_contact_messages_user_id" in indexes
            fks = {(r[2], r[3], r[4]) for r in conn.execute("PRAGMA foreign_key_list('contact_messages')")}
            assert ("users", "user_id", "id") in fks
        finally:
            conn.close()

        command.upgrade(cfg, "0038_clear_deleted_op_line_ids")
        audit_logs = [
            r.getMessage()
            for r in caplog.records
            if r.name == "alembic.versions.0038_clear_deleted_op_line_ids"
        ]
        assert len(audit_logs) == 1
        assert "LINE 連携を 1 件消去" in audit_logs[0]
        assert "業者レビューは 1 件" in audit_logs[0]

        # 冪等性: 同じ是正をもう一度流しても結果は変わらない（downgrade は no-op）。
        command.downgrade(cfg, "0037_contact_messages_user_id")
        command.upgrade(cfg, "0038_clear_deleted_op_line_ids")

        conn = sqlite3.connect(str(db_path))
        try:
            line_ids = dict(conn.execute("SELECT id, line_user_id FROM operators").fetchall())
            assert line_ids[deleted_linked] is None, "削除済み業者に再設定された連携が残っている"
            assert line_ids[deleted_unlinked] is None
            assert line_ids[active_linked] == "U-active", "有効な業者の連携を消してはならない"
        finally:
            conn.close()

        command.downgrade(cfg, "0036_email_notify_opt_in")
        conn = sqlite3.connect(str(db_path))
        try:
            assert "user_id" not in _columns(conn, "contact_messages")
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0038_is_chained_from_0037_and_0036_on_a_single_head():
    """0038 が 0037 → 0036 に正しく連鎖し、履歴が単一の head に収束していること（分岐の防止）。

    head そのものの検証は最新リビジョンのテスト（test_0039_sessions_revoked_at_migration.py）
    が持つ（0039 以降の追加で本テストが head 固定のまま壊れないようにする）。
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    rev_0038 = script.get_revision("0038_clear_deleted_op_line_ids")
    assert rev_0038.down_revision == "0037_contact_messages_user_id"
    rev_0037 = script.get_revision("0037_contact_messages_user_id")
    assert rev_0037.down_revision == "0036_email_notify_opt_in"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0038.revision) <= 32
    assert len(rev_0037.revision) <= 32
