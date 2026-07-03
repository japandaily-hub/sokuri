"""ローカルE2E検証用バックエンド起動スクリプト（Docker/PostgreSQL 不要）。

tests/conftest.py と同じ方式で SQLite（ファイル永続）上にスキーマを構築し、
実 uvicorn で app.main:app を起動する。フロント（localhost:3100 等）からの
結合検証（実クリックE2E）を、本番DBに触れず使い捨てDBで行うための開発ツール。

使い方:
    cd C:\\sokuri\\backend
    .venv\\Scripts\\python.exe run_local_e2e.py    # http://127.0.0.1:8000

DBファイル e2e_local.db は使い捨て。作り直す場合は削除して再実行する。
"""
from __future__ import annotations

import os
import pathlib

# ── 環境変数は app モジュール import 前に確定させる（get_settings は lru_cache）──
_HERE = pathlib.Path(__file__).resolve().parent
# DATABASE_URL は setdefault にしないこと: 本番/開発の実DB URLが環境に残っていても
# 必ず使い捨てSQLiteへ上書きし、本スクリプト経由での実DB到達を構造的に防ぐ。
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_HERE / 'e2e_local.db').as_posix()}"
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("ADMIN_EMAILS", "e2e-admin@example.com")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3100")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3100,http://localhost:3000")
if not os.environ.get("APP_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet

    os.environ["APP_ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")

# ── JSONB は PostgreSQL 固有のため SQLite では JSON として DDL 生成する ──
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


# ── 全モデルを import してからテーブルを作成（conftest.py と同一の集合）──
import asyncio

from app.db.base import Base
import app.db.models.channel  # noqa: F401
import app.db.models.item  # noqa: F401
import app.db.models.routing  # noqa: F401
import app.db.models.assessment  # noqa: F401
import app.db.models.defect  # noqa: F401
import app.db.models.case  # noqa: F401
import app.db.models.operator  # noqa: F401
import app.db.models.operator_application  # noqa: F401
import app.db.models.operator_profile  # noqa: F401
import app.db.models.bid  # noqa: F401
import app.db.models.message  # noqa: F401
import app.db.models.transaction  # noqa: F401
import app.db.models.user  # noqa: F401
import app.db.models.invite  # noqa: F401
from sqlalchemy.orm import configure_mappers

configure_mappers()


async def _init_schema() -> None:
    """使い捨てエンジンで create_all（uvicorn 本体のループと分離するため独立生成）。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_init_schema())

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
