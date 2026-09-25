"""0041_review_verdict_recount（P1〜P2 間のずれの補正・データ是正のみ）の回帰テスト。

test_0040_review_verdict_migration.py と同じ理由（alembic の env.py が内部で
``asyncio.run()`` を呼ぶため ``async def`` にはできない）で同期テストにしている。

- 0040 適用後・新コード切替前に旧コードが書いた行（verdict 列 NULL）を ★4以上→good／
  ★3以下→improve で補完する（非表示・業者→依頼者も含む全行）。rating は書き換えない。
- 旧コードの投稿・非表示で good_count / improve_count が review_count とずれた業者だけを、
  「依頼者→業者・非表示を除く」母集団から再計算して補正する。ずれの無い業者の行は更新しない
  （UPDATE の対象外。更新された行をトリガーで記録して確かめる）。
- PostgreSQL だけで発行する lock_timeout と LOCK TABLE reviews IN SHARE MODE は、SQLite では
  発行しない（実行された SQL を捕捉して確かめる）。
- 件数の証跡は INFO、補正があれば WARNING。2回目は補完 0 件・補正 0 件（冪等）。
- downgrade は no-op（データ是正のため戻さない）。
- 0040 → 0041 を1回の upgrade で続けて流すと、0041 は補完 0 件・再計算 0 件で 0040 の結果を
  変えない（P1 と P2 を同時にデプロイした場合・空の DB を最新まで上げる場合の経路）。
- head が 0041 の単独チェーンで、リビジョン ID が 32 文字以内（head の固定は最新リビジョンの
  テストである本ファイルが持つ）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_LOGGER_NAME = "alembic.versions.0041_review_verdict_recount"

# 0040 適用済み相当の最小スキーマ（0041 が読み書きする4テーブルの、判定に使う列のみ）。
_PRE_0041_SCHEMA_SQL = """
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
    id CHAR(32) PRIMARY KEY,
    transaction_id CHAR(32) NOT NULL REFERENCES transactions (id),
    reviewer_type VARCHAR(32) NOT NULL,
    rating INTEGER NOT NULL,
    verdict VARCHAR(16),
    hidden_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_reviews_transaction_reviewer UNIQUE (transaction_id, reviewer_type),
    CONSTRAINT ck_reviews_verdict CHECK (verdict IN ('good','improve'))
);
-- 更新された業者行の記録（ずれていない業者が UPDATE の対象にならないことの確認用）。
CREATE TABLE operator_updates (operator_id CHAR(32) NOT NULL);
CREATE TRIGGER trg_operator_updates AFTER UPDATE ON operators
BEGIN
    INSERT INTO operator_updates (operator_id) VALUES (NEW.id);
