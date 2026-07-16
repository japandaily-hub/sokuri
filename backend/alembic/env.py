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
from sqlalchemy import text as sa_text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.base import Base
import app.db.models  # noqa: F401  -- 全モデルを Base.metadata に登録するため

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DB URL を app 設定から注入。
# ConfigParser は "%" を補間構文として解釈するため "%%" にエスケープする
# （パスワード等に "%" が含まれると InterpolationSyntaxError で即死するのを防ぐ。
#   get_main_option() で読み戻す際に補間で "%" に復元される）。
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

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
    """同期コネクション上でマイグレーションを実行する内部関数。

    transaction_per_migration=True でリビジョン毎にコミットする。
    デフォルト（False）は upgrade 全体が単一トランザクションのため、
    チェーン後半の1箇所の失敗で 0001 から全てロールバックされ
    「テーブルが1つも無い空DB」が残る（2026-07 全断障害の増幅要因）。
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """オンラインモード。async エンジンで接続しマイグレーションを適用する。

    タイムアウトを明示し「DB 無応答 → alembic 無限ハング → uvicorn 永遠に未起動」を
    構造的に不可能にする（接続確立 10 秒 / 各 SQL 120 秒 / ロック待ち 10 秒）。
    asyncpg 以外のドライバ（テスト用 SQLite 等）には固有パラメータを渡さない。
    """
    url = config.get_main_option("sqlalchemy.url") or ""
    connect_args: dict = {}
    if url.startswith("postgresql+asyncpg"):
        connect_args = {
            "timeout": 10,
            "command_timeout": 120,
            "server_settings": {"lock_timeout": "10s", "statement_timeout": "120s"},
        }
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        # alembic_version.version_num はデフォルト VARCHAR(32) だが、本チェーンには
        # 32文字超のリビジョンID（0008=46字/0009=44字/0010=37字）があり、マイグレー
        # ション本体が成功しても自身のバージョン記録(UPDATE)が
        # StringDataRightTruncationError で失敗→全ロールバックする（2026-07 全断障害の
        # 真因）。先に冪等で広げる。IF EXISTS によりテーブル未作成（初回）は no-op で、
        # 初回は alembic が 32 字で作成→0008 で一度失敗→start.sh のリトライ再実行時に
        # ここで広がって自己回復する。
        if url.startswith("postgresql"):
            await connection.execute(
                sa_text(
                    "ALTER TABLE IF EXISTS alembic_version "
                    "ALTER COLUMN version_num TYPE VARCHAR(255)"
                )
            )
            await connection.commit()
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
