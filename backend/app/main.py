"""FastAPI アプリケーションエントリーポイント（ハンドオフ §5 規約継承）。

lifespan で DB 接続プールを初期化・クリーンアップし、
Phase 4 から起動時チャネルシードを実行する（冪等）。
エンドポイント実装は :mod:`app.api.v1.router` に委譲する。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.db.session import AsyncSessionLocal, engine
from app.services.seed import seed_channels_and_rules

logger = logging.getLogger(__name__)


async def _run_seed() -> None:
    """バックグラウンドでチャネルシードを実行する。失敗してもサーバーは継続する。"""
    try:
        logger.info("seed: チャネルシードを開始")
        async with AsyncSessionLocal() as session:
            await seed_channels_and_rules(session)
        logger.info("seed: チャネルシード完了")
    except Exception as exc:
        logger.error("seed: チャネルシード失敗（サービスは継続） - %s", exc, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """起動時: DB エンジンを app.state に格納し、シードをバックグラウンドで起動。
    終了時: プールをクローズ。

    seed はバックグラウンドタスクで実行するため、DB 未起動などでシードに失敗しても
    サーバー自体は起動する（ヘルスチェックが通る）。
    """
    app.state.db_engine = engine

    # Phase 4: バックグラウンドでチャネル・ルールを投入（冪等）
    asyncio.create_task(_run_seed())

    yield

    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="カタヅケ API",
        description=(
            "全カテゴリ横断リユース・アグリゲーター — 写真から売却チャネルを AI で自動推奨する。\n\n"
            "## フロー\n"
            "1. **Identify**: `POST /api/v1/analyze` — 写真を投稿して製品を特定\n"
            "2. **Evaluate**: `POST /api/v1/estimate` — コンディションを確定して見積もり取得\n"
            "3. **Verify**: `POST /api/v1/assessments/{id}/defects` — 瑕疵写真を添付（必要時）\n"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO(Phase 6): 本番では許可オリジンを絞ること
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["System"], summary="ヘルスチェック")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
