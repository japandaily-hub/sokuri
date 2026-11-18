"""0049_erase_identity_images（本人確認書類の画像消去）の回帰テスト。

test_0048 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため
``async def`` にはできない）で同期テストにしている。

- upgrade で全行の画像（表・裏）と裏面の MIME が NULL になり、行そのもの（書類種別・提出日時・
  審査結果）は残る。
- 審査待ちは rejected（理由付き・reviewed_at は入れない）になり、承認・却下済みは変わらない。
- users.identity_status は pending だけ unverified に戻り、approved / rejected は変わらない。
- 2回流しても同じ結果（冪等）。downgrade は何もしない（画像は戻らない）。
- head が 0049 の単独チェーンで 0048 に連鎖し、リビジョン ID が 32 文字以内。
- VACUUM FULL は PostgreSQL でだけ、トランザクションの外（autocommit）で発行する。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_REVISION = "0049_erase_identity_images"
_DOWN_REVISION = "0048_users_terms_agreement"

# 0048 適用済み相当の最小スキーマ（0049 が触れるのは users と user_identity_documents だけ）。
_PRE_0049_SCHEMA_SQL = """
CREATE TABLE users (
    id CHAR(32) NOT NULL,
    email VARCHAR(255) NOT NULL,
    identity_status VARCHAR(20) NOT NULL DEFAULT 'unverified',
    CONSTRAINT pk_users PRIMARY KEY (id)
);
CREATE TABLE user_identity_documents (
    id CHAR(32) NOT NULL,
    user_id CHAR(32) NOT NULL,
    doc_type VARCHAR(32) NOT NULL,
    front_image_data BLOB,
    front_image_content_type VARCHAR(32) NOT NULL,
    back_image_data BLOB,
    back_image_content_type VARCHAR(32),
    status VARCHAR(20) NOT NULL,
    submitted_at TIMESTAMP NOT NULL,
    reviewed_by CHAR(32),
    reviewed_at TIMESTAMP,
    reject_reason VARCHAR(500),
    CONSTRAINT pk_user_identity_documents PRIMARY KEY (id)
);
"""

_IMAGE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _alembic_config() -> Config:
    # alembic.ini を読ませない理由は tests/test_0028_migration_dedup.py と同じ。
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("path_separator", "os")
    return cfg


def _seed(db_path: Path) -> dict[str, str]:
    ids = {key: uuid.uuid4().hex for key in ("u_pending", "u_approved", "u_rejected", "u_none")}
    docs = {key: uuid.uuid4().hex for key in ("d_pending", "d_approved", "d_rejected")}
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_PRE_0049_SCHEMA_SQL)
        for key, status in (
            ("u_pending", "pending"),
            ("u_approved", "approved"),
            ("u_rejected", "rejected"),
            ("u_none", "unverified"),
        ):
            conn.execute(
                "INSERT INTO users (id, email, identity_status) VALUES (?, ?, ?)",
                (ids[key], f"{key}@example.com", status),
            )
        for doc_key, user_key, status, reviewed_at, reason in (
            ("d_pending", "u_pending", "pending", None, None),
            ("d_approved", "u_approved", "approved", "2026-10-01 00:00:00", None),
            ("d_rejected", "u_rejected", "rejected", "2026-10-02 00:00:00", "読み取れません"),
        ):
            conn.execute(
                "INSERT INTO user_identity_documents (id, user_id, doc_type, front_image_data,"
                " front_image_content_type, back_image_data, back_image_content_type, status,"
                " submitted_at, reviewed_at, reject_reason)"
                " VALUES (?, ?, 'drivers_license', ?, 'image/png', ?, 'image/png', ?,"
                " '2026-09-30 00:00:00', ?, ?)",
                (docs[doc_key], ids[user_key], _IMAGE, _IMAGE, status, reviewed_at, reason),
            )
        conn.commit()
    finally:
        conn.close()
    return {**ids, **docs}


def _assert_erased(db_path: Path, keys: dict[str, str]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute(
            "SELECT count(*) FROM user_identity_documents"
            " WHERE front_image_data IS NOT NULL OR back_image_data IS NOT NULL"
            " OR back_image_content_type IS NOT NULL"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM user_identity_documents").fetchone()[0] == 3
        docs = {
            row[0]: row[1:]
            for row in conn.execute(
                "SELECT id, status, reviewed_at, reject_reason, doc_type, front_image_content_type"
                " FROM user_identity_documents"
            )
        }
        status, reviewed_at, reason, doc_type, front_type = docs[keys["d_pending"]]
        assert status == "rejected"
        assert reviewed_at is None, "運営が審査したわけではないので reviewed_at は入れない"
        assert reason and "受付終了" in reason
        assert (doc_type, front_type) == ("drivers_license", "image/png")
        assert docs[keys["d_approved"]][:3] == ("approved", "2026-10-01 00:00:00", None)
        assert docs[keys["d_rejected"]][:3] == ("rejected", "2026-10-02 00:00:00", "読み取れません")

        users = dict(conn.execute("SELECT id, identity_status FROM users"))
        assert users[keys["u_pending"]] == "unverified"
        assert users[keys["u_approved"]] == "approved"
        assert users[keys["u_rejected"]] == "rejected"
        assert users[keys["u_none"]] == "unverified"
    finally:
        conn.close()


def test_0049_erases_images_keeps_rows_and_is_idempotent(tmp_path, monkeypatch):
    from app.config import get_settings

    db_path = tmp_path / "0049.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        keys = _seed(db_path)
        cfg = _alembic_config()
        command.stamp(cfg, _DOWN_REVISION)
        command.upgrade(cfg, _REVISION)
        _assert_erased(db_path, keys)

        # downgrade は何もしない（画像は戻らない）。再 upgrade しても同じ結果（冪等）。
        command.downgrade(cfg, _DOWN_REVISION)
        _assert_erased(db_path, keys)
        command.upgrade(cfg, _REVISION)
        _assert_erased(db_path, keys)
    finally:
        get_settings.cache_clear()


def test_0049_is_the_single_head_chained_from_0048():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [_REVISION]
    rev = script.get_revision(_REVISION)
    assert rev.down_revision == _DOWN_REVISION
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev.revision) <= 32


class _FakeResult:
    rowcount = 0

    def __init__(self, scalar_value: int = 0) -> None:
        self._scalar_value = scalar_value

    def scalar(self) -> int:
        return self._scalar_value


class _FakeBind:
    def __init__(self, dialect: str, executed: list[str], holders: int = 0) -> None:
        from types import SimpleNamespace

        self.dialect = SimpleNamespace(name=dialect)
        self._executed = executed
        self._holders = holders

    def execute(self, statement, params=None):
        self._executed.append(str(statement))
        return _FakeResult(self._holders)


def _run_upgrade_with_fake_op(
    monkeypatch, dialect: str, *, vacuum_fails: bool = False, holders: int = 0
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from alembic.script import ScriptDirectory

    module = ScriptDirectory.from_config(_alembic_config()).get_revision(_REVISION).module
    executed: list[str] = []
    in_autocommit: list[bool] = [False]
    vacuum_in_autocommit: list[bool] = []

    @contextmanager
    def autocommit_block():
        in_autocommit[0] = True
        executed.append("<autocommit>")
        try:
            yield
        finally:
            in_autocommit[0] = False
            executed.append("</autocommit>")

    def fake_execute(statement):
        text = str(statement)
        if text.startswith("VACUUM"):
            vacuum_in_autocommit.append(in_autocommit[0])
            if vacuum_fails:
                executed.append(text)
                raise RuntimeError("lock timeout")
        executed.append(text)

    bind = _FakeBind(dialect, executed, holders)
    fake_op = SimpleNamespace(
        get_bind=lambda: bind,
        execute=fake_execute,
        get_context=lambda: SimpleNamespace(autocommit_block=autocommit_block),
    )
    monkeypatch.setattr(module, "op", fake_op)
    module.upgrade()
    return executed, vacuum_in_autocommit


def test_0049_vacuum_full_only_on_postgresql_outside_transaction(monkeypatch):
    executed, vacuum_flags = _run_upgrade_with_fake_op(monkeypatch, "postgresql")
    assert executed[0] == "SET LOCAL lock_timeout = '3s'"
    assert "VACUUM FULL user_identity_documents" in executed
    assert vacuum_flags == [True], "VACUUM はトランザクションの外（autocommit）で流す"
    assert executed[-2:] == ["RESET lock_timeout", "</autocommit>"]

    executed, vacuum_flags = _run_upgrade_with_fake_op(monkeypatch, "sqlite")
    assert not any(s.startswith(("VACUUM", "SET", "RESET")) for s in executed)
    assert "<autocommit>" not in executed
    assert vacuum_flags == []


def test_0049_vacuum_failure_does_not_abort_migration(monkeypatch):
    """VACUUM が取れなくても起動を止めない（画像の NULL 化はコミット済み）。"""
    executed, _ = _run_upgrade_with_fake_op(monkeypatch, "postgresql", vacuum_fails=True)
    assert executed[-2:] == ["RESET lock_timeout", "</autocommit>"]


def test_0049_warns_when_old_snapshots_may_keep_images(monkeypatch, caplog):
    """古いスナップショットを持つ接続があると VACUUM FULL は旧い版を写す（実 PG16 で確認）。
    その場合は成功ログではなく、手動の再 VACUUM を促す WARNING を出す。"""
    import logging

    with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
        executed, _ = _run_upgrade_with_fake_op(monkeypatch, "postgresql", holders=2)
    assert any("pg_stat_activity" in s for s in executed)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and "古いスナップショット" in warnings[0].getMessage()
    assert not any("書き直しました" in r.getMessage() for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
        _run_upgrade_with_fake_op(monkeypatch, "postgresql", holders=0)
    assert any("書き直しました" in r.getMessage() for r in caplog.records)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