END;
"""


# 0039_sessions_revoked_at 適用済み相当の最小スキーマ（0040 → 0041 の連続適用の確認用。
# test_0040_review_verdict_migration.py の事前スキーマを、0040 / 0041 が触る列に絞ったもの）。
# FK 句を1行で書く理由は test_0040 と同じ（SQLite の反映が改行入りの FK 句を読み落とす）。
_PRE_0040_SCHEMA_SQL = """
CREATE TABLE operators (
    id CHAR(32) PRIMARY KEY,
    rating FLOAT,
    review_count INTEGER DEFAULT '0' NOT NULL,
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
    hidden_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_reviews PRIMARY KEY (id),
    CONSTRAINT fk_reviews_transaction_id_transactions FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
    CONSTRAINT uq_reviews_transaction_reviewer UNIQUE (transaction_id, reviewer_type)
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


def _snapshot(db_path: Path) -> tuple[dict, dict, dict]:
    conn = sqlite3.connect(str(db_path))
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


def _logs(caplog, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER_NAME and r.levelno == level]


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


def _updated_operator_ids(db_path: Path) -> list[str]:
    """トリガーが記録した「UPDATE された業者行」（値が変わらない更新も含む）。"""
    conn = sqlite3.connect(str(db_path))
    try:
        return sorted(row[0] for row in conn.execute("SELECT operator_id FROM operator_updates"))
    finally:
        conn.close()


def test_0041_fills_null_verdicts_and_recounts_only_drifted_operators(
    tmp_path, monkeypatch, caplog
):
    db_path = tmp_path / "0041.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        # op_posted: 0040 時点の★5（good）に加え、旧コードが★4・★3 を投稿し★2 を投稿後に非表示。
        #            旧コードの集計は review_count だけを 3 に更新（good 1・improve 0 のまま）。
        # op_consistent: 新コードの improve 1件で整合済み（値が変わらないこと）。
        # op_empty: 評価なし。
        # op_hidden: good 1件を旧コードの運営操作が非表示にし、review_count だけ 0 に下がった。
        op_posted, op_consistent, op_empty, op_hidden = (uuid.uuid4().hex for _ in range(4))
        txn_of: dict[str, str] = {}
        # (review_id, 業者, 取引キー, reviewer_type, rating, verdict, hidden_at)
        rows = [
            ("r_good_new", op_posted, "p1", "user", 5, "good", None),
            ("r_legacy_4", op_posted, "p2", "user", 4, None, None),
            ("r_legacy_3", op_posted, "p3", "user", 3, None, None),
            ("r_legacy_2_hidden", op_posted, "p4", "user", 2, None, "2026-09-25 00:00:00"),
            ("r_legacy_op_5", op_posted, "p1", "operator", 5, None, None),
            ("r_consistent", op_consistent, "c1", "user", 2, "improve", None),
            ("r_hidden_good", op_hidden, "h1", "user", 5, "good", "2026-09-25 00:00:00"),
        ]
        review_ids = {key: uuid.uuid4().hex for key, *_ in rows}

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0041_SCHEMA_SQL)
            conn.executemany(
                "INSERT INTO operators (id, review_count, good_count, improve_count)"
                " VALUES (?, ?, ?, ?)",
                [
                    (op_posted, 3, 1, 0),
                    (op_consistent, 1, 0, 1),
                    (op_empty, 0, 0, 0),
                    (op_hidden, 0, 1, 0),
                ],
            )
            for _, operator_id, txn_key, *_ in rows:
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
                    for key, _, txn_key, reviewer_type, rating, verdict, hidden_at in rows
                ],
            )
            conn.commit()
        finally:
            conn.close()
        _, ratings_before, _ = _snapshot(db_path)

        cfg = _alembic_config()
        command.stamp(cfg, "0040_review_verdict")
        statements = _run_capturing_sql(
            lambda: command.upgrade(cfg, "0041_review_verdict_recount")
        )

        # PostgreSQL だけの lock_timeout・表ロックは SQLite では発行しない（捕捉できていることも確認）。
        assert any(s.lstrip().upper().startswith("UPDATE OPERATORS") for s in statements)
        assert not [s for s in statements if "LOCK TABLE" in s.upper() or "LOCK_TIMEOUT" in s.upper()]
        assert _logs(caplog, logging.INFO) == [
            "0041: verdict が未設定だった評価を 4 件補完しました（P1〜P2 の間に旧コードが書いた行）。"
            "件数がずれていた業者 2 件の集計を再計算しました（更新 2 件）。"
        ]
        warnings = _logs(caplog, logging.WARNING)
        assert len(warnings) == 1 and "2 件" in warnings[0]

        expected_verdicts = {
            review_ids["r_good_new"]: "good",
            review_ids["r_legacy_4"]: "good",
            review_ids["r_legacy_3"]: "improve",
            review_ids["r_legacy_2_hidden"]: "improve",
            review_ids["r_legacy_op_5"]: "good",
            review_ids["r_consistent"]: "improve",
            review_ids["r_hidden_good"]: "good",
        }
        # (good_count, improve_count, review_count)。非表示と業者→依頼者は数えない。
        expected_counts = {
            op_posted: (2, 1, 3),
            op_consistent: (0, 1, 1),
            op_empty: (0, 0, 0),
            op_hidden: (0, 0, 0),
        }
        verdicts, ratings, counts = _snapshot(db_path)
        assert verdicts == expected_verdicts
        assert ratings == ratings_before, "rating は書き換えない"
        assert counts == expected_counts
        assert all(good + improve == total for good, improve, total in counts.values())
        # ずれていない業者（op_consistent・op_empty）の行は UPDATE の対象にならない。
        assert _updated_operator_ids(db_path) == sorted([op_posted, op_hidden])

        # downgrade は no-op（是正した値を戻さない）。
        command.downgrade(cfg, "0040_review_verdict")
        assert _snapshot(db_path) == (expected_verdicts, ratings_before, expected_counts)

        # 冪等: 2回目は補完 0 件・補正 0 件で WARNING なし、値も同じ。
        caplog.clear()
        command.upgrade(cfg, "0041_review_verdict_recount")
        assert _logs(caplog, logging.INFO) == [
            "0041: verdict が未設定だった評価を 0 件補完しました（P1〜P2 の間に旧コードが書いた行）。"
            "件数がずれていた業者 0 件の集計を再計算しました（更新 0 件）。"
        ]
        assert _logs(caplog, logging.WARNING) == []
        assert _snapshot(db_path) == (expected_verdicts, ratings_before, expected_counts)
        assert _updated_operator_ids(db_path) == sorted([op_posted, op_hidden]), "2回目は行を更新しない"
    finally:
        get_settings.cache_clear()


