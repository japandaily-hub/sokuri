"""非同期 DB エンジンとセッションファクトリ。

FastAPI の依存性注入に :func:`get_session` を用いる。バックエンドは asyncpg で
PostgreSQL に非同期接続する（ハンドオフ §4 / vision.py が google-genai の非同期
クライアントを使うため全体を async で統一する）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.sql_echo,
    pool_pre_ping=True,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """リクエストスコープの :class:`AsyncSession` を払い出す依存性プロバイダ。

    Yields:
        トランザクション境界はハンドラ側で明示的に commit すること。
        例外発生時はコンテキストマネージャが自動でロールバックする。
    """
    async with AsyncSessionLocal() as session:
        yield session
