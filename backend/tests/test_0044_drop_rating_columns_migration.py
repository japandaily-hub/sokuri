"""0044_drop_rating_columns（★列の DB からの削除）の回帰テスト。

test_0040〜0042 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため ``async def`` に
できない）で同期テストにしている。SQLite ファイルに 0043 適用済み相当の最小スキーマを作り、
stamp 0043 → 明示のリビジョンへ upgrade する。

- reviews.rating と★の範囲の CHECK、operators.rating を削除する。CHECK の名前は DB から読む
  （実名 ck_reviews_ck_reviews_rating・命名規約の二重化が無い ck_reviews_rating・CHECK 無しの3通り）。
- SQLite の batch（表の作り直し）後も、一意制約・評価の値の CHECK・FK・索引が有効で
  ``PRAGMA foreign_key_check`` が空。他の列の値と件数は変わらない。
- 非 NULL の件数と（1〜50 件なら）(id, rating) を INFO に残す。PostgreSQL だけの lock_timeout・表ロックは
  SQLite では発行しない。
- downgrade で rating が NULL で戻り、★の範囲の CHECK（実名 ck_reviews_ck_reviews_rating）が 6 を拒否し
  NULL を通す。往復（2回目の upgrade）も通る。rating 列が既に無い DB では upgrade が何もしない（冪等）。
- 0044 が 0043 に連鎖し単一の head に収束していて、リビジョン ID が 32 文字以内（head そのものの固定は
  最新リビジョンのテスト＝test_0045_review_hidden_by_admin_migration.py）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_LOGGER_NAME = "alembic.versions.0044_drop_rating_columns"

# 0043 適用済み相当の最小スキーマ（0044 が触る表と、その FK の親子）。reviews の★の CHECK は
# パラメータで差し替える。FK 句を1行で書く理由は test_0040 と同じ（SQLite の反映が改行入りの FK 句を
# 読み落とす）。
_PRE_0044_SCHEMA_SQL = """
CREATE TABLE operators (
    id CHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    rating FLOAT,
    review_count INTEGER DEFAULT '0' NOT NULL,
    good_count INTEGER DEFAULT '0' NOT NULL,
    improve_count INTEGER DEFAULT '0' NOT NULL,
    vendor_status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_operators PRIMARY KEY (id)
);
CREATE INDEX ix_operators_vendor_status ON operators (vendor_status);
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
    {rating_check}CONSTRAINT ck_reviews_ck_reviews_reviewer_type CHECK (reviewer_type IN ('user','operator')),
    CONSTRAINT ck_reviews_verdict CHECK (verdict IN ('good','improve'))
);
CREATE INDEX ix_reviews_transaction_id ON reviews (transaction_id);
"""

# 表の作り直し後も残っているべき名前付き制約。
_PRESERVED_REVIEW_CONSTRAINTS = (
    "pk_reviews",
    "fk_reviews_transaction_id_transactions",
    "uq_reviews_transaction_reviewer",
    "ck_reviews_ck_reviews_reviewer_type",
    "ck_reviews_verdict",
)
_REVIEW_COLUMNS = "id, transaction_id, reviewer_type, verdict, comment, hidden_at, hidden_reason, created_at"
_OPERATOR_COLUMNS = "id, company_name, review_count, good_count, improve_count, vendor_status, created_at"


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


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()[0]


def _assert_schema_preserved(conn: sqlite3.Connection) -> None:
    """作り直し後も名前付き制約・FK・索引が残り、FK の参照がすべて有効であること。"""
    reviews_sql = _table_sql(conn, "reviews")
    for name in _PRESERVED_REVIEW_CONSTRAINTS:
        # 部分一致だと命名規約で二重化した名前も通るため "CONSTRAINT <名前> " の形で見る。
        assert f"CONSTRAINT {name} " in reviews_sql, f"作り直しで制約 {name} が消えた: {reviews_sql}"
    assert "CONSTRAINT pk_operators " in _table_sql(conn, "operators")
    review_fks = {(r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list('reviews')")}
    assert ("transactions", "transaction_id", "id", "CASCADE") in review_fks
    bid_fks = {(r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list('bids')")}
    assert bid_fks == {("operators", "operator_id", "id", "CASCADE")}
    assert "ix_reviews_transaction_id" in {r[1] for r in conn.execute("PRAGMA index_list('reviews')")}
    assert "ix_operators_vendor_status" in {r[1] for r in conn.execute("PRAGMA index_list('operators')")}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def _snapshot(db_path: Path) -> tuple[list, list]:
    """rating 以外の列の値（件数も含めて比較する）。"""
    conn = _connect(db_path)
    try:
        return (
            conn.execute(f"SELECT {_REVIEW_COLUMNS} FROM reviews ORDER BY id").fetchall(),
            conn.execute(f"SELECT {_OPERATOR_COLUMNS} FROM operators ORDER BY id").fetchall(),
        )
    finally:
        conn.close()


# スキーマ全体（alembic_version の表と索引を除く）。作り直しの有無を1バイト単位で比べる。
_MASTER_SQL = (
    "SELECT type, name, sql FROM sqlite_master WHERE tbl_name <> 'alembic_version' ORDER BY type, name"
)


def _logs(caplog, level: int = logging.INFO) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER_NAME and r.levelno == level]


@pytest.mark.parametrize(
    "rating_check_name",
    [
        # 本番の実名（0004 の "ck_reviews_rating" に命名規約が掛かって二重化した名前）。
        "ck_reviews_ck_reviews_rating",
        # 命名規約が掛からずに作られた DB（名前を推測せず DB から読むことの確認）。
        "ck_reviews_rating",
        # ★の CHECK が無い DB。
        None,
    ],
)
def test_0044_drops_rating_columns_and_round_trips(
    tmp_path, monkeypatch, caplog, rating_check_name
):
    db_path = tmp_path / "0044.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        rating_check = (
            f"CONSTRAINT {rating_check_name} CHECK (rating >= 1 AND rating <= 5),\n    "
            if rating_check_name
            else ""
        )
        # ID は並び順（ORDER BY id）とログの順序を固定するため hex の昇順で決め打ちにする。
        op_rated, op_unrated = "a" * 32, "b" * 32
        txn_ids = [f"{n:032x}" for n in (1, 2, 3)]
        r_user_5, r_op_2, r_hidden_null, r_null = (f"{n:032x}" for n in (11, 12, 13, 14))
        conn = _connect(db_path)
        try:
            conn.executescript(_PRE_0044_SCHEMA_SQL.format(rating_check=rating_check))
            conn.executemany(
                "INSERT INTO operators (id, company_name, rating, review_count, good_count,"
                " improve_count, vendor_status) VALUES (?, ?, ?, ?, ?, ?, 'active')",
                [(op_rated, "★あり株式会社", 4.5, 1, 1, 0), (op_unrated, "★なし合同会社", None, 1, 1, 0)],
            )
            for index, (txn_id, operator_id) in enumerate(
                zip(txn_ids, (op_rated, op_rated, op_unrated))
            ):
                bid_id = f"{index + 100:032x}"
                conn.execute("INSERT INTO bids (id, operator_id) VALUES (?, ?)", (bid_id, operator_id))
                conn.execute("INSERT INTO transactions (id, bid_id) VALUES (?, ?)", (txn_id, bid_id))
            conn.executemany(
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, verdict, comment,"
                " hidden_at, hidden_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (r_user_5, txn_ids[0], "user", 5, "good", "丁寧でした", None, None),
                    (r_op_2, txn_ids[0], "operator", 2, "improve", None, None, None),
                    (r_hidden_null, txn_ids[1], "user", None, "improve", "宣伝", "2026-09-20 00:00:00", "その他"),
                    (r_null, txn_ids[2], "user", None, "good", None, None, None),
                ],
            )
            conn.commit()
        finally:
            conn.close()
        before = _snapshot(db_path)

        cfg = _alembic_config()
        command.stamp(cfg, "0043_audit_active_no_license")
        statements = _run_capturing_sql(lambda: command.upgrade(cfg, "0044_drop_rating_columns"))

        # PostgreSQL だけの lock_timeout・表ロックは SQLite では発行しない（捕捉できていることも確認）。
        assert any("COUNT(*)" in s.upper() for s in statements)
        assert not [s for s in statements if "LOCK TABLE" in s.upper() or "LOCK_TIMEOUT" in s.upper()]
        check_list = rating_check_name or ""
        assert _logs(caplog) == [
            f"0044: 削除する reviews.rating の値（id=rating・2 件）: {r_user_5}=5, {r_op_2}=2",
            f"0044: 削除する operators.rating の値（id=rating・1 件）: {op_rated}=4.5",
            f"0044: reviews.rating（非NULL 2 件・CHECK [{check_list}]）と"
            "operators.rating（非NULL 1 件）を削除。",
        ]
        assert _snapshot(db_path) == before, "rating 以外の列の値と件数は変わらない"
        conn = _connect(db_path)
        try:
            assert "rating" not in _columns(conn, "reviews")
            assert "rating" not in _columns(conn, "operators")
            assert "rating" not in _table_sql(conn, "reviews"), "★の CHECK も消える"
            _assert_schema_preserved(conn)
            # 一意制約・評価の値の CHECK は作り直し後も効く。
            insert_sql = (
                "INSERT INTO reviews (id, transaction_id, reviewer_type, verdict) VALUES (?, ?, ?, ?)"
            )
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
                conn.execute(insert_sql, (uuid.uuid4().hex, txn_ids[0], "user", "good"))
            with pytest.raises(sqlite3.IntegrityError, match="ck_reviews_verdict"):
                conn.execute(insert_sql, (uuid.uuid4().hex, txn_ids[2], "operator", "bad"))
            conn.rollback()
        finally:
            conn.close()

        # downgrade: rating が NULL で戻り、★の範囲の CHECK（実名）が 6 を拒否し NULL を通す。
        caplog.clear()
        command.downgrade(cfg, "0043_audit_active_no_license")
        assert _logs(caplog) == [
            "0044 の downgrade: reviews.rating（CHECK ck_reviews_ck_reviews_rating）と"
            "operators.ratingを NULL 可の列として戻しました（削除した値は復元できず NULL のまま）。"
        ]
        assert _snapshot(db_path) == before
        conn = _connect(db_path)
        try:
            assert _columns(conn, "reviews")["rating"] == 0
            assert _columns(conn, "operators")["rating"] == 0
            assert conn.execute("SELECT COUNT(*) FROM reviews WHERE rating IS NOT NULL").fetchone() == (0,)
            assert conn.execute("SELECT COUNT(*) FROM operators WHERE rating IS NOT NULL").fetchone() == (0,)
            _assert_schema_preserved(conn)
            assert "CONSTRAINT ck_reviews_ck_reviews_rating " in _table_sql(conn, "reviews")
            insert_sql = (
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, verdict)"
                " VALUES (?, ?, 'operator', ?, 'good')"
            )
            with pytest.raises(sqlite3.IntegrityError, match="ck_reviews_ck_reviews_rating"):
                conn.execute(insert_sql, (uuid.uuid4().hex, txn_ids[2], 6))
            conn.rollback()
            conn.execute(insert_sql, (uuid.uuid4().hex, txn_ids[2], None))
            conn.execute("UPDATE reviews SET rating = 3 WHERE id = ?", (r_null,))
            conn.commit()
        finally:
            conn.close()

        # 往復（2回目の upgrade）: downgrade が作った実名の CHECK を読んで落とす。
        caplog.clear()
        command.upgrade(cfg, "0044_drop_rating_columns")
        assert _logs(caplog) == [
            f"0044: 削除する reviews.rating の値（id=rating・1 件）: {r_null}=3",
            "0044: reviews.rating（非NULL 1 件・CHECK [ck_reviews_ck_reviews_rating]）と"
            "operators.rating（非NULL 0 件）を削除。",
        ]
        conn = _connect(db_path)
        try:
            assert "rating" not in _columns(conn, "reviews")
            assert "rating" not in _columns(conn, "operators")
            assert "rating" not in _table_sql(conn, "reviews")
            _assert_schema_preserved(conn)
            assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone() == (5,)
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0044_is_a_noop_when_rating_columns_are_already_gone(tmp_path, monkeypatch, caplog):
    """rating 列が既に無い DB（手で消した・再実行など）では何も変えずに通る（表も作り直さない）。"""
    db_path = tmp_path / "0044_noop.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        schema = (
            _PRE_0044_SCHEMA_SQL.format(rating_check="")
            .replace("    rating FLOAT,\n", "")
            .replace("    rating INTEGER,\n", "")
        )
        conn = _connect(db_path)
        try:
            conn.executescript(schema)
            master_before = conn.execute(_MASTER_SQL).fetchall()
        finally:
            conn.close()
        assert "rating" not in schema

        cfg = _alembic_config()
        command.stamp(cfg, "0043_audit_active_no_license")
        command.upgrade(cfg, "0044_drop_rating_columns")
        assert _logs(caplog) == [
            "0044: reviews.rating は既に無いため飛ばしました（冪等）。",
            "0044: operators.rating は既に無いため飛ばしました（冪等）。",
        ]
        conn = _connect(db_path)
        try:
            master_after = conn.execute(_MASTER_SQL).fetchall()
        finally:
            conn.close()
        # alembic_version（stamp が作る表と索引）以外は1バイトも変わらない（表を作り直していない）。
        assert master_after == master_before
    finally:
        get_settings.cache_clear()


def test_0044_locks_reviews_then_operators_waiting_at_most_3s_only_on_postgresql(monkeypatch):
    """PostgreSQL では LOCK の間だけ lock_timeout を 3s にし、reviews → operators の順に ACCESS EXCLUSIVE を
    取ってから 10s へ戻す。SQLite では何も発行しない。実 PostgreSQL が無い環境でも文の順序を固定するため、
    マイグレーションの op を差し替えて確かめる（実 PG の往復は ci.yml の pg-concurrency が通す）。"""
    from types import SimpleNamespace

    from alembic.script import ScriptDirectory

    module = (
        ScriptDirectory.from_config(_alembic_config())
        .get_revision("0044_drop_rating_columns")
        .module
    )
    for dialect, expected in (
        (
            "postgresql",
            [
                "SET LOCAL lock_timeout = '3s'",
                "LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE",
                "LOCK TABLE operators IN ACCESS EXCLUSIVE MODE",
                "SET LOCAL lock_timeout = '10s'",
            ],
        ),
        ("sqlite", []),
    ):
        executed: list[str] = []
        fake_op = SimpleNamespace(
            get_bind=lambda dialect=dialect: SimpleNamespace(dialect=SimpleNamespace(name=dialect)),
            execute=lambda statement: executed.append(str(statement)),
        )
        monkeypatch.setattr(module, "op", fake_op)
        module._lock_tables_for_alter()
        assert executed == expected, dialect


def test_0044_is_chained_from_0043_on_a_single_head():
    """0044 が 0043 に正しく連鎖し、履歴が単一の head に収束していること（分岐の防止）。

    head そのものの固定は最新リビジョンのテスト（現在は test_0045_review_hidden_by_admin_migration.py）
    が持つ（test_0041・test_0042 と同じ作法）。
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    assert len(script.get_heads()) == 1
    rev_0044 = script.get_revision("0044_drop_rating_columns")
    assert rev_0044.down_revision == "0043_audit_active_no_license"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0044.revision) <= 32
