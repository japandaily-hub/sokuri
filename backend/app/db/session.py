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

# asyncpg のデフォルトは command_timeout=None（接続後のクエリが無期限ブロック）のため、
# half-dead な DB で API リクエストが永遠にハングしないよう有限のタイムアウトを明示する。
# asyncpg 以外のドライバ（テスト用 SQLite 等）には固有パラメータを渡さない。
_connect_args: dict = {}
# プール設定は QueuePool（＝実 DB 接続を持つドライバ）にのみ渡す。SQLite/aiosqlite の
# テスト用エンジンは NullPool / StaticPool になり pool_size 等を受け付けないため、
# PostgreSQL 経路に限定する。
_pool_kwargs: dict = {}
if _settings.database_url.startswith("postgresql+asyncpg"):
    _connect_args = {"timeout": 10, "command_timeout": 30}
    # 既定値依存をやめ、Render 無料 PostgreSQL の接続上限に収まる明示値に固定する
    # （r6 ADD-1）。pool_timeout は 30 秒（r7 H-1 で 10 秒から復帰）: 長時間占有の
    # 根本原因（AI 解析中の接続保持）を cases.py 側で除去したため、瞬間的なバースト
    # は待って吸収する。上限は config で上書きできる。
    _pool_kwargs = {
        "pool_size": _settings.db_pool_size,
        "max_overflow": _settings.db_max_overflow,
        "pool_timeout": _settings.db_pool_timeout,
    }

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.sql_echo,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args=_connect_args,
    **_pool_kwargs,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


def get_background_session_factory() -> async_sessionmaker[AsyncSession]:
    """BackgroundTasks 用に「新しいセッション」を開くためのファクトリを返す。

    リクエストスコープの :class:`AsyncSession`（``get_session``）はレスポンス送出時に
    クローズされるため、レスポンス後に走る BackgroundTasks から使い回してはならない。
    また、長時間処理（AI 解析）をリクエストスコープのセッションで行うとコネクションを
    掴んだままになる（r6 ADD-1）。

    ``AsyncSessionLocal`` をモジュール属性経由で毎回解決するのは、テストが
    ``app.db.session.AsyncSessionLocal`` を差し替えるだけでバックグラウンド処理を
    テスト用エンジンへ向けられるようにするため（import 時に束縛しない）。
    """
    return AsyncSessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """リクエストスコープの :class:`AsyncSession` を払い出す依存性プロバイダ。

    Yields:
        トランザクション境界はハンドラ側で明示的に commit すること。
        例外発生時はコンテキストマネージャが自動でロールバックする。
    """
    async with AsyncSessionLocal() as session:
        yield session
