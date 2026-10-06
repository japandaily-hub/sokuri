"""0047_password_reset_tokens（パスワード再設定トークンの表の新設）の回帰テスト。

test_0046 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため
``async def`` にはできない）で同期テストにしている。

- upgrade で password_reset_tokens が作られ、列・名前付き制約（PK・token_hash のユニーク・
  account_type の CHECK）・アカウント単位の索引がそろうこと。
- ユニーク制約・CHECK 制約が実際に効くこと（同じハッシュの2行目・未知の種別は拒否）。
- downgrade で表が消え（既存表には触れない）、往復（再 upgrade）でも同じ形に戻ること。
- 0047 が 0046 に正しく連鎖し、リビジョン ID が 32 文字以内（head の固定は
  最新リビジョンのテスト test_0048_users_terms_agreement_migration.py へ移設）。
- PostgreSQL でだけ lock_timeout を短くすること。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_REVISION = "0047_password_reset_tokens"
_DOWN_REVISION = "0046_messages_kind_length"

# 0046 適用済み相当の最小スキーマ（0047 は既存表に触れないため、触れないことの確認用に users だけ置く）。
_PRE_0047_SCHEMA_SQL = """
CREATE TABLE users (
    id CHAR(32) NOT NULL,
    email VARCHAR(255) NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id)
);
"""

_EXPECTED_COLUMNS = {
    "id": (1, None),
    "account_type": (1, None),
    "account_id": (1, None),
    "token_hash": (1, None),
    "expires_at": (1, None),
    "used_at": (0, None),
    "created_at": (1, "CURRENT_TIMESTAMP"),
}


def _alembic_config() -> Config:
    # alembic.ini を読ませない理由は tests/test_0028_migration_dedup.py と同じ
    # （ConfigParser の既定 encoding が cp932 環境で ini 内の日本語を壊す）。
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("path_separator", "os")
    return cfg


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _assert_table_shape(conn: sqlite3.Connection) -> None:
    columns = {r[1]: (r[3], r[4]) for r in conn.execute("PRAGMA table_info('password_reset_tokens')")}
    assert set(columns) == set(_EXPECTED_COLUMNS)
    for name, (notnull, default) in _EXPECTED_COLUMNS.items():
        assert columns[name][0] == notnull, name
        if default is not None:
            assert default in (columns[name][1] or "").upper(), name
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'password_reset_tokens'"
    ).fetchone()[0]
    for constraint in (
        "pk_password_reset_tokens",
        "uq_password_reset_tokens_token_hash",
        "ck_password_reset_tokens_account_type",
    ):
        assert f"CONSTRAINT {constraint} " in table_sql, table_sql
    index_columns = [
        r[2] for r in conn.execute("PRAGMA index_info('ix_password_reset_tokens_account')")
    ]
    assert index_columns == ["account_type", "account_id"]


def _insert(conn: sqlite3.Connection, *, token_hash: str, account_type: str = "user") -> None:
    conn.execute(
        "INSERT INTO password_reset_tokens (id, account_type, account_id, token_hash, expires_at)"
        " VALUES (?, ?, ?, ?, '2026-10-06 00:30:00')",
        (uuid.uuid4().hex, account_type, uuid.uuid4().hex, token_hash),
    )


def test_0047_creates_table_with_constraints_and_round_trips(tmp_path, monkeypatch):
    from app.config import get_settings

    db_path = tmp_path / "0047.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0047_SCHEMA_SQL)
            conn.execute("INSERT INTO users (id, email) VALUES (?, 'a@example.com')", (uuid.uuid4().hex,))
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, _DOWN_REVISION)
        command.upgrade(cfg, _REVISION)

        conn = sqlite3.connect(str(db_path))
        try:
            _assert_table_shape(conn)
            _insert(conn, token_hash="a" * 64)
            _insert(conn, token_hash="b" * 64, account_type="operator")
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                _insert(conn, token_hash="a" * 64)  # token_hash のユニーク制約
            conn.rollback()
            with pytest.raises(sqlite3.IntegrityError):
                _insert(conn, token_hash="c" * 64, account_type="admin")  # 種別の CHECK 制約
            conn.rollback()
            assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        finally:
            conn.close()

        command.downgrade(cfg, _DOWN_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            tables = _table_names(conn)
            assert "password_reset_tokens" not in tables
            assert "users" in tables, "既存表には触れない"
            assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        finally:
            conn.close()

        # 往復（再 upgrade）でも同じ形に戻る。
        command.upgrade(cfg, _REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            _assert_table_shape(conn)
            assert conn.execute("SELECT count(*) FROM password_reset_tokens").fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0047_is_chained_from_0046_on_a_single_head():
    """0047 が 0046 に正しく連鎖し、履歴が単一の head に収束していること（分岐の防止）。

    head そのものの固定は最新リビジョンのテスト（現在は test_0048_users_terms_agreement_migration.py）
    が持つ（test_0046 と同じ作法）。
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    assert len(script.get_heads()) == 1
    rev = script.get_revision(_REVISION)
    assert rev.down_revision == _DOWN_REVISION
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev.revision) <= 32


def test_0047_matches_the_orm_model():
    """マイグレーションの列・制約名が ORM モデル（テストの create_all の正本）と一致していること。"""
    from app.db.models.password_reset_token import PasswordResetToken

    table = PasswordResetToken.__table__
    assert {c.name for c in table.columns} == set(_EXPECTED_COLUMNS)
    assert table.c.token_hash.type.length == 64
    assert table.c.account_type.type.length == 16
    assert {c.name for c in table.constraints if c.name} >= {
        "pk_password_reset_tokens",
        "uq_password_reset_tokens_token_hash",
        "ck_password_reset_tokens_account_type",
    }
    assert {i.name for i in table.indexes} == {"ix_password_reset_tokens_account"}


def test_0047_sets_lock_timeout_3s_only_on_postgresql(monkeypatch):
    """PostgreSQL では DDL の前だけ lock_timeout を 3s にする。SQLite では何も発行しない。"""
    from types import SimpleNamespace

    from alembic.script import ScriptDirectory

    module = ScriptDirectory.from_config(_alembic_config()).get_revision(_REVISION).module
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
