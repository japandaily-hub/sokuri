"""PG 同時実行チェック用バックエンド起動スクリプト（Docker の PostgreSQL に接続）。

``run_local_e2e.py``（使い捨て SQLite・:8000）の PostgreSQL 版。SQLite では
``SELECT ... FOR UPDATE`` が no-op のため行ロックを実証できない。本スクリプトは
Docker で立てた実 PG（既に ``alembic upgrade head`` 済みであること）に接続し、
``scripts/pg_concurrency_check.py`` が叩く API を :8001 で起動する。

前提・手順の正本は ``docs/ops/e2e.md``「PG 同時実行チェック」。要点のみ:
    docker run -d --name kdz-pg -e POSTGRES_PASSWORD=kdz -e POSTGRES_DB=kdz \
        -p 55432:5432 postgres:16
    PYTHONUTF8=1 DATABASE_URL=... .venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head
    .venv/Scripts/python.exe scripts/run_pg_e2e.py

``run_local_e2e.py`` と異なりスキーマは ``create_all`` せず**実マイグレーション**に
委ねる（0028 の部分一意索引・0029 の複合一意など、metadata と実 DDL の差分を
そのまま検証対象にするため）。

環境変数:
  KDZ_PG_URL   既定 postgresql+asyncpg://postgres:kdz@127.0.0.1:55432/kdz
  KDZ_PG_PORT  既定 8001
"""

from __future__ import annotations

import os
import pathlib
import sys

# scripts/ から起動されると sys.path[0] が scripts/ になり ``app`` を解決できない。
# 実行ディレクトリに依存せず backend/ を import ルートに固定する。
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ── 環境変数は app モジュール import 前に確定させる（get_settings は lru_cache）──
# DATABASE_URL は setdefault にしない: 本番/開発の実 DB URL が環境に残っていても
# 必ずローカル Docker の使い捨て PG へ上書きし、実 DB 到達を構造的に防ぐ
# （run_local_e2e.py と同じ規約）。
os.environ["DATABASE_URL"] = os.environ.get(
    "KDZ_PG_URL", "postgresql+asyncpg://postgres:kdz@127.0.0.1:55432/kdz"
)
os.environ.setdefault("APP_ENV", "development")
# pg_concurrency_check.py の ADMIN_EMAIL と一致させること。
os.environ.setdefault("ADMIN_EMAILS", "pgcheck-admin@example.com")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3100")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3100")
# 同時実行チェックは同一 IP から短時間に多数のリクエストを撃つため、レート制限で
# 429 になると「競合の結果」と区別できなくなる。検証中のみ無効化する。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# 行ロックの待ち合わせで接続を掴む時間が伸びるため、既定（5+5）よりプールを厚くする。
os.environ.setdefault("DB_POOL_SIZE", "10")
os.environ.setdefault("DB_MAX_OVERFLOW", "10")
if not os.environ.get("APP_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet

    os.environ["APP_ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("KDZ_PG_PORT", "8001")),
        log_level="info",
    )
