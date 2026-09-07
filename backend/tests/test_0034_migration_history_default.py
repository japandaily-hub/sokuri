"""0034_bid_amount_history: changed_at の NOT NULL 制約に対する server_default の回帰テスト。

security review Critical指摘: 旧版の 0034 は ``bid_amount_history.changed_at`` を
``nullable=False`` にしていながら migration の DDL に ``server_default`` を与えて
いなかった（ORM 側 ``BidAmountHistory.changed_at`` にのみ ``server_default=func.now()``
を書いていたが、これは alembic 経由で作られた本番テーブルの実DDLには反映されない
メタデータに過ぎない）。この状態で ``changed_at`` を明示せずに INSERT すると、
alembic 適用済みテーブルでは NotNullViolation になる。

既存の pytest（test_bid_raise.py 等）は ``Base.metadata.create_all``（ORM メタデータ
からテーブルを直接生成する経路）で通っていたため、ORM 側の server_default が
そのままテーブルDDLに反映され、この不整合を検出できなかった。本テストは
alembic の migration 本文（DDL）を直接 SQLite に当てて検証する
（tests/test_0028_migration_dedup.py と同型のアプローチ）。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

# 0033 適用済み相当のスキーマ（0034 の upgrade() が add_column するのに必要な
# 最小限の bids テーブルのみ）。0001〜0033 の完全なチェーン実行はしない
# （test_0028_migration_dedup.py と同じ理由: 過去の migration に PostgreSQL
# 専用の raw DDL があり SQLite では構文エラーになるため）。
_PRE_0034_SCHEMA_SQL = """
CREATE TABLE bids (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _alembic_config() -> Config:
    # ini の日本語コメントが cp932 環境で UnicodeDecodeError になる既知の罠を
    # 避けるため、ini ファイルを読ませず必要なオプションだけを設定する
    # （test_0028_migration_dedup.py と同一の理由）。
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("path_separator", "os")
    return cfg


def test_0034_upgrade_and_history_insert_without_changed_at_does_not_violate_not_null(
    tmp_path, monkeypatch
):
    """0034 適用後、changed_at を明示しない INSERT でも NOT NULL 違反にならず埋まる。"""
    db_path = tmp_path / "0034_history_default.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0034_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0033_reminder_marks")

        # 0034 を適用する。旧版はここまでは通る（NOT NULL違反が起きるのは
        # 「テーブル定義」ではなく「アプリ層からのINSERT時」）。
        command.upgrade(cfg, "0034_bid_amount_history")

        conn = sqlite3.connect(str(db_path))
        try:
            # revision_count 列と bid_amount_history テーブルが作られていること。
            columns = {row[1] for row in conn.execute("PRAGMA table_info('bids')")}
            assert "revision_count" in columns

            bid_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO bids (id, case_id, operator_id, amount, status)"
                " VALUES (?, ?, ?, 30000, 'pending')",
                (bid_id, str(uuid.uuid4()), str(uuid.uuid4())),
            )
            conn.commit()

            # security review Critical指摘の核心: changed_at を明示せずに
            # bid_amount_history へ INSERT する（アプリ層の BidAmountHistory(...)
            # 呼び出しが changed_at を渡さないケースを再現）。旧版の migration
            # （server_default 無し）ではここで sqlite3.IntegrityError
            # (NOT NULL constraint failed) になっていた。
            history_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO bid_amount_history"
                " (id, bid_id, old_amount, new_amount, old_message, new_message)"
                " VALUES (?, ?, 30000, 40000, NULL, NULL)",
                (history_id, bid_id),
            )
            conn.commit()

            row = conn.execute(
                "SELECT changed_at FROM bid_amount_history WHERE id = ?", (history_id,)
            ).fetchone()
            assert row is not None
            assert row[0] is not None, "changed_at が NULL のまま挿入されてしまった"
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()
