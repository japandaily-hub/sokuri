"""Alembic 実行環境。

オンライン（DB 接続）/ オフライン（``--sql``）の双方に対応する。DB URL は
:func:`app.config.get_settings` から取得し、全 ORM モデルを import して
``Base.metadata`` を完全な状態にした上で autogenerate の対象とする。
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.base import Base
import app.db.models  # noqa: F401  -- 全モデルを Base.metadata に登録するため

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DB URL を app 設定から注入。
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """オフライン（``--sql``）モード。DB に接続せず SQL を生成する。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """同期コネクション上でマイグレーションを実行する内部関数。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """オンラインモード。async エンジンで接続しマイグレーションを適用する。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
