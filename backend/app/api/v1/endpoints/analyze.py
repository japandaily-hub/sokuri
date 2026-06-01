# -*- coding: utf-8 -*-
"""POST /api/v1/analyze -- AI Vision による製品特定エンドポイント（Phase 3 実装）。

フロー:
1. app.services.vision で画像から製品情報を Structured Outputs 抽出
2. Item を DB に保存（attributes["base_market_price_jpy"] を含む）
3. AnalyzeResponse を返す

セキュリティ: FastAPI + Pydantic によるリクエスト型バリデーションで SQLi / XSS を防止。
"""

from __future__ import annotations

# NOTE: 元実装で openai SDK 由来の OpenAIError を catch していたが、
# 本プロジェクトの vision 層は google-genai のみを使用しており、
# openai パッケージは依存に含まれない（ModuleNotFoundError 防止のため import 削除）。
# Gemini API 通信エラーは google.genai.errors.APIError に切り替える。
from fastapi import APIRouter, Depends, HTTPException, status
from google.genai.errors import APIError as GenAIAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.item import Item
from app.db.session import get_session
from app.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.vision import analyze_image

router = APIRouter()


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_200_OK,
    summary="製品特定（AI Vision）",
    description=(
        "画像から製品のスペック・カテゴリ・コンディション初期値を AI で推定する。\n\n"
        "- `base_image`: base64 エンコード画像 または HTTPS URL\n"
        "- 返却される `item_id` を `/estimate` に渡すこと\n"
        "- `initial_condition` は AI 推定値。ユーザーが `/estimate` で上書き可能。"
    ),
    responses={
        422: {"description": "バリデーションエラー（画像形式不正など）"},
        503: {"description": "AI サービス（Gemini）が利用不可"},
    },
)
async def analyze(
    body: AnalyzeRequest,
    session: AsyncSession = Depends(get_session),
) -> AnalyzeResponse:
    """画像を解析して Item を永続化し、AnalyzeResponse を返す。

    影響範囲: items テーブルへの INSERT のみ。他テーブルは変更しない。
    """
    # 1. AI Vision で製品情報を抽出
    try:
        vision_result = await analyze_image(body.base_image)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except GenAIAPIError as exc:
        # Gemini 側のレート制限・タイムアウト・5xx は 503 にマップ。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI サービスとの通信に失敗しました: {exc}",
        ) from exc

    # 2. Item を DB に保存。
    #    base_market_price_jpy を attributes に埋め込み、/estimate で参照可能にする。
    item = Item(
        category_tier=vision_result.category_tier,
        detected_name=vision_result.detected_name,
        detected_category_label=vision_result.detected_category_label,
        condition=vision_result.initial_condition,
        condition_confidence=vision_result.condition_confidence,
        image_object_key=vision_result.image_object_key,
        attributes={
            **vision_result.attributes,
            "base_market_price_jpy": vision_result.base_market_price_jpy,
        },
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    # 3. AnalyzeResponse を構築して返す。
    #    attributes から base_market_price_jpy を除いて返す（内部フィールド）。
    public_attributes = {
        k: v for k, v in item.attributes.items() if k != "base_market_price_jpy"
    }

    return AnalyzeResponse(
        item_id=item.id,
        detected_name=item.detected_name,
        detected_category_label=item.detected_category_label,
        category_tier=item.category_tier,
        initial_condition=item.condition,
        condition_confidence=item.condition_confidence,
        attributes=public_attributes,
    )
