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
from app.config import Settings, get_settings
from app.db.session import AsyncSessionLocal, engine
from app.services.seed import seed_channels_and_rules

logger = logging.getLogger(__name__)

# 本番起動ガードで拒否する既知の弱い JWT_SECRET（デフォルト値・ドキュメント例示値）。
# これらのまま本番運用されると署名検証が事実上無効化される（fail-open）ため起動を止める。
_WEAK_JWT_SECRETS = {"dev-secret-change-me", "change-me-to-random-64-hex"}


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


def create_app(settings: Settings | None = None) -> FastAPI:
    """FastAPI アプリケーションを構築する。

    ``settings`` を明示的に注入できる（未指定時は ``get_settings()`` の
    シングルトンを使用）。これによりテストから起動ガードや CORS 設定を
    実プロセスの環境変数に依存せず直接検証できる。
    """
    settings = settings or get_settings()

    if settings.app_env == "production":
        if settings.jwt_secret in _WEAK_JWT_SECRETS or len(settings.jwt_secret) < 32:
            logger.critical(
                "起動中断: 本番環境（APP_ENV=production）で JWT_SECRET が"
                "既知の弱い値、または32文字未満のまま起動しようとしました。"
            )
            raise RuntimeError(
                "本番環境（APP_ENV=production）で JWT_SECRET が未設定（デフォルト値/例示値）"
                "または短すぎる（32文字未満）まま起動しようとしました。"
                "Render の環境変数で十分な長さのランダムな JWT_SECRET を設定してください。"
            )
        origin_tokens = [t.strip() for t in settings.allowed_origins_raw.split(",")]
        if any("*" in t for t in origin_tokens):
            logger.critical(
                "起動中断: 本番環境（APP_ENV=production）で ALLOWED_ORIGINS に"
                "\"*\"（全オリジン許可、またはワイルドカードサブドメイン）が"
                "含まれたまま起動しようとしました。"
            )
            raise RuntimeError(
                "本番環境（APP_ENV=production）で ALLOWED_ORIGINS に \"*\" を含むトークン"
                "（例: \"https://*.evil.com\"）が含まれています。"
                "許可するオリジンを明示的にカンマ区切りで指定してください。"
            )
    elif settings.jwt_secret in _WEAK_JWT_SECRETS or len(settings.jwt_secret) < 32:
        logger.warning(
            "JWT_SECRET が弱い値（デフォルト値/例示値、または32文字未満）です。"
            "開発環境のため起動は継続しますが、本番相当の検証時は必ず強い鍵を設定してください。"
        )

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
        allow_origins=settings.allowed_origins,
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
