"""0028_txn_state_integrity: 重複データが在っても upgrade が完走することの回帰テスト。

r6-review H3: 旧版は cancellations.transaction_id / reduction_requests(pending) の
重複が1組でもあると RuntimeError で **適用自体を中断** していた
（alembic env.py の transaction_per_migration=True により 0028 だけロールバック
され、0027 は適用済みのまま uq_cancellations_transaction_id /
uq_reduction_requests_pending の無い状態で本番が起動しうる）。

本テストは 0028 が前提とする「0027 適用済み」相当のスキーマ（cancellations /
reduction_requests / transactions の必要カラムのみ）をファイル DB に直接作成し
（0001〜0027 の完全なチェーン実行はしない。0006 等に PostgreSQL 専用の
raw ``ALTER TABLE ... ALTER COLUMN`` があり SQLite では構文エラーになるため、
実チェーン実行は本番相当の PostgreSQL でのみ意味を持つ。本テストは 0028 の
マイグレーション本文（自動是正ロジック）そのものの検証に閉じる）、重複行を
仕込んだ上で ``command.stamp`` → ``command.upgrade`` により 0028 の upgrade() を
実行し、RuntimeError を出さずに完走すること・重複が是正された上で一意制約/索引が
実在することを検証する（既存の migration テスト方式が無いこの領域では、指示に
従い engine を作って command.upgrade を回す最小構成にした）。

同期テスト（``async def`` にしない）: alembic の env.py は内部で
``asyncio.run()`` を呼ぶため、既に実行中のイベントループ（pytest-asyncio が
async def テストへ張るもの）の中から呼ぶと
``RuntimeError: asyncio.run() cannot be called from a running event loop`` に
なる。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

# 0028 の upgrade() が読み書きする最小限のテーブルのみを、0027 適用済み相当の
# （まだ uq_cancellations_transaction_id / uq_reduction_requests_pending /
# ix_transactions_bid_id が無い）スキーマで作成する。
_PRE_0028_SCHEMA_SQL = """
CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    case_id TEXT,
    bid_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE cancellations (
    id TEXT PRIMARY KEY,
    case_id TEXT,
    transaction_id TEXT,
    cancelled_by TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reduction_requests (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    original_amount INTEGER NOT NULL,
    requested_amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _alembic_config() -> Config:
    # alembic.ini を Config(str(path)) 経由で読ませると、ConfigParser の既定
    # encoding="locale" がこの Windows 環境（cp932）で ini 内の日本語コメントを
    # デコードできず UnicodeDecodeError になる（tests/test_admin_notifications_r6.py
    # が同じ理由で ScriptDirectory.from_config(Config("alembic.ini")) を try/except
    # フォールバックしているのと同一の既知の罠）。ini ファイルを読ませず
    # ``Config()`` を無引数で構築すると file_config は空の ConfigParser のまま
    # （ファイル未読込）になるため、必要なオプションだけをプログラムで設定する。
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option("path_separator", "os")
    # env.py は sqlalchemy.url を app.config.get_settings() から動的に注入するため
    # ここでの set_main_option は無視される（下の monkeypatch 側で環境変数から効かせる）。
    return cfg


def test_upgrade_resolves_duplicates_without_raising(tmp_path, monkeypatch):
    """cancellations / reduction_requests に重複を仕込んでも 0028 の upgrade が通る。"""
    db_path = tmp_path / "0028_dedup.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        # 1) 0027 適用済み相当のスキーマを直接作る。
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(_PRE_0028_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

        cfg = _alembic_config()
        command.stamp(cfg, "0027_case_ai_status")

        # 2) 重複行を直接仕込む（raw sqlite3。ORM/セッションは経由しない＝アプリ層の
        #    多層防御を迂回した「制約だけが最後の砦」の状況を再現する）。created_at は
        #    「最古の1行を残す」順序判定を確定させるため明示的にずらして与える。
        txn_id = str(uuid.uuid4())
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO cancellations"
                " (id, case_id, transaction_id, cancelled_by, reason, created_at)"
                " VALUES (?, NULL, ?, 'user', '1件目（最古）', '2026-01-01 00:00:00')",
                (str(uuid.uuid4()), txn_id),
            )
            conn.execute(
                "INSERT INTO cancellations"
                " (id, case_id, transaction_id, cancelled_by, reason, created_at)"
                " VALUES (?, NULL, ?, 'admin', '2件目（重複・削除される想定）',"
                " '2026-01-01 00:00:01')",
                (str(uuid.uuid4()), txn_id),
            )
            reduction_txn_id = str(uuid.uuid4())
            operator_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO reduction_requests"
                " (id, transaction_id, operator_id, original_amount, requested_amount,"
                "  reason, status, created_at)"
                " VALUES (?, ?, ?, 30000, 20000, '1件目（最古・pending のまま残る想定）',"
                " 'pending', '2026-01-01 00:00:00')",
                (str(uuid.uuid4()), reduction_txn_id, operator_id),
            )
            conn.execute(
                "INSERT INTO reduction_requests"
                " (id, transaction_id, operator_id, original_amount, requested_amount,"
                "  reason, status, created_at)"
                " VALUES (?, ?, ?, 30000, 18000,"
                " '2件目（重複・rejected へ自動却下される想定）', 'pending',"
                " '2026-01-01 00:00:01')",
                (str(uuid.uuid4()), reduction_txn_id, operator_id),
            )
            conn.commit()
        finally:
            conn.close()

        # 3) 0028 を適用する。旧版はここで RuntimeError を送出していた。
        command.upgrade(cfg, "0028_txn_state_integrity")

        # 4) 重複が是正され、制約/索引が実在することを検証する。
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT cancelled_by FROM cancellations WHERE transaction_id = ?",
                (txn_id,),
            ).fetchall()
            assert [r[0] for r in rows] == [
                "user"
            ], "最古の1行だけが残るはず（重複行は削除される）"

            rows = conn.execute(
                "SELECT reason, status FROM reduction_requests"
                " WHERE transaction_id = ? ORDER BY reason",
                (reduction_txn_id,),
            ).fetchall()
            statuses = {reason: status for reason, status in rows}
            assert statuses["1件目（最古・pending のまま残る想定）"] == "pending"
            assert statuses["2件目（重複・rejected へ自動却下される想定）"] == "rejected"

            # cancellations.transaction_id の一意制約は batch_alter_table（SQLite の
            # コピー＆リネーム方式）で張られるため、PRAGMA index_list 上は
            # 明示名ではなく sqlite_autoindex_* として現れる（SQLite が inline の
            # テーブル制約に付けた名前を保持しない仕様。PostgreSQL では実名で現れる）。
            # ここでは実際に一意性が効くことを後段の INSERT 失敗検証で確認する。
            unique_index_count = sum(
                1
                for row in conn.execute("PRAGMA index_list('cancellations')").fetchall()
                if row[2]  # row[2] = unique フラグ
            )
            assert unique_index_count >= 1, "cancellations に一意インデックスが無い"

            index_names = {
                row[1]
                for row in conn.execute(
                    "PRAGMA index_list('reduction_requests')"
                ).fetchall()
            }
            assert "uq_reduction_requests_pending" in index_names

            index_names = {
                row[1]
                for row in conn.execute("PRAGMA index_list('transactions')").fetchall()
            }
            assert "ix_transactions_bid_id" in index_names

            # 一意制約が実際に効いていること（重複はもう作れない）。
            try:
                conn.execute(
                    "INSERT INTO cancellations"
                    " (id, case_id, transaction_id, cancelled_by, reason)"
                    " VALUES (?, NULL, ?, 'admin', '制約検証用の3件目')",
                    (str(uuid.uuid4()), txn_id),
                )
                conn.commit()
                raised = False
            except sqlite3.IntegrityError:
                raised = True
            assert raised, "uq_cancellations_transaction_id が効いていない"
        finally:
            conn.close()
    finally:
        get_settings.cache_clear()
