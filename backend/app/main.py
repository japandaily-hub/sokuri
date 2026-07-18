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
from fastapi.responses import JSONResponse
from sqlalchemy import text

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
        if "@localhost" in settings.database_url or "@127.0.0.1" in settings.database_url:
            # 起動は継続する（全断より degraded + 可観測性を優先）が、原因をログで即特定
            # できるようにする。DATABASE_URL 未注入時は config.py のデフォルト
            # (localhost) にフォールバックするため、本番でこれが出たら env 注入漏れ確定。
            logger.critical(
                "本番環境（APP_ENV=production）で DATABASE_URL が localhost を指しています。"
                "Render の fromDatabase 注入が効いていない（DB 削除・リンク切れ・env 未設定）"
                "可能性が高く、DB 依存 API は全て失敗します。/readyz で到達性を確認してください。"
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

    @app.get("/readyz", tags=["System"], summary="レディネスチェック（DB到達性+スキーマ状態込み）")
    async def readyz(token: str | None = None) -> JSONResponse:
        """liveness(/health) と分離した readiness プローブ。

        DB へ実際に ``SELECT 1`` を投げて到達性を検証する（5 秒上限）。
        さらに alembic_version の現在リビジョンと主要テーブルの有無を返し、
        「接続はできるがマイグレーション未完了（空/部分スキーマ）」を
        外形監視だけで特定できるようにする（Render のログを見られない
        環境からの診断用。2026-07 全断障害で接続OK・スキーマ不在の切り分けに
        /readyz が無力だった反省から拡張）。
        """
        try:
            async with asyncio.timeout(5):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 -- 到達性判定のため例外種別は問わない
            logger.error("readyz: DB 到達性チェック失敗 - %s", exc)
            return JSONResponse(
                {"status": "degraded", "db": "unreachable"}, status_code=503
            )

        # スキーマ状態（診断情報）。取得失敗は unknown として本体判定を阻害しない。
        alembic_rev: str | None = None
        tables: dict[str, bool] = {}
        try:
            async with asyncio.timeout(5):
                async with engine.connect() as conn:

                    def _inspect(sync_conn) -> tuple[str | None, dict[str, bool]]:  # noqa: ANN001
                        from sqlalchemy import inspect as sa_inspect

                        insp = sa_inspect(sync_conn)
                        present = {
                            name: insp.has_table(name)
                            for name in (
                                "users",
                                "operators",
                                "cases",
                                "transactions",
                                # 0008〜0009 の生成物。バージョン停滞時に「どこまで
                                # 物理的に作られているか」を外形から判別するため追加。
                                "operator_applications",
                                "messages",
                                "operator_profiles",
                            )
                        }
                        rev = None
                        if insp.has_table("alembic_version"):
                            rev = sync_conn.execute(
                                text("SELECT version_num FROM alembic_version")
                            ).scalar()
                        return rev, present

                    alembic_rev, tables = await conn.run_sync(_inspect)
        except Exception as exc:  # noqa: BLE001 -- 診断情報の欠落は readiness を壊さない
            logger.error("readyz: スキーマ状態の取得失敗 - %s", exc)

        # 期待ヘッドは alembic のスクリプトディレクトリから実行時に解決する
        # （ハードコードだと新規マイグレーション追加時に必ず腐る）。読めない環境
        # （テスト・ローカル等）では None → テーブル有無ベースの判定へフォールバック。
        head_rev: str | None = None
        try:
            from alembic.config import Config as _AlembicConfig
            from alembic.script import ScriptDirectory as _ScriptDirectory

            head_rev = _ScriptDirectory.from_config(
                _AlembicConfig("alembic.ini")
            ).get_current_head()
        except Exception:  # noqa: BLE001 -- 診断補助のため失敗は無視
            head_rev = None

        if head_rev is not None:
            schema_ok = alembic_rev == head_rev
        else:
            schema_ok = bool(tables) and all(tables.values())

        payload: dict[str, object] = {
            "status": "ready" if schema_ok else "degraded",
            "db": "ok",
            "schema": {
                "alembic_version": alembic_rev,
                "expected_head": head_rev,
                "tables": tables,
            },
        }

        # スキーマ未達時のみ、start.sh が保存した直近の alembic 出力末尾を添付する
        # （Render ログを読めない環境からの根本原因特定用）。接続文字列はリダクト。
        # DIAG_TOKEN 設定時は ?token= の一致が必須（定数時間比較）。未設定時は
        # β運用としてスキーマ未達の間のみ公開（インシデント時に認証系が死んで
        # いても診断できることを優先する設計判断）。
        import hmac as _hmac

        diag_allowed = not settings.diag_token or (
            token is not None and _hmac.compare_digest(token, settings.diag_token)
        )
        if not schema_ok and diag_allowed:
            try:
                import re
                from pathlib import Path

                log_path = Path("/tmp/alembic-last.log")
                if log_path.exists():
                    tail_lines = log_path.read_text(errors="replace").splitlines()[-30:]
                    redacted = [
                        re.sub(r"postgres(?:ql)?(?:\+\w+)?://\S+", "[REDACTED_URL]", ln)
                        for ln in tail_lines
                    ]
                    payload["migration_log_tail"] = redacted
            except Exception:  # noqa: BLE001 -- 診断補助のため失敗は無視
                pass

        return JSONResponse(payload, status_code=200 if schema_ok else 503)

    return app


app = create_app()
