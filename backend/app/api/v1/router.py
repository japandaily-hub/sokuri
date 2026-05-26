"""API v1 ルーター — /api/v1 以下の全エンドポイントを集約する。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.analyze import router as analyze_router
from app.api.v1.endpoints.estimate import router as estimate_router

api_router = APIRouter()
api_router.include_router(analyze_router, tags=["Analyze"])
api_router.include_router(estimate_router, tags=["Estimate"])
