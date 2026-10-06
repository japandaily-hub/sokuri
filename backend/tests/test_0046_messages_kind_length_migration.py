"""0046_messages_kind_length（messages.kind を VARCHAR(16) → VARCHAR(32) へ拡幅）の回帰テスト。

test_0043 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため
``async def`` にはできない）で同期テストにしている。

- upgrade 後、messages.kind の列型が VARCHAR(32) になっていること（PRAGMA table_info）。
- 既存の名前付き制約・FK・索引が SQLite の表の作り直し後も残ること。
- 17文字超（schedule_confirmed 等の旧データ）の既存行が upgrade 前後で変わらないこと。
- 拡幅後は32文字までの新しい kind 値を書き込めること（旧列長16なら実害は無いが
  SQLite は型を強制しないため、ここでは型情報の変化そのものを主な検証対象にする）。
- downgrade は no-op（値・スキーマとも変わらない）。
- 0046 が 0045 に正しく連鎖し、リビジョン ID が 32 文字以内（head の固定は
  最新リビジョンのテスト test_0048_users_terms_agreement_migration.py へ移設）。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

# 0045 適用済み相当の最小スキーマ（0046 が触る messages のみ。0009 の実カラム定義を写す）。
_PRE_0046_SCHEMA_SQL = """
CREATE TABLE transactions (
    id CHAR(32) NOT NULL,
    CONSTRAINT pk_transactions PRIMARY KEY (id)
);
CREATE TABLE messages (
    id CHAR(32) NOT NULL,
    transaction_id CHAR(32) NOT NULL,
    sender_type VARCHAR(16) NOT NULL,
    sender_id CHAR(32),
    body TEXT NOT NULL,
    kind VARCHAR(16) DEFAULT 'text' NOT NULL,
    meta TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_messages PRIMARY KEY (id),
    CONSTRAINT fk_messages_transaction_id_transactions FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE RESTRICT
);
CREATE INDEX ix_messages_transaction_id ON messages (transaction_id);
CREATE INDEX ix_messages_transaction_id_created_at ON messages (transaction_id, created_at);
"""

_PRESERVED_MESSAGE_CONSTRAINTS = (
    "pk_messages",
    "fk_messages_transaction_id_transactions",
)


def _alembic_config() -> Config:
    # alembic.ini を読ませない理由は tests/test_0028_migration_dedup.py と同じ
    # （ConfigParser の既定 encoding が cp932 環境で ini 内の日本語を壊す）。
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("path_separator", "os")
    return cfg


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def _kind_column_type(conn: sqlite3.Connection) -> str:
    for row in conn.execute("PRAGMA table_info('messages')"):
        if row[1] == "kind":
            return row[2]
    raise AssertionError("messages.kind 列が見つからない")


def _assert_message_schema_preserved(conn: sqlite3.Connection) -> None:
    """表の作り直し後も、名前付き制約・FK（ON DELETE RESTRICT）・索引が残っていること。"""
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages'"
    ).fetchone()[0]
    for name in _PRESERVED_MESSAGE_CONSTRAINTS:
        # 部分一致だと命名規約で二重化した名前も通るため "CONSTRAINT <名前> " の形で見る。
        assert f"CONSTRAINT {name} " in table_sql, f"作り直しで制約 {name} が消えた: {table_sql}"
    fks = {(r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list('messages')")}
    assert ("transactions", "transaction_id", "id", "RESTRICT") in fks
    indexes = {r[1] for r in conn.execute("PRAGMA index_list('messages')")}
    assert "ix_messages_transaction_id" in indexes
    assert "ix_messages_transaction_id_created_at" in indexes


def test_0046_widens_kind_to_varchar32_and_preserves_existing_rows(tmp_path, monkeypatch):
    from app.config import get_settings

    db_path = tmp_path / "0046.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        txn_id = uuid.uuid4().hex
        legacy_row_id = uuid.uuid4().hex  # "schedule_confirmed" は18文字（旧列長16を既に超えていた実例）

        conn = _connect(db_path)
        try:
            conn.executescript(_PRE_0046_SCHEMA_SQL)
            conn.execute("INSERT INTO transactions (id) VALUES (?)", (txn_id,))
            conn.execute(
                "INSERT INTO messages (id, transaction_id, sender_type, body, kind)"
                " VALUES (?, ?, 'system', 'x', ?)",
                (legacy_row_id, txn_id, "schedule_confirmed"),
            )
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0045_review_hidden_by_admin")
        command.upgrade(cfg, "0046_messages_kind_length")

        conn = _connect(db_path)
        try:
            assert _kind_column_type(conn) == "VARCHAR(32)"
            _assert_message_schema_preserved(conn)
            row = conn.execute(
                "SELECT kind FROM messages WHERE id = ?", (legacy_row_id,)
            ).fetchone()
            assert row[0] == "schedule_confirmed", "既存データは変わらない"

            # 拡幅後は32文字までの新しい kind 値を書き込める。
            new_row_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO messages (id, transaction_id, sender_type, body, kind)"
                " VALUES (?, ?, 'operator', 'y', ?)",
                (new_row_id, txn_id, "x" * 32),
            )
            conn.commit()
        finally:
            conn.close()

        # downgrade は no-op（値・スキーマとも変わらない）。
        command.downgrade(cfg, "0045_review_hidden_by_admin")
        conn = _connect(db_path)
        try:
            assert _kind_column_type(conn) == "VARCHAR(32)"
            _assert_message_schema_preserved(conn)
            row = conn.execute(
                "SELECT kind FROM messages WHERE id = ?", (legacy_row_id,)
            ).fetchone()
            assert row[0] == "schedule_confirmed"
        finally:
            conn.close()

        # 往復（再 upgrade）でも型は変わらず、データも保持される。
        command.upgrade(cfg, "0046_messages_kind_length")
        conn = _connect(db_path)
        try:
            assert _kind_column_type(conn) == "VARCHAR(32)"
            _assert_message_schema_preserved(conn)
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0046_is_chained_from_0045_on_a_single_head():
    """0046 が 0045 に正しく連鎖し、履歴が単一の head に収束していること（分岐の防止）。

    head そのものの固定は最新リビジョンのテスト（現在は test_0048_users_terms_agreement_migration.py）
    が持つ（test_0045 と同じ作法）。
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    rev_0046 = script.get_revision("0046_messages_kind_length")
    assert rev_0046.down_revision == "0045_review_hidden_by_admin"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0046.revision) <= 32


def test_0046_sets_lock_timeout_3s_only_on_postgresql(monkeypatch):
    """PostgreSQL では ALTER の前だけ lock_timeout を 3s にする。SQLite では何も発行しない。

    実 DB の PostgreSQL が無い環境でも文の順序を固定するため、マイグレーションの
    op を差し替えて確かめる（test_0042 の同名テストと同じ手法）。
    """
    from types import SimpleNamespace

    from alembic.script import ScriptDirectory

    module = (
        ScriptDirectory.from_config(_alembic_config())
        .get_revision("0046_messages_kind_length")
        .module
    )
    for dialect, expected in (
        ("postgresql", ["SET LOCAL lock_timeout = '3s'"]),
        ("sqlite", []),
    ):
        executed: list[str] = []
        fake_op = SimpleNamespace(
            get_bind=lambda dialect=dialect: SimpleNamespace(dialect=SimpleNamespace(name=dialect)),
            execute=lambda statement: executed.append(str(statement)),
        )
        monkeypatch.setattr(module, "op", fake_op)
        module._shorten_lock_timeout_on_postgresql()
        assert executed == expected, dialect
