"""0045_review_hidden_by_admin（口コミを今削除している運営の記録）の回帰テスト。

test_0040〜0044 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため ``async def`` に
できない）で同期テストにしている。SQLite ファイルに 0043 適用済み相当の最小スキーマを作り、
stamp 0043 → 明示のリビジョンへ upgrade する（0044 → 0045 を続けて通す）。

- reviews.hidden_by_admin_id（NULL 可）・FK users.id ON DELETE SET NULL（名前
  fk_reviews_hidden_by_admin_id_users）・索引 ix_reviews_hidden_by_admin_id ができる。既存行は NULL で、
  他の列・制約・索引はそのまま。運営アカウントを消すと口コミは残り列だけ NULL になる。
- PostgreSQL だけの lock_timeout は SQLite では発行しない。
- 戻し手順（DESIGN-admin.md）の順: downgrade 0044（0045 を戻す＝列・FK・索引が消える）→
  downgrade 0043（★列が NULL で戻る）→ upgrade head で元どおり。
- head が 0045 の単独チェーンで、リビジョン ID が 32 文字以内（head の固定は最新リビジョンの
  テストである本ファイルが持つ）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

# 0043 適用済み相当の最小スキーマ（0044・0045 が触る表と、その FK の親子）。制約名は本番の実名。
# FK 句を1行で書く理由は test_0040 と同じ（SQLite の反映が改行入りの FK 句を読み落とす）。
_PRE_0044_SCHEMA_SQL = """
CREATE TABLE users (
    id CHAR(32) NOT NULL,
    email VARCHAR(255) NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id)
);
CREATE TABLE operators (
    id CHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    rating FLOAT,
    CONSTRAINT pk_operators PRIMARY KEY (id)
);
CREATE TABLE bids (
    id CHAR(32) PRIMARY KEY,
    operator_id CHAR(32) NOT NULL,
    CONSTRAINT fk_bids_operator_id_operators FOREIGN KEY(operator_id) REFERENCES operators (id) ON DELETE CASCADE
);
CREATE TABLE transactions (
    id CHAR(32) PRIMARY KEY,
    bid_id CHAR(32) NOT NULL REFERENCES bids (id)
);
CREATE TABLE reviews (
    id CHAR(32) NOT NULL,
    transaction_id CHAR(32) NOT NULL,
    reviewer_type VARCHAR(32) NOT NULL,
    rating INTEGER,
    verdict VARCHAR(16) NOT NULL,
    comment TEXT,
    hidden_at TIMESTAMP,
    hidden_reason VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_reviews PRIMARY KEY (id),
    CONSTRAINT fk_reviews_transaction_id_transactions FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
    CONSTRAINT uq_reviews_transaction_reviewer UNIQUE (transaction_id, reviewer_type),
    CONSTRAINT ck_reviews_ck_reviews_rating CHECK (rating >= 1 AND rating <= 5),
    CONSTRAINT ck_reviews_verdict CHECK (verdict IN ('good','improve'))
);
CREATE INDEX ix_reviews_transaction_id ON reviews (transaction_id);
"""

_PRESERVED_REVIEW_CONSTRAINTS = (
    "pk_reviews",
    "fk_reviews_transaction_id_transactions",
    "uq_reviews_transaction_reviewer",
    "ck_reviews_verdict",
)
_REVIEW_COLUMNS = "id, transaction_id, reviewer_type, verdict, comment, hidden_at, hidden_reason, created_at"
_ADMIN_FK = ("users", "hidden_by_admin_id", "id", "SET NULL")


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


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    """列名 → NOT NULL 指定（1＝NOT NULL、0＝NULL 可）。"""
    return {row[1]: row[3] for row in conn.execute(f"PRAGMA table_info('{table}')")}


def _review_fks(conn: sqlite3.Connection) -> set[tuple]:
    return {(r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list('reviews')")}


def _review_indexes(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA index_list('reviews')")}


def _reviews_sql(conn: sqlite3.Connection) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reviews'"
    ).fetchone()[0]


def _assert_preserved(conn: sqlite3.Connection) -> None:
    reviews_sql = _reviews_sql(conn)
    for name in _PRESERVED_REVIEW_CONSTRAINTS:
        assert f"CONSTRAINT {name} " in reviews_sql, f"作り直しで制約 {name} が消えた: {reviews_sql}"
    assert ("transactions", "transaction_id", "id", "CASCADE") in _review_fks(conn)
    assert "ix_reviews_transaction_id" in _review_indexes(conn)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def _review_rows(db_path: Path) -> list:
    conn = _connect(db_path)
    try:
        return conn.execute(f"SELECT {_REVIEW_COLUMNS} FROM reviews ORDER BY id").fetchall()
    finally:
        conn.close()


def test_0045_adds_hidden_by_admin_id_with_set_null_fk_and_index_and_rolls_back_in_order(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "0045.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        admin_id, operator_id, bid_id = "a" * 32, "b" * 32, "c" * 32
        txn_a, txn_b = "d" * 32, "e" * 32
        review_hidden, review_visible = f"{1:032x}", f"{2:032x}"
        conn = _connect(db_path)
        try:
            conn.executescript(_PRE_0044_SCHEMA_SQL)
            conn.execute("INSERT INTO users (id, email) VALUES (?, 'admin@example.com')", (admin_id,))
            conn.execute(
                "INSERT INTO operators (id, company_name, rating) VALUES (?, '記録株式会社', 4.0)",
                (operator_id,),
            )
            conn.execute("INSERT INTO bids (id, operator_id) VALUES (?, ?)", (bid_id, operator_id))
            conn.executemany(
                "INSERT INTO transactions (id, bid_id) VALUES (?, ?)", [(txn_a, bid_id), (txn_b, bid_id)]
            )
            conn.executemany(
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, verdict, comment,"
                " hidden_at, hidden_reason) VALUES (?, ?, 'user', ?, ?, ?, ?, ?)",
                [
                    (review_hidden, txn_a, 2, "improve", "宣伝", "2026-09-20 00:00:00", "その他"),
                    (review_visible, txn_b, None, "good", "丁寧でした", None, None),
                ],
            )
            conn.commit()
        finally:
            conn.close()
        rows_before = _review_rows(db_path)

        cfg = _alembic_config()
        command.stamp(cfg, "0043_audit_active_no_license")
        statements = _run_capturing_sql(
            lambda: command.upgrade(cfg, "0045_review_hidden_by_admin")
        )
        # PostgreSQL だけの lock_timeout は SQLite では発行しない（捕捉できていることも確認）。
        assert any("hidden_by_admin_id" in s for s in statements)
        assert not [s for s in statements if "LOCK_TIMEOUT" in s.upper() or "LOCK TABLE" in s.upper()]

        conn = _connect(db_path)
        try:
            columns = _columns(conn, "reviews")
            assert columns["hidden_by_admin_id"] == 0 and "rating" not in columns
            assert _ADMIN_FK in _review_fks(conn)
            assert "CONSTRAINT fk_reviews_hidden_by_admin_id_users " in _reviews_sql(conn)
            assert "ix_reviews_hidden_by_admin_id" in _review_indexes(conn)
            _assert_preserved(conn)
            assert conn.execute("SELECT COUNT(*) FROM reviews WHERE hidden_by_admin_id IS NOT NULL").fetchone() == (0,)
        finally:
            conn.close()
        assert _review_rows(db_path) == rows_before, "既存の口コミは変わらない（新しい列は NULL）"

        # 運営アカウントを消すと、口コミは残り hidden_by_admin_id だけ NULL になる（ON DELETE SET NULL）。
        conn = _connect(db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                "UPDATE reviews SET hidden_by_admin_id = ? WHERE id = ?", (admin_id, review_hidden)
            )
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                conn.execute(
                    "UPDATE reviews SET hidden_by_admin_id = ? WHERE id = ?", ("f" * 32, review_visible)
                )
            conn.execute("DELETE FROM users WHERE id = ?", (admin_id,))
            conn.commit()
            assert conn.execute(
                "SELECT hidden_by_admin_id, hidden_reason FROM reviews WHERE id = ?", (review_hidden,)
            ).fetchone() == (None, "その他")
            assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone() == (2,)
        finally:
            conn.close()

        # 戻し手順の1: downgrade 0044（0045 を戻す）で列・FK・索引が消える。★列はまだ無い。
        command.downgrade(cfg, "0044_drop_rating_columns")
        conn = _connect(db_path)
        try:
            columns = _columns(conn, "reviews")
            assert "hidden_by_admin_id" not in columns and "rating" not in columns
            assert not [fk for fk in _review_fks(conn) if fk[0] == "users"]
            assert "hidden_by_admin_id" not in _reviews_sql(conn)
            assert "ix_reviews_hidden_by_admin_id" not in _review_indexes(conn)
            _assert_preserved(conn)
        finally:
            conn.close()
        assert _review_rows(db_path) == rows_before

        # 戻し手順の2: downgrade 0043 で★列が NULL で戻る。
        command.downgrade(cfg, "0043_audit_active_no_license")
        conn = _connect(db_path)
        try:
            assert _columns(conn, "reviews")["rating"] == 0
            assert _columns(conn, "operators")["rating"] == 0
            assert "CONSTRAINT ck_reviews_ck_reviews_rating " in _reviews_sql(conn)
            assert conn.execute("SELECT COUNT(*) FROM reviews WHERE rating IS NOT NULL").fetchone() == (0,)
            _assert_preserved(conn)
        finally:
            conn.close()
        assert _review_rows(db_path) == rows_before

        # 往復: head へ上げ直すと元どおり（ci.yml の pg-concurrency が実 PG で同じ往復を通す）。
        command.upgrade(cfg, "head")
        conn = _connect(db_path)
        try:
            columns = _columns(conn, "reviews")
            assert "hidden_by_admin_id" in columns and "rating" not in columns
            assert "rating" not in _columns(conn, "operators")
            assert _ADMIN_FK in _review_fks(conn)
            assert "ix_reviews_hidden_by_admin_id" in _review_indexes(conn)
            _assert_preserved(conn)
        finally:
            conn.close()
        assert _review_rows(db_path) == rows_before
    finally:
        get_settings.cache_clear()


def test_0045_waits_for_locks_at_most_3s_only_on_postgresql(monkeypatch):
    """PostgreSQL では lock_timeout を 3s にしてから表を変える。SQLite では何も発行しない。
    実 PostgreSQL が無い環境でも文を固定するため、マイグレーションの op を差し替えて確かめる。"""
    from types import SimpleNamespace

    from alembic.script import ScriptDirectory

    module = (
        ScriptDirectory.from_config(_alembic_config())
        .get_revision("0045_review_hidden_by_admin")
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
        module._set_lock_timeout()
        assert executed == expected, dialect


def test_0045_is_the_single_head_chained_from_0044():
    """0045 が単独の head として 0044 → 0043 → 0042 に正しく連鎖していること（分岐の防止）。"""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == ["0045_review_hidden_by_admin"]
    rev_0045 = script.get_revision("0045_review_hidden_by_admin")
    assert rev_0045.down_revision == "0044_drop_rating_columns"
    assert script.get_revision("0044_drop_rating_columns").down_revision == (
        "0043_audit_active_no_license"
    )
    assert script.get_revision("0043_audit_active_no_license").down_revision == (
        "0042_review_verdict_contract"
    )
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0045.revision) <= 32
