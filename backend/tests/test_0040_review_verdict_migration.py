"""0040_review_verdict（評価の2択化・expand 段階）の回帰テスト。

test_0037_0038_migrations.py と同じ理由（alembic の env.py が内部で
``asyncio.run()`` を呼ぶため ``async def`` にはできない）で同期テストにしている。

- 既存レビューを ★4・5 → good／★1〜3 → improve に変換する（非表示・業者→依頼者も含む
  全行）。rating は書き換えない。
- operators.good_count / improve_count / review_count を「依頼者→業者・非表示を除く」
  母集団から再計算し、不変条件 review_count = good_count + improve_count を成立させる。
  ずれていた業者は WARNING、件数の証跡は INFO で残す。
- CHECK ck_reviews_verdict は good / improve 以外を拒否し、NULL（expand 期間中の旧コードの
  INSERT）は通す。
- SQLite の batch（テーブル作り直し）後も既存の名前付き制約・FK・索引が残る
  （設計時の [要確認] 事項をここで固定する）。
- downgrade で追加した3列と CHECK が消え、rating と行数は不変。再 upgrade で同じ結果。
- 0039_sessions_revoked_at に連鎖し、リビジョン ID が 32 文字以内（head の固定は最新リビジョンの
  テスト、分岐の防止は test_0036 の ``len(get_heads()) == 1`` が持つ）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_LOGGER_NAME = "alembic.versions.0040_review_verdict"

# 0039_sessions_revoked_at 適用済み相当の最小スキーマ（0040 が触る4テーブルのみ）。reviews の
# 制約名・FK・索引は 0004_katadzuke_schema.py に書かれた名前にしている（batch の作り直しで
# 消えないことを確かめるため。本番の CHECK の実名は命名規約が掛かった ck_reviews_ck_reviews_…
# だが、名前付き制約が残るかの確認に名前の違いは影響しない）。FK 句は SQLAlchemy が出力する
# DDL と同じく1行で書く: SQLite の反映はテーブル定義 SQL を正規表現で読み、FK 句の途中に改行が
# あると制約名と ON DELETE を取りこぼす（作り直し後の FK から CASCADE が消える。実装時にこの
# テストで確認済み）。
_PRE_0040_SCHEMA_SQL = """
CREATE TABLE operators (
    id CHAR(32) PRIMARY KEY,
    rating FLOAT,
    review_count INTEGER DEFAULT '0' NOT NULL,
    latest_review_comment VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    id CHAR(32) NOT NULL,
    transaction_id CHAR(32) NOT NULL,
    reviewer_type VARCHAR(32) NOT NULL,
    rating INTEGER NOT NULL,
    comment TEXT,
    hidden_at TIMESTAMP,
    hidden_reason VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_reviews PRIMARY KEY (id),
    CONSTRAINT fk_reviews_transaction_id_transactions FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
    CONSTRAINT uq_reviews_transaction_reviewer UNIQUE (transaction_id, reviewer_type),
    CONSTRAINT ck_reviews_rating CHECK (rating >= 1 AND rating <= 5),
    CONSTRAINT ck_reviews_reviewer_type CHECK (reviewer_type IN ('user','operator'))
);
CREATE INDEX ix_reviews_transaction_id ON reviews (transaction_id);
"""

# 作り直し後も残っているべき既存の名前付き制約。
_PRESERVED_REVIEW_CONSTRAINTS = (
    "pk_reviews",
    "fk_reviews_transaction_id_transactions",
    "uq_reviews_transaction_reviewer",
    "ck_reviews_rating",
    "ck_reviews_reviewer_type",
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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')")}


def _reviews_table_sql(conn: sqlite3.Connection) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reviews'"
    ).fetchone()[0]


def _assert_existing_review_schema_preserved(conn: sqlite3.Connection) -> None:
    """batch の作り直し後も、既存の名前付き制約・FK・索引が残り、実際に効いていること。"""
    table_sql = _reviews_table_sql(conn)
    for name in _PRESERVED_REVIEW_CONSTRAINTS:
        # 部分一致だと命名規約で二重化した名前（ck_reviews_ck_reviews_…）も通るため、
        # "CONSTRAINT <名前> " の形で完全一致を見る。
        assert f"CONSTRAINT {name} " in table_sql, f"作り直しで制約 {name} が消えた: {table_sql}"
    fks = {(r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list('reviews')")}
    assert ("transactions", "transaction_id", "id", "CASCADE") in fks
    indexes = {r[1] for r in conn.execute("PRAGMA index_list('reviews')")}
    assert "ix_reviews_transaction_id" in indexes


def _snapshot(conn: sqlite3.Connection) -> tuple[dict, dict]:
    verdicts = dict(conn.execute("SELECT id, verdict FROM reviews").fetchall())
    counts = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT id, good_count, improve_count, review_count FROM operators"
        )
    }
    return verdicts, counts


def test_0040_converts_ratings_recalculates_counts_and_round_trips(
    tmp_path, monkeypatch, caplog
):
    db_path = tmp_path / "0040.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        op_rated, op_no_reviews, op_drifted = (uuid.uuid4().hex for _ in range(3))
        # 依頼者→業者 ★1〜5（★5 は運営が非表示）と、業者→依頼者 ★5・★2。
        txn_ids = [uuid.uuid4().hex for _ in range(5)]
        user_reviews = {
            uuid.uuid4().hex: (txn_ids[star - 1], star, "2026-09-20 00:00:00" if star == 5 else None)
            for star in range(1, 6)
        }
        op_review_good, op_review_improve = uuid.uuid4().hex, uuid.uuid4().hex
        drift_txn, drift_review = uuid.uuid4().hex, uuid.uuid4().hex

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0040_SCHEMA_SQL)
            conn.executemany(
                "INSERT INTO operators (id, rating, review_count) VALUES (?, ?, ?)",
                [
                    # 旧コードの集計どおり（公開中の依頼者レビュー ★1〜4 の4件）。
                    (op_rated, 2.5, 4),
                    (op_no_reviews, None, 0),
                    # 実件数1件に対して review_count が 3 にずれている業者。
                    (op_drifted, 4.0, 3),
                ],
            )
            for txn_id in txn_ids:
                bid_id = uuid.uuid4().hex
                conn.execute("INSERT INTO bids (id, operator_id) VALUES (?, ?)", (bid_id, op_rated))
                conn.execute("INSERT INTO transactions (id, bid_id) VALUES (?, ?)", (txn_id, bid_id))
            drift_bid = uuid.uuid4().hex
            conn.execute("INSERT INTO bids (id, operator_id) VALUES (?, ?)", (drift_bid, op_drifted))
            conn.execute("INSERT INTO transactions (id, bid_id) VALUES (?, ?)", (drift_txn, drift_bid))
            conn.executemany(
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, comment, hidden_at)"
                " VALUES (?, ?, 'user', ?, ?, ?)",
                [
                    (review_id, txn_id, star, f"★{star}", hidden_at)
                    for review_id, (txn_id, star, hidden_at) in user_reviews.items()
                ]
                + [(drift_review, drift_txn, 4, "ずれ業者", None)],
            )
            conn.executemany(
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating) VALUES (?, ?, 'operator', ?)",
                [(op_review_good, txn_ids[0], 5), (op_review_improve, txn_ids[1], 2)],
            )
            conn.commit()
            ratings_before = dict(conn.execute("SELECT id, rating FROM reviews").fetchall())
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0039_sessions_revoked_at")
        command.upgrade(cfg, "0040_review_verdict")

        info_logs = [
            r.getMessage() for r in caplog.records if r.name == _LOGGER_NAME and r.levelno == logging.INFO
        ]
        warning_logs = [
            r.getMessage() for r in caplog.records if r.name == _LOGGER_NAME and r.levelno == logging.WARNING
        ]
        assert info_logs == [
            "0040: reviews.verdict を 8 件設定（依頼者→業者: よかった 3／伸びしろ 3〔うち★3 1〕、"
            "業者→依頼者: よかった 1／伸びしろ 1）。業者 3 件の集計を再計算（review_count の補正 1 件）。"
        ]
        assert len(warning_logs) == 1 and "1 件" in warning_logs[0]

        expected_verdicts = {
            **{
                review_id: ("good" if star >= 4 else "improve")
                for review_id, (_, star, _) in user_reviews.items()
            },
            drift_review: "good",
            op_review_good: "good",
            op_review_improve: "improve",
        }
        # (good_count, improve_count, review_count)。非表示の ★5 と業者→依頼者は数えない。
        expected_counts = {
            op_rated: (1, 3, 4),
            op_no_reviews: (0, 0, 0),
            op_drifted: (1, 0, 1),
        }

        conn = sqlite3.connect(str(db_path))
        try:
            verdicts, counts = _snapshot(conn)
            assert verdicts == expected_verdicts, "★4・5→good／★1〜3→improve（非表示・業者レビュー含む）"
            assert counts == expected_counts
            assert all(good + improve == total for good, improve, total in counts.values())
            assert dict(conn.execute("SELECT id, rating FROM reviews").fetchall()) == ratings_before

            _assert_existing_review_schema_preserved(conn)
            # 命名規約で "ck_reviews_ck_reviews_verdict" に二重化していないこと（op.f() の回帰）。
            assert "CONSTRAINT ck_reviews_verdict CHECK" in _reviews_table_sql(conn)

            # CHECK: 'bad' は拒否し、NULL（expand 期間中の旧コードの INSERT）は通す。
            # 既存制約も作り直し後に実際に効いている。確認用の行は最後に巻き戻す。
            insert_sql = (
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, verdict)"
                " VALUES (?, ?, ?, ?, ?)"
            )
            with pytest.raises(sqlite3.IntegrityError, match="ck_reviews_verdict"):
                conn.execute(insert_sql, (uuid.uuid4().hex, drift_txn, "operator", 3, "bad"))
            with pytest.raises(sqlite3.IntegrityError, match="ck_reviews_rating"):
                conn.execute(insert_sql, (uuid.uuid4().hex, drift_txn, "operator", 6, "good"))
            with pytest.raises(sqlite3.IntegrityError, match="ck_reviews_reviewer_type"):
                conn.execute(insert_sql, (uuid.uuid4().hex, drift_txn, "admin", 3, "good"))
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
                conn.execute(insert_sql, (uuid.uuid4().hex, drift_txn, "user", 3, "good"))
            conn.execute(insert_sql, (uuid.uuid4().hex, drift_txn, "operator", 3, None))
            conn.rollback()
        finally:
            conn.close()

        command.downgrade(cfg, "0039_sessions_revoked_at")
        conn = sqlite3.connect(str(db_path))
        try:
            assert "verdict" not in _columns(conn, "reviews")
            assert not {"good_count", "improve_count"} & _columns(conn, "operators")
            assert dict(conn.execute("SELECT id, rating FROM reviews").fetchall()) == ratings_before
            _assert_existing_review_schema_preserved(conn)
            assert "verdict" not in _reviews_table_sql(conn)
            # review_count の補正は「正しい値への是正」のため downgrade でも戻さない。
            assert conn.execute(
                "SELECT review_count FROM operators WHERE id = ?", (op_drifted,)
            ).fetchone() == (1,)
        finally:
            conn.close()

        # 往復: 再 upgrade で同じ結果。補正済みのため2回目はずれ 0 件・WARNING なし。
        caplog.clear()
        command.upgrade(cfg, "0040_review_verdict")
        second_logs = [r for r in caplog.records if r.name == _LOGGER_NAME]
        assert [r.levelno for r in second_logs] == [logging.INFO]
        assert "review_count の補正 0 件" in second_logs[0].getMessage()
        conn = sqlite3.connect(str(db_path))
        try:
            assert _snapshot(conn) == (expected_verdicts, expected_counts)
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0040_is_chained_from_0039_sessions_revoked_at():
    """0040 が 0039_sessions_revoked_at に正しく連鎖していること。

    head そのものの固定は最新リビジョンのテスト（現在は test_0041_review_verdict_recount_migration.py）、
    分岐の防止は test_0036 の ``len(script.get_heads()) == 1`` が持つ（0041 以降の追加で本テストが
    壊れないようにする）。
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    rev_0040 = script.get_revision("0040_review_verdict")
    assert rev_0040.down_revision == "0039_sessions_revoked_at"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0040.revision) <= 32
