"""0042_review_verdict_contract（評価の2択化の後片付け・contract）の回帰テスト。

test_0040 / test_0041 と同じ理由（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため
``async def`` にはできない）で同期テストにしている。

- verdict が NULL の行を ★4以上→good／★3以下→improve で補完してから、verdict を NOT NULL、
  rating を NULL 可にする（PRAGMA table_info で確認）。rating の値は書き換えない。
- SQLite の batch（表の作り直し）後も既存の名前付き制約・FK・索引が残る。
- 件数がずれている業者だけを再計算する（ずれていない業者の行は更新しない。トリガーで記録して
  確かめる）。件数の証跡は INFO、ずれがあれば WARNING。
- PostgreSQL だけで発行する lock_timeout と表ロックは、SQLite では発行しない。
- downgrade で rating が NULL の行（段B 以降に書かれた行）が互換値（good=5／improve=2）で埋まり、
  rating NOT NULL・verdict NULL 可に戻る。再 upgrade（往復・2回目）は補完 0 件・再計算 0 件。
- 0042 が 0041 に連鎖し単一の head に収束していて、リビジョン ID が 32 文字以内（head そのものの
  固定は最新リビジョンのテストへ移設。現在は test_0043_audit_active_no_license_migration.py）。
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
_LOGGER_NAME = "alembic.versions.0042_review_verdict_contract"

# 0041 適用済み相当の最小スキーマ（0042 が触る4テーブル）。reviews の制約名は本番の実名
# （0004 の CHECK は命名規約で ck_reviews_ck_reviews_…。tests/test_review_model_constraints.py 参照）。
# FK 句を1行で書く理由は test_0040 と同じ（SQLite の反映が改行入りの FK 句を読み落とす）。
_PRE_0042_SCHEMA_SQL = """
CREATE TABLE operators (
    id CHAR(32) PRIMARY KEY,
    rating FLOAT,
    review_count INTEGER DEFAULT '0' NOT NULL,
    good_count INTEGER DEFAULT '0' NOT NULL,
    improve_count INTEGER DEFAULT '0' NOT NULL,
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
    verdict VARCHAR(16),
    comment TEXT,
    hidden_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_reviews PRIMARY KEY (id),
    CONSTRAINT fk_reviews_transaction_id_transactions FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
    CONSTRAINT uq_reviews_transaction_reviewer UNIQUE (transaction_id, reviewer_type),
    CONSTRAINT ck_reviews_ck_reviews_rating CHECK (rating >= 1 AND rating <= 5),
    CONSTRAINT ck_reviews_ck_reviews_reviewer_type CHECK (reviewer_type IN ('user','operator')),
    CONSTRAINT ck_reviews_verdict CHECK (verdict IN ('good','improve'))
);
CREATE INDEX ix_reviews_transaction_id ON reviews (transaction_id);
-- 更新された業者行の記録（ずれていない業者が UPDATE の対象にならないことの確認用）。
CREATE TABLE operator_updates (operator_id CHAR(32) NOT NULL);
CREATE TRIGGER trg_operator_updates AFTER UPDATE ON operators
BEGIN
    INSERT INTO operator_updates (operator_id) VALUES (NEW.id);
