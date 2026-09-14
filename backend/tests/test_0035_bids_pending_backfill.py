"""0035_bids_pending_reminder: 既存行を「送信済み」で埋め戻すことの回帰テスト。

test_0033_reminder_backfill.py と同じ理由（r12-review H-1 と同型の問題）:
列を NULL のまま追加すると、適用直後の1周目で「サービス開始以来、入札未決定の
まま2日超放置されている bidding 案件すべて」が一斉にリマインド対象になり、
過去分の催促が大量に飛ぶ。0035 の upgrade はその該当行を適用時刻でマークして
これを塞ぐ。

**将来の対象行（届いたばかりの入札・全入札取り下げ済み・未 bidding・既に
決定済み）は NULL のまま**残ることも併せて検証する（埋め戻しが効きすぎて
以後のリマインドが死ぬ回帰を防ぐ）。

テストの作法は tests/test_0033_reminder_backfill.py と同一
（alembic の env.py が内部で ``asyncio.run()`` を呼ぶため ``async def`` にはできない）。
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

#: reminders.py の BIDS_PENDING_GRACE_DAYS と一致させる。
_BIDS_PENDING_GRACE_DAYS = 2

# 0035 の upgrade() が読み書きするカラムだけを、0034 適用済み相当の
# （まだ bids_pending_reminded_at が無い）スキーマで作成する。
_PRE_0035_SCHEMA_SQL = """
CREATE TABLE cases (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bids (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    operator_id TEXT,
    amount INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE operators (
    id TEXT PRIMARY KEY,
    is_suspended INTEGER NOT NULL DEFAULT 0,
    vendor_status TEXT NOT NULL DEFAULT 'active',
    deleted_at TIMESTAMP
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


def test_upgrade_marks_existing_rows_as_already_reminded(tmp_path, monkeypatch):
    """適用時点の該当行だけが送信済みとして埋まり、将来の対象行は NULL のまま残る。"""
    db_path = tmp_path / "0035_backfill.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0035_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0034_bid_amount_history")

        now = datetime.now(timezone.utc)
        stale_case_id = str(uuid.uuid4())
        fresh_case_id = str(uuid.uuid4())
        withdrawn_only_case_id = str(uuid.uuid4())
        no_bid_case_id = str(uuid.uuid4())
        closed_case_id = str(uuid.uuid4())
        suspended_only_case_id = str(uuid.uuid4())

        def _iso(dt: datetime) -> str:
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        active_operator_id = str(uuid.uuid4())
        suspended_operator_id = str(uuid.uuid4())

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executemany(
                "INSERT INTO operators (id, is_suspended, vendor_status, deleted_at) VALUES (?, ?, ?, ?)",
                [
                    (active_operator_id, 0, "active", None),
                    # 停止中業者（依頼者は実際にはこの入札を選べない。security review Medium-1 対応）
                    (suspended_operator_id, 1, "active", None),
                ],
            )
            conn.executemany(
                "INSERT INTO cases (id, user_id, status) VALUES (?, ?, ?)",
                [
                    (stale_case_id, str(uuid.uuid4()), "bidding"),
                    (fresh_case_id, str(uuid.uuid4()), "bidding"),
                    (withdrawn_only_case_id, str(uuid.uuid4()), "bidding"),
                    (no_bid_case_id, str(uuid.uuid4()), "open"),
                    (closed_case_id, str(uuid.uuid4()), "closed"),
                    (suspended_only_case_id, str(uuid.uuid4()), "bidding"),
                ],
            )
            conn.executemany(
                "INSERT INTO bids (id, case_id, operator_id, status, created_at) VALUES (?, ?, ?, ?, ?)",
                [
                    # 埋め戻し対象: bidding かつ最古の pending 入札が2日超前
                    (
                        str(uuid.uuid4()),
                        stale_case_id,
                        active_operator_id,
                        "pending",
                        _iso(now - timedelta(days=_BIDS_PENDING_GRACE_DAYS + 1)),
                    ),
                    # 対象外: 入札が届いてからまだ2日経っていない（今後リマインドされうる）
                    (
                        str(uuid.uuid4()),
                        fresh_case_id,
                        active_operator_id,
                        "pending",
                        _iso(now - timedelta(hours=1)),
                    ),
                    # 対象外: 唯一の入札が取り下げ済み（決めるべき入札が残っていない）
                    (
                        str(uuid.uuid4()),
                        withdrawn_only_case_id,
                        active_operator_id,
                        "withdrawn",
                        _iso(now - timedelta(days=10)),
                    ),
                    # 対象外: 既に決定済み（closed の案件に付いた選定済み入札）
                    (
                        str(uuid.uuid4()),
                        closed_case_id,
                        active_operator_id,
                        "selected",
                        _iso(now - timedelta(days=10)),
                    ),
                    # 対象外: 唯一の pending 入札が停止中業者のもの（選択不可）
                    (
                        str(uuid.uuid4()),
                        suspended_only_case_id,
                        suspended_operator_id,
                        "pending",
                        _iso(now - timedelta(days=10)),
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        command.upgrade(cfg, "0035_bids_pending_reminder")

        conn = sqlite3.connect(str(db_path))
        try:
            marks = dict(
                conn.execute(
                    "SELECT id, bids_pending_reminded_at FROM cases"
                ).fetchall()
            )
            assert marks[stale_case_id] is not None, "入札未決定の既存行が埋め戻されていない"
            assert marks[fresh_case_id] is None, "届いたばかりの入札まで送信済みにしてはいけない"
            assert marks[withdrawn_only_case_id] is None, "決めるべき入札が無い案件を対象にしてはいけない"
            assert marks[no_bid_case_id] is None, "入札ゼロの案件（no_bid リマインドの対象）を巻き込んではいけない"
            assert marks[closed_case_id] is None, "既に決定済みの案件を対象にしてはいけない"
            assert marks[suspended_only_case_id] is None, "選択できない入札しか無い案件を対象にしてはいけない"

            index_names = {
                row[1] for row in conn.execute("PRAGMA index_list('cases')").fetchall()
            }
            assert "ix_cases_bids_pending_reminder" in index_names
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()