def test_0040_then_0041_in_one_upgrade_leaves_0040_results_unchanged(
    tmp_path, monkeypatch, caplog
):
    """0040 → 0041 を1回の upgrade で続けて流す（P1 と P2 を同時にデプロイした場合・空の DB を
    最新まで上げる場合の経路）。0040 が変換・補正した直後の 0041 は補完 0 件・再計算 0 件で、
    0040 の結果を変えない。

    upgrade の目標は head ではなく 0041 を明示する（0042 以降が足されても、本テストが確かめる
    範囲を 0040 → 0041 に保つため）。test_0040 側でこれを行わないのは、P1 単体（head=0040）の
    時点では 0041 のログを期待できず壊れるため。
    """
    db_path = tmp_path / "0040_0041.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    caplog.set_level(logging.INFO, logger="alembic.versions.0040_review_verdict")
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    get_settings.cache_clear()
    try:
        op_rated, op_empty, op_drifted = (uuid.uuid4().hex for _ in range(3))
        # key: (業者, 取引キー, reviewer_type, rating, hidden_at)
        rows = {
            "r_user_5": (op_rated, "a1", "user", 5, None),
            "r_user_3": (op_rated, "a2", "user", 3, None),
            "r_user_4_hidden": (op_rated, "a3", "user", 4, "2026-09-20 00:00:00"),
            "r_op_2": (op_rated, "a1", "operator", 2, None),
            "r_drifted_1": (op_drifted, "d1", "user", 1, None),
        }
        review_ids = {key: uuid.uuid4().hex for key in rows}
        txn_of: dict[str, str] = {}

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0040_SCHEMA_SQL)
            conn.executemany(
                "INSERT INTO operators (id, review_count) VALUES (?, ?)",
                # op_drifted は実件数1件に対して review_count が 5（0040 の U5 が補正する）。
                [(op_rated, 2), (op_empty, 0), (op_drifted, 5)],
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
                "INSERT INTO reviews (id, transaction_id, reviewer_type, rating, hidden_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (review_ids[key], txn_of[txn_key], reviewer_type, rating, hidden_at)
                    for key, (_, txn_key, reviewer_type, rating, hidden_at) in rows.items()
                ],
            )
            conn.commit()
            ratings_before = dict(conn.execute("SELECT id, rating FROM reviews").fetchall())
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0039_sessions_revoked_at")
        command.upgrade(cfg, "0041_review_verdict_recount")

        # 0040 が review_count のずれ（op_drifted）を補正して WARNING を出した後、0041 は何も直さない。
        migration_logs = [
            (r.name, r.levelno) for r in caplog.records if r.name.startswith("alembic.versions.004")
        ]
        assert migration_logs == [
            ("alembic.versions.0040_review_verdict", logging.INFO),
            ("alembic.versions.0040_review_verdict", logging.WARNING),
            (_LOGGER_NAME, logging.INFO),
        ]
        assert _logs(caplog, logging.INFO) == [
            "0041: verdict が未設定だった評価を 0 件補完しました（P1〜P2 の間に旧コードが書いた行）。"
            "件数がずれていた業者 0 件の集計を再計算しました（更新 0 件）。"
        ]

        verdicts, ratings, counts = _snapshot(db_path)
        assert verdicts == {
            review_ids["r_user_5"]: "good",
            review_ids["r_user_3"]: "improve",
            review_ids["r_user_4_hidden"]: "good",
            review_ids["r_op_2"]: "improve",
            review_ids["r_drifted_1"]: "improve",
        }
        assert ratings == ratings_before, "rating は書き換えない"
        # (good_count, improve_count, review_count)。非表示と業者→依頼者は数えない。
        assert counts == {op_rated: (1, 1, 2), op_empty: (0, 0, 0), op_drifted: (0, 1, 1)}
    finally:
        get_settings.cache_clear()


def test_0041_is_the_single_head_chained_from_0040():
    """0041 が単独の head として 0040 に正しく連鎖していること（分岐の防止）。"""
    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0041_review_verdict_recount"]
    rev_0041 = script.get_revision("0041_review_verdict_recount")
    assert rev_0041.down_revision == "0040_review_verdict"
    # 過去の alembic_version VARCHAR(32) 全断障害の再発防止ガード。
    assert len(rev_0041.revision) <= 32
