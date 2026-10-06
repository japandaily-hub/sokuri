"""0048_users_terms_agreement（依頼者の規約同意の版数・日時の列追加）の回帰テスト。

test_0047 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため
``async def`` にはできない）で同期テストにしている。

- upgrade で users に agreed_terms_version（VARCHAR(32)・NULL 可）と agreed_at（NULL 可）が
  追加され、既存行の値は変わらず新しい2列は NULL のまま（＝再同意を求めない・backfill しない）。
- downgrade で2列が消え（既存の列・行には触れない）、往復（再 upgrade）でも同じ形に戻ること。
- head が 0048 の単独チェーンで 0047 に正しく連鎖し、リビジョン ID が 32 文字以内
  （head の固定は最新リビジョンのテストである本ファイルが持つ）。
- PostgreSQL でだけ lock_timeout を短くすること。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_REVISION = "0048_users_terms_agreement"
_DOWN_REVISION = "0047_password_reset_tokens"

# 0047 適用済み相当の最小スキーマ（0048 が触れるのは users だけ）。
_PRE_0048_SCHEMA_SQL = """
CREATE TABLE users (
    id CHAR(32) NOT NULL,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(128),
    CONSTRAINT pk_users PRIMARY KEY (id)
);
"""

_NEW_COLUMNS = {"agreed_terms_version", "agreed_at"}


def _alembic_config() -> Config:
    # alembic.ini を読ませない理由は tests/test_0028_migration_dedup.py と同じ
    # （ConfigParser の既定 encoding が cp932 環境で ini 内の日本語を壊す）。
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("path_separator", "os")
    return cfg


def _user_columns(conn: sqlite3.Connection) -> dict[str, tuple[str, int]]:
    """users の列名 → (型, NOT NULL) 。"""
    return {r[1]: (r[2].upper(), r[3]) for r in conn.execute("PRAGMA table_info('users')")}


def test_0048_adds_nullable_columns_without_backfill_and_round_trips(tmp_path, monkeypatch):
    from app.config import get_settings

    db_path = tmp_path / "0048.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    existing_id = uuid.uuid4().hex
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0048_SCHEMA_SQL)
            conn.execute(
                "INSERT INTO users (id, email, name) VALUES (?, 'a@example.com', '既存')",
                (existing_id,),
            )
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, _DOWN_REVISION)
        command.upgrade(cfg, _REVISION)

        conn = sqlite3.connect(str(db_path))
        try:
            columns = _user_columns(conn)
            assert _NEW_COLUMNS <= set(columns)
            assert columns["agreed_terms_version"] == ("VARCHAR(32)", 0)
            assert columns["agreed_at"][1] == 0
            # 既存ユーザーは NULL のまま（推測の値で埋めない＝再同意も求めない）。
            row = conn.execute(
                "SELECT email, name, agreed_terms_version, agreed_at FROM users WHERE id = ?",
                (existing_id,),
            ).fetchone()
            assert row == ("a@example.com", "既存", None, None)
            # 新しい行は版数と日時を書ける。
            conn.execute(
                "INSERT INTO users (id, email, agreed_terms_version, agreed_at)"
                " VALUES (?, 'b@example.com', '2026-10-06', '2026-10-06 00:00:00')",
                (uuid.uuid4().hex,),
            )
            conn.commit()
        finally:
            conn.close()

        command.downgrade(cfg, _DOWN_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            columns = _user_columns(conn)
            assert not (_NEW_COLUMNS & set(columns))
            assert {"id", "email", "name"} <= set(columns), "既存の列には触れない"
            assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 2
        finally:
            conn.close()

        # 往復（再 upgrade）でも同じ形に戻る。値は downgrade で消えるため NULL。
        command.upgrade(cfg, _REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            columns = _user_columns(conn)
            assert columns["agreed_terms_version"] == ("VARCHAR(32)", 0)
            assert columns["agreed_at"][1] == 0
            assert conn.execute(
                "SELECT count(*) FROM users WHERE agreed_terms_version IS NOT NULL"
            ).fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0048_is_the_single_head_chained_from_0047():
    """0048 が単独の head として 0047 に正しく連鎖していること（分岐の防止）。"""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [_REVISION]
    rev = script.get_revision(_REVISION)
    assert rev.down_revision == _DOWN_REVISION
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev.revision) <= 32


def test_0048_sets_lock_timeout_3s_only_on_postgresql(monkeypatch):
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