END;
"""

# 表の作り直し後も残っているべき名前付き制約。
_PRESERVED_REVIEW_CONSTRAINTS = (
    "pk_reviews",
    "fk_reviews_transaction_id_transactions",
    "uq_reviews_transaction_reviewer",
    "ck_reviews_ck_reviews_rating",
    "ck_reviews_ck_reviews_reviewer_type",
    "ck_reviews_verdict",
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


def _notnull(conn: sqlite3.Connection) -> dict[str, int]:
    """reviews の verdict / rating の NOT NULL 指定（1＝NOT NULL、0＝NULL 可）。"""
    return {
        row[1]: row[3]
        for row in conn.execute("PRAGMA table_info('reviews')")
        if row[1] in ("verdict", "rating")
    }


def _assert_review_schema_preserved(conn: sqlite3.Connection) -> None:
    """表の作り直し後も、名前付き制約・FK（ON DELETE CASCADE）・索引が残っていること。"""
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reviews'"
    ).fetchone()[0]
    for name in _PRESERVED_REVIEW_CONSTRAINTS:
        # 部分一致だと命名規約で二重化した名前も通るため "CONSTRAINT <名前> " の形で見る。
        assert f"CONSTRAINT {name} " in table_sql, f"作り直しで制約 {name} が消えた: {table_sql}"
    fks = {(r[2], r[3], r[4], r[6]) for r in conn.execute("PRAGMA foreign_key_list('reviews')")}
    assert ("transactions", "transaction_id", "id", "CASCADE") in fks
    assert "ix_reviews_transaction_id" in {r[1] for r in conn.execute("PRAGMA index_list('reviews')")}


def _snapshot(db_path: Path) -> tuple[dict, dict, dict]:
    conn = _connect(db_path)
    try:
        verdicts = dict(conn.execute("SELECT id, verdict FROM reviews").fetchall())
        ratings = dict(conn.execute("SELECT id, rating FROM reviews").fetchall())
        counts = {
            row[0]: (row[1], row[2], row[3])
            for row in conn.execute(
                "SELECT id, good_count, improve_count, review_count FROM operators"
            )
        }
        return verdicts, ratings, counts
    finally:
        conn.close()


def _updated_operator_ids(db_path: Path) -> list[str]:
    conn = _connect(db_path)
    try:
        return sorted(row[0] for row in conn.execute("SELECT operator_id FROM operator_updates"))
    finally:
        conn.close()


def _logs(caplog, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER_NAME and r.levelno == level]


def test_0042_makes_verdict_not_null_and_rating_nullable_and_round_trips(
    tmp_path, monkeypatch, caplog
):
    db_path = tmp_path / "0042.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        # op_drifted: 0041 の後に verdict NULL の依頼者★4 が残り、good_count が 1 のまま（ずれ）。
        # op_consistent: 整合済み（行を更新しないこと）。op_empty: 評価なし。
        op_drifted, op_consistent, op_empty = (uuid.uuid4().hex for _ in range(3))
        # key: (業者, 取引キー, reviewer_type, rating, verdict, hidden_at)
        rows = {
            "r_good": (op_drifted, "a1", "user", 5, "good", None),
            "r_null_4": (op_drifted, "a2", "user", 4, None, None),
            "r_hidden": (op_drifted, "a3", "user", 2, "improve", "2026-09-20 00:00:00"),
            "r_op_null_1": (op_drifted, "a1", "operator", 1, None, None),
            "r_consistent": (op_consistent, "b1", "user", 2, "improve", None),
            # ★3 は境界（4 未満）なので improve に補完される。業者→依頼者なので件数には影響しない。
            "r_op_null_3": (op_consistent, "c1", "operator", 3, None, None),
        }
        review_ids = {key: uuid.uuid4().hex for key in rows}
        txn_of: dict[str, str] = {}

        conn = _connect(db_path)
        try:
            conn.executescript(_PRE_0042_SCHEMA_SQL)
            conn.executemany(
                "INSERT INTO operators (id, review_count, good_count, improve_count)"
                " VALUES (?, ?, ?, ?)",
                [(op_drifted, 1, 1, 0), (op_consistent, 1, 0, 1), (op_empty, 0, 0, 0)],
            )
            for operator_id, txn_key, *_ in rows.values():
                if txn_key in txn_of:
                    continue
                bid_id, txn_of[txn_key] = uuid.uuid4().hex, uuid.uuid4().hex
                conn.execute("INSERT INTO bids (id, operator_id) VALUES (?, ?)", (bid_id, operator_id))
                conn.execute(
                    "INSERT INTO transactions (id, bid_id) VALUES (?, ?)", (txn_of[txn_key], bid_id)
                )
            conn.executemany(
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, verdict, hidden_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (review_ids[key], txn_of[txn_key], reviewer_type, rating, verdict, hidden_at)
                    for key, (_, txn_key, reviewer_type, rating, verdict, hidden_at) in rows.items()
                ],
            )
            conn.commit()
        finally:
            conn.close()
        _, ratings_before, _ = _snapshot(db_path)

        cfg = _alembic_config()
        command.stamp(cfg, "0041_review_verdict_recount")
        statements = _run_capturing_sql(
            lambda: command.upgrade(cfg, "0042_review_verdict_contract")
        )

        # PostgreSQL だけの lock_timeout・表ロックは SQLite では発行しない（捕捉できていることも確認）。
        assert any(s.lstrip().upper().startswith("UPDATE OPERATORS") for s in statements)
        assert not [s for s in statements if "LOCK TABLE" in s.upper() or "LOCK_TIMEOUT" in s.upper()]
        assert _logs(caplog, logging.INFO) == [
            "0042: verdict を 3 件補完し NOT NULL 化、rating を NULL 可に変更。"
            "件数がずれていた業者 1 件を再計算（更新 1 件）。"
        ]
        warnings = _logs(caplog, logging.WARNING)
        assert len(warnings) == 1 and "1 件" in warnings[0]

        expected_verdicts = {
            review_ids["r_good"]: "good",
            review_ids["r_null_4"]: "good",
            review_ids["r_hidden"]: "improve",
            review_ids["r_op_null_1"]: "improve",
            review_ids["r_consistent"]: "improve",
            review_ids["r_op_null_3"]: "improve",
        }
        # (good_count, improve_count, review_count)。非表示と業者→依頼者は数えない。
        expected_counts = {op_drifted: (2, 0, 2), op_consistent: (0, 1, 1), op_empty: (0, 0, 0)}
        verdicts, ratings, counts = _snapshot(db_path)
        assert verdicts == expected_verdicts
        assert ratings == ratings_before, "upgrade は rating を書き換えない"
        assert counts == expected_counts
        assert _updated_operator_ids(db_path) == [op_drifted], "ずれていない業者の行は更新しない"

        conn = _connect(db_path)
        try:
            assert _notnull(conn) == {"verdict": 1, "rating": 0}
            _assert_review_schema_preserved(conn)
            insert_sql = (
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, verdict)"
                " VALUES (?, ?, 'operator', ?, ?)"
            )
            with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
                conn.execute(insert_sql, (uuid.uuid4().hex, txn_of["b1"], 3, None))
            # rating の CHECK（1〜5）は作り直し後も効き、範囲外は拒否する（NULL は下の段B の行で通る）。
            for out_of_range in (0, 6):
                with pytest.raises(sqlite3.IntegrityError, match="ck_reviews_ck_reviews_rating"):
                    conn.execute(insert_sql, (uuid.uuid4().hex, txn_of["b1"], out_of_range, "good"))
            conn.rollback()
            # 段B のコードが書く行（rating を書かない＝NULL）。業者→依頼者なので件数には影響しない。
            stage_b_good, stage_b_improve = uuid.uuid4().hex, uuid.uuid4().hex
            conn.execute(insert_sql, (stage_b_good, txn_of["b1"], None, "good"))
            conn.execute(insert_sql, (stage_b_improve, txn_of["a2"], None, "improve"))
            conn.commit()
        finally:
            conn.close()

        # downgrade: rating が NULL の行を互換値で埋め、rating NOT NULL・verdict NULL 可へ戻す。
        command.downgrade(cfg, "0041_review_verdict_recount")
        verdicts, ratings, counts = _snapshot(db_path)
        assert ratings == {**ratings_before, stage_b_good: 5, stage_b_improve: 2}
        assert verdicts == {**expected_verdicts, stage_b_good: "good", stage_b_improve: "improve"}
        assert counts == expected_counts
        conn = _connect(db_path)
        try:
            assert _notnull(conn) == {"verdict": 0, "rating": 1}
            _assert_review_schema_preserved(conn)
        finally:
            conn.close()

        # 往復（2回目）: 補完 0 件・再計算 0 件で WARNING なし。値と制約は1回目と同じ。
        caplog.clear()
        command.upgrade(cfg, "0042_review_verdict_contract")
        assert _logs(caplog, logging.INFO) == [
            "0042: verdict を 0 件補完し NOT NULL 化、rating を NULL 可に変更。"
            "件数がずれていた業者 0 件を再計算（更新 0 件）。"
        ]
        assert _logs(caplog, logging.WARNING) == []
        assert _snapshot(db_path) == (
            {**expected_verdicts, stage_b_good: "good", stage_b_improve: "improve"},
            {**ratings_before, stage_b_good: 5, stage_b_improve: 2},
            expected_counts,
        )
        assert _updated_operator_ids(db_path) == [op_drifted], "2回目は行を更新しない"
        conn = _connect(db_path)
        try:
            assert _notnull(conn) == {"verdict": 1, "rating": 0}
            _assert_review_schema_preserved(conn)
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()


def test_0042_waits_for_the_reviews_lock_at_most_3s_only_on_postgresql(monkeypatch):
    """PostgreSQL では LOCK の直前だけ lock_timeout を 3s にし、取得後に 10s へ戻す（待ち行列の後ろに
    読み手が並ぶ時間を短くし、取れなければ start.sh のリトライに任せる）。SQLite では何も発行しない。
    実 DB の PostgreSQL が無い環境でも文の順序を固定するため、マイグレーションの op を差し替えて確かめる。"""
    from types import SimpleNamespace

    from alembic.script import ScriptDirectory

    module = (
        ScriptDirectory.from_config(_alembic_config())
        .get_revision("0042_review_verdict_contract")
        .module
    )
    for dialect, expected in (
        (
            "postgresql",
            [
                "SET LOCAL lock_timeout = '3s'",
                "LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE",
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
        module._lock_reviews_for_alter()
        assert executed == expected, dialect


def test_0042_is_chained_from_0041_on_a_single_head():
    """0042 が 0041 に正しく連鎖し、履歴が単一の head に収束していること（分岐の防止）。

    head そのものの固定は最新リビジョンのテスト（現在は test_0043_audit_active_no_license_migration.py）
    が持つ（0043 以降の追加で本テストが head 固定のまま壊れないようにする。test_0041 と同じ作法）。
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    rev_0042 = script.get_revision("0042_review_verdict_contract")
    assert rev_0042.down_revision == "0041_review_verdict_recount"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0042.revision) <= 32
