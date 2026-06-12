"""API v1 ルーター — /api/v1 以下の全エンドポイントを集約する。"""

from __future__ import annotations

from fastapi import APIRouter

# NOTE: albums_router は Phase 2 機能（一括査定アルバム永続化）。
# 現在は ENUM/テーブル状態の不整合により Railway デプロイで healthcheck failure を
# 起こしているため一時的に未登録。AI 解析 (Gemini 2.5 Flash) の本番反映を優先する。
# Phase 2 復旧時は: alembic 0003 を再有効化 + 下の import/include をアンコメント。
# from app.api.v1.endpoints.albums import router as albums_router
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.analyze import router as analyze_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.bids import router as bids_router
from app.api.v1.endpoints.case_photos import router as case_photos_router
from app.api.v1.endpoints.cases import router as cases_router
from app.api.v1.endpoints.estimate import router as estimate_router
from app.api.v1.endpoints.reductions import router as reductions_router
from app.api.v1.endpoints.reviews import router as reviews_router
from app.api.v1.endpoints.transactions import router as transactions_router

api_router = APIRouter()
# ── ソクウリ既存 ──────────────────────────────────────────────────
api_router.include_router(analyze_router, tags=["Analyze"])
api_router.include_router(estimate_router, tags=["Estimate"])
# api_router.include_router(albums_router, tags=["Albums"])
# ── カタヅケ（クローズドβ） ──────────────────────────────────────
api_router.include_router(auth_router, tags=["Auth"])
api_router.include_router(case_photos_router, tags=["Photos"])
api_router.include_router(cases_router, tags=["Cases"])
api_router.include_router(bids_router, tags=["Bids"])
api_router.include_router(transactions_router, tags=["Transactions"])
api_router.include_router(reductions_router, tags=["Reductions"])
api_router.include_router(reviews_router, tags=["Reviews"])
api_router.include_router(admin_router, tags=["Admin"])
