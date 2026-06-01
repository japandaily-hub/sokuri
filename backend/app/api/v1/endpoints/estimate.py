# -*- coding: utf-8 -*-
"""Phase 3 実装: /estimate（価格算出）+ /assessments/{id}/defects（瑕疵エビデンス）。

フロー（/estimate）:
1. item_id で Item を取得（404 ガード）
2. Item.attributes["base_market_price_jpy"] から基準相場を取得
3. CONDITION_CONFIG 乗数で全コンディション見積もりを算出
4. Assessment を flush（ID 確定）
5. ルーティングエンジンで AssessmentRecommendation を生成（Phase 4: outbound_url も生成）
6. Assessment を COMPLETED に更新してコミット
7. EstimateResponse を構築して返す

フロー（/defects）:
- Assessment の存在確認（404 ガード）
- DefectEvidence を DB に永続化（Phase 4 実装）
- オブジェクトキーはモック生成（Phase 5 で実ストレージに置換）

セキュリティ: FastAPI + Pydantic によるリクエスト型バリデーションで SQLi / XSS を防止。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.assessment import Assessment, AssessmentRecommendation
from app.db.models.defect import DefectEvidence
from app.db.models.enums import AssessmentStatus, ItemCondition
from app.db.models.item import Item
from app.db.session import get_session
from app.schemas import (
    CONDITION_CONFIG,
    AssessmentGetResponse,
    ConditionDetail,
    DefectUploadRequest,
    DefectUploadResponse,
    EstimateRequest,
    EstimateResponse,
    RecommendationResponse,
)
from app.services.routing import evaluate_routing_rules

router = APIRouter()


@router.post(
    "/estimate",
    response_model=EstimateResponse,
    status_code=status.HTTP_200_OK,
    summary="減価後価格算出 + チャネル推奨",
    description=(
        "ユーザーが確定したコンディションを受け取り、乗数を適用した見積もり額と"
        "ルーティングルールに基づくチャネル推奨一覧を返す。\n\n"
        "レスポンスの `defect_evidence_required` が `true` の場合、"
        " `POST /assessments/{assessment_id}/defects` で瑕疵写真の添付が必要。"
    ),
    responses={
        404: {"description": "item_id が存在しない"},
        422: {"description": "condition に UNKNOWN を指定した場合など"},
    },
)
async def estimate(
    body: EstimateRequest,
    session: AsyncSession = Depends(get_session),
) -> EstimateResponse:
    """コンディション確定後の減価計算 + ルーティングを実行する。

    影響範囲: assessments / recommendations テーブルへの INSERT。
    Phase 4 変更: evaluate_routing_rules に item を渡すよう更新（outbound_url 生成のため）。
    """
    # 1. Item を取得
    item: Item | None = await session.get(Item, body.item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"item_id={body.item_id} の Item が見つかりません。",
        )

    # 2. 基準相場を attributes から取得（/analyze 時に格納した値）
    base_market_price: int = int(item.attributes.get("base_market_price_jpy", 0))

    # 3. 全コンディション見積もりを算出
    condition_details: dict[str, ConditionDetail] = {
        cond.value: ConditionDetail(
            label=cfg.label,
            multiplier=cfg.multiplier,
            estimated_price=int(base_market_price * cfg.multiplier),
            defect_evidence_required=cfg.defect_evidence_required,
        )
        for cond, cfg in CONDITION_CONFIG.items()
    }

    selected_cfg = CONDITION_CONFIG[body.condition]
    estimated_price = int(base_market_price * selected_cfg.multiplier)

    # 4. Assessment を生成して flush（ID を確定させる）
    assessment = Assessment(
        item_id=item.id,
        status=AssessmentStatus.PENDING,
        estimated_price_min=estimated_price,
        estimated_price_max=estimated_price,
        price_currency="JPY",
        price_basis={
            "condition": body.condition.value,
            "multiplier": selected_cfg.multiplier,
            "base_market_price_jpy": base_market_price,
        },
    )
    session.add(assessment)
    await session.flush()  # assessment.id を確定させる（コミット前）

    # 5. ルーティングエンジンで AssessmentRecommendation を生成
    #    Phase 4: item を渡して outbound_url を生成させる
    routing_result = await evaluate_routing_rules(
        session=session,
        assessment=assessment,
        item=item,
        category_tier=item.category_tier,
        condition=body.condition,
        base_market_price=base_market_price,
    )

    # 6. Assessment を COMPLETED に更新してコミット
    assessment.status = AssessmentStatus.COMPLETED
    assessment.routing_method = routing_result.method
    await session.commit()

    # 7. recommendations + channel を eager-load してレスポンスを構築
    stmt = (
        select(AssessmentRecommendation)
        .where(AssessmentRecommendation.assessment_id == assessment.id)
        .order_by(AssessmentRecommendation.rank.asc())
        .options(selectinload(AssessmentRecommendation.channel))
    )
    rec_result = await session.execute(stmt)
    loaded_recs: list[AssessmentRecommendation] = list(rec_result.scalars().all())

    recommendations = [
        RecommendationResponse(
            rank=rec.rank,
            channel_code=rec.channel.code,
            channel_name=rec.channel.display_name,
            channel_type=rec.channel.channel_type,
            reason=rec.reason,
            outbound_url=rec.outbound_url,
            is_sponsored=rec.is_sponsored,
        )
        for rec in loaded_recs
    ]

    return EstimateResponse(
        assessment_id=assessment.id,
        base_market_price=base_market_price,
        price_currency="JPY",
        conditions=condition_details,
        selected_condition=body.condition,
        estimated_price=estimated_price,
        defect_evidence_required=selected_cfg.defect_evidence_required,
        routing_method=routing_result.method,
        recommendations=recommendations,
    )


@router.get(
    "/assessments/{assessment_id}",
    response_model=AssessmentGetResponse,
    status_code=status.HTTP_200_OK,
    summary="査定結果取得",
    description="assessment_id で既存の Assessment を参照する（/result ページのフォールバック用）。",
    responses={
        404: {"description": "assessment_id が存在しない"},
    },
)
async def get_assessment(
    assessment_id: uuid.UUID = Path(description="estimate が返した assessment_id"),
    session: AsyncSession = Depends(get_session),
) -> AssessmentGetResponse:
    """既存 Assessment + Recommendations を取得する。

    影響範囲: SELECT のみ（副作用なし）。
    """
    stmt_get = (
        select(Assessment)
        .where(Assessment.id == assessment_id)
        .options(
            selectinload(Assessment.recommendations).selectinload(  # type: ignore[arg-type]
                AssessmentRecommendation.channel
            )
        )
    )
    result_get = await session.execute(stmt_get)
    assessment: Assessment | None = result_get.scalars().first()
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"assessment_id={assessment_id} の Assessment が見つかりません。",
        )

    # price_basis から defect_evidence_required を再構築
    price_basis: dict = assessment.price_basis or {}
    condition_value: str = price_basis.get("condition", "")
    defect_required = False
    try:
        cond_enum = ItemCondition(condition_value)
        defect_required = CONDITION_CONFIG[cond_enum].defect_evidence_required
    except (ValueError, KeyError):
        pass

    recommendations = [
        RecommendationResponse(
            rank=rec.rank,
            channel_code=rec.channel.code,
            channel_name=rec.channel.display_name,
            channel_type=rec.channel.channel_type,
            reason=rec.reason,
            outbound_url=rec.outbound_url,
            is_sponsored=rec.is_sponsored,
        )
        for rec in sorted(assessment.recommendations, key=lambda r: r.rank)
    ]

    return AssessmentGetResponse(
        assessment_id=assessment.id,
        item_id=assessment.item_id,
        estimated_price=assessment.estimated_price_min,
        defect_evidence_required=defect_required,
        recommendations=recommendations,
    )


@router.post(
    "/assessments/{assessment_id}/defects",
    response_model=DefectUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="瑕疵エビデンス写真のアップロード",
    description=(
        "`estimate` レスポンスの `defect_evidence_required` が `true` の場合に呼び出す。\n\n"
        "写真を受け取りオブジェクトストレージキーを DB に保存する（非同期処理）。"
    ),
    responses={
        404: {"description": "assessment_id が存在しない"},
    },
)
async def upload_defect(
    assessment_id: uuid.UUID = Path(description="estimate が返した assessment_id"),
    body: DefectUploadRequest = ...,
    session: AsyncSession = Depends(get_session),
) -> DefectUploadResponse:
    """瑕疵エビデンスを DB に永続化する。

    影響範囲:
    - Assessment の存在確認（SELECT）。
    - defect_evidences テーブルへの INSERT（Phase 4 実装）。

    TODO(Phase 5): 実オブジェクトストレージ（S3/GCS）へのアップロードを非同期タスクで実装する。
    """
    # Assessment の存在確認（404 ガード）
    assessment: Assessment | None = await session.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"assessment_id={assessment_id} の Assessment が見つかりません。",
        )

    # オブジェクトキーのモック生成
    # TODO(Phase 5): 実オブジェクトストレージのキーに置換する。
    defect_id = uuid.uuid4()
    mock_object_key = f"defects/{assessment_id}/{defect_id}.jpg"

    # DefectEvidence を DB に永続化（Phase 4 実装）
    evidence = DefectEvidence(
        id=defect_id,
        assessment_id=assessment_id,
        image_object_key=mock_object_key,
        description=body.description,
    )
    session.add(evidence)
    await session.commit()

    return DefectUploadResponse(
        defect_id=defect_id,
        assessment_id=assessment_id,
        image_object_key=mock_object_key,
        status="accepted",
    )
