"""0033_reminder_marks: 既存行を「送信済み」で埋め戻すことの回帰テスト（r12-review H-1）。

列を NULL のまま追加すると、適用直後の1周目で「サービス開始以来の該当行すべて」
（訪問日を過ぎた成約・3日以上入札ゼロの open 案件）が一斉にリマインド対象になり、
過去分の催促が大量に飛ぶ。0033 の upgrade は該当行を適用時刻でマークしてこれを塞ぐ。

**将来の対象行（未来の訪問日・入札済み案件・作成直後の案件）は NULL のまま**残る
ことも併せて検証する（埋め戻しが効きすぎて以後のリマインドが死ぬ回帰を防ぐ）。

テストの作法（同期テスト・Config の組み立て方・PRE スキーマを直接作る理由）は
tests/test_0028_migration_dedup.py と同一。alembic の env.py が内部で
``asyncio.run()`` を呼ぶため ``async def`` にはできない。
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

#: reminders.py と同じ JST（visit_date は日本の暦で入力された日付）。
_JST = timezone(timedelta(hours=9), name="Asia/Tokyo")

# 0033 の upgrade() が読み書きするカラムだけを、0032 適用済み相当の
# （まだ overdue_reminded_at / no_bid_reminded_at が無い）スキーマで作成する。
_PRE_0033_SCHEMA_SQL = """
CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    case_id TEXT,
    bid_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    visit_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE cases (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    db_path = tmp_path / "0033_backfill.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0033_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0032_contact_messages")

        now = datetime.now(timezone.utc)
        today_jst = now.astimezone(_JST).date()
        overdue_id = str(uuid.uuid4())
        future_id = str(uuid.uuid4())
        no_visit_id = str(uuid.uuid4())
        stale_case_id = str(uuid.uuid4())
        fresh_case_id = str(uuid.uuid4())
        closed_case_id = str(uuid.uuid4())

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executemany(
                "INSERT INTO transactions (id, status, visit_date) VALUES (?, ?, ?)",
                [
                    # 埋め戻し対象: 訪問日が過去（この版が無ければ1周目に一斉送信された）
                    (overdue_id, "visiting", (today_jst - timedelta(days=3)).isoformat()),
                    # 対象外: 訪問日が未来（今後リマインドされうる＝NULL のまま）
                    (future_id, "visiting", (today_jst + timedelta(days=3)).isoformat()),
                    # 対象外: 訪問日未設定
                    (no_visit_id, "pending", None),
                ],
            )
            conn.executemany(
                "INSERT INTO cases (id, user_id, status, created_at) VALUES (?, ?, ?, ?)",
                [
                    # 埋め戻し対象: open かつ作成から3日超
                    (
                        stale_case_id,
                        str(uuid.uuid4()),
                        "open",
                        (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                    # 対象外: まだ3日経っていない（今後リマインドされうる）
                    (
                        fresh_case_id,
                        str(uuid.uuid4()),
                        "open",
                        (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                    # 対象外: open ではない
                    (
                        closed_case_id,
                        str(uuid.uuid4()),
                        "closed",
                        (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        command.upgrade(cfg, "0033_reminder_marks")

        conn = sqlite3.connect(str(db_path))
        try:
            marks = dict(
                conn.execute(
                    "SELECT id, overdue_reminded_at FROM transactions"
                ).fetchall()
            )
            assert marks[overdue_id] is not None, "訪問日超過の既存行が埋め戻されていない"
            assert marks[future_id] is None, "未来の訪問日まで送信済みにしてはいけない"
            assert marks[no_visit_id] is None

            marks = dict(
                conn.execute("SELECT id, no_bid_reminded_at FROM cases").fetchall()
            )
            assert marks[stale_case_id] is not None, "入札ゼロ放置の既存行が埋め戻されていない"
            assert marks[fresh_case_id] is None, "作成直後の案件まで送信済みにしてはいけない"
            assert marks[closed_case_id] is None

            index_names = {
                row[1]
                for row in conn.execute("PRAGMA index_list('transactions')").fetchall()
            }
            assert "ix_transactions_overdue_reminder" in index_names
            index_names = {
                row[1] for row in conn.execute("PRAGMA index_list('cases')").fetchall()
            }
            assert "ix_cases_no_bid_reminder" in index_names
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()
