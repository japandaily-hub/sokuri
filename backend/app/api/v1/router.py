"""API v1 ルーター — /api/v1 以下の全エンドポイントを集約する。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.request_char_guard import reject_unsafe_request_chars

# NOTE: albums_router は Phase 2 機能（一括査定アルバム永続化）。
# 現在は ENUM/テーブル状態の不整合により Railway デプロイで healthcheck failure を
# 起こしているため一時的に未登録。AI 解析 (Gemini 2.5 Flash) の本番反映を優先する。
# Phase 2 復旧時は: alembic 0003 を再有効化 + 下の import/include をアンコメント。
# from app.api.v1.endpoints.albums import router as albums_router
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.analyze import router as analyze_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.bids import router as bids_router
from app.api.v1.endpoints.case_items import router as case_items_router
from app.api.v1.endpoints.case_photos import router as case_photos_router
from app.api.v1.endpoints.cases import router as cases_router
from app.api.v1.endpoints.contact import router as contact_router
from app.api.v1.endpoints.operator_applications import router as operator_applications_router
from app.api.v1.endpoints.operator_license import router as operator_license_router
from app.api.v1.endpoints.operator_profile import router as operator_profile_router
from app.api.v1.endpoints.reductions import router as reductions_router
from app.api.v1.endpoints.reviews import router as reviews_router
from app.api.v1.endpoints.transactions import router as transactions_router
from app.api.v1.endpoints.user_identity import router as user_identity_router
from app.api.v1.endpoints.users import router as users_router

# dependencies はコンストラクタで指定する（後から api_router.dependencies.append(...)
# しても、既に include_router 済みのルートは self.dependencies を呼び出し時点で
# コピーしているため効かない。app/api/request_char_guard.py のモジュール docstring
# に fastapi/routing.py を実読して確認した根拠を記載）。NUL・孤立サロゲート
# （保存できない文字）を全ルート共通で 422 拒否する最外周の防御。
api_router = APIRouter(dependencies=[Depends(reject_unsafe_request_chars)])
# ── カタヅケ既存 ──────────────────────────────────────────────────
api_router.include_router(analyze_router, tags=["Analyze"])
# NOTE: 旧 AssetWise の査定 API（/estimate・/assessments/*）は 2026-09-27 に撤去した。
# 認証・回数制限の無い書き込み口で、web からの呼び出し元も本番の利用も無かったため。
# DB テーブルは残置。
# api_router.include_router(albums_router, tags=["Albums"])
# ── カタヅケ（クローズドβ） ──────────────────────────────────────
api_router.include_router(auth_router, tags=["Auth"])
api_router.include_router(contact_router, tags=["Contact"])
api_router.include_router(operator_applications_router, tags=["OperatorApplications"])
api_router.include_router(case_photos_router, tags=["Photos"])
api_router.include_router(cases_router, tags=["Cases"])
api_router.include_router(case_items_router, tags=["CaseItems"])
api_router.include_router(bids_router, tags=["Bids"])
api_router.include_router(transactions_router, tags=["Transactions"])
api_router.include_router(users_router, tags=["account"])
api_router.include_router(user_identity_router, tags=["UserIdentity"])
api_router.include_router(operator_profile_router, tags=["OperatorProfile"])
api_router.include_router(operator_license_router, tags=["OperatorLicenseImage"])
api_router.include_router(reductions_router, tags=["Reductions"])
api_router.include_router(reviews_router, tags=["Reviews"])
api_router.include_router(admin_router, tags=["Admin"])
