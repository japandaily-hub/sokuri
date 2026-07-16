"""業者プロフィール — 自社編集（/operator/profile）と公開参照（/vendors/{operator_id}）。

審査確定項目（company_name, license_number, verified_at, vendor_status, rating等）は
Operator 本体でのみ管理し、本エンドポイントの PUT では更新できない。
編集可能項目（areas, categories, strong_categories, staff_count, business_hours,
intro_message, is_public, show_stats, show_reviews, show_message, accept_unsellable）
は operator_profiles テーブルで管理する。

閲覧・編集は vendor_status を問わず許可する（get_current_operator を使用）。
チャット同様「承認待ちでも会話・プロフィール確認自体は可能」という方針に揃える
（入札のみ get_verified_operator で別途ブロックされる非対称設計を踏襲）。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.db.models.bid import Bid
from app.db.models.operator import Operator
from app.db.models.operator_profile import OperatorProfile
from app.db.models.transaction import Review, Transaction
from app.db.session import get_session
from app.schemas_katadzuke import (
    OperatorProfileOut,
    OperatorProfileUpdateRequest,
    OperatorPublicProfileOut,
    ReviewOut,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_or_create_profile(session: AsyncSession, operator_id: uuid.UUID) -> OperatorProfile:
    profile = await session.get(OperatorProfile, operator_id)
    if profile is None:
        profile = OperatorProfile(operator_id=operator_id)
        session.add(profile)
        try:
            await session.commit()
        except IntegrityError:
            # 同時リクエストが先に作成済み（operator_id は主キー）。
            # 自分の INSERT は諦めて既存レコードを取り直す。
            await session.rollback()
            profile = await session.get(OperatorProfile, operator_id)
            if profile is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="プロフィールの初期化に失敗しました。",
                ) from None
            return profile
        except Exception as exc:
            await session.rollback()
            logger.error(
                "operator_profile: 初回プロフィール自動作成に失敗 - operator_id=%s - %s",
                operator_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="プロフィールの初期化に失敗しました。",
            ) from exc
        await session.refresh(profile)
    return profile


def _to_profile_out(operator: Operator, profile: OperatorProfile) -> OperatorProfileOut:
    return OperatorProfileOut(
        operator_id=operator.id,
        company_name=operator.company_name,
        license_number=operator.license_number,
        verified_at=operator.verified_at,
        vendor_status=operator.vendor_status,
        rating=operator.rating,
        areas=profile.areas or [],
        categories=profile.categories or [],
        strong_categories=profile.strong_categories or [],
        staff_count=profile.staff_count,
        business_hours=profile.business_hours,
        intro_message=profile.intro_message,
        is_public=profile.is_public,
        show_stats=profile.show_stats,
        show_reviews=profile.show_reviews,
        show_message=profile.show_message,
        accept_unsellable=profile.accept_unsellable,
    )


@router.get(
    "/operator/profile",
    response_model=OperatorProfileOut,
    summary="自社プロフィール取得（審査確定項目 + 編集可能項目）",
)
async def get_my_operator_profile(
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> OperatorProfileOut:
    profile = await _get_or_create_profile(session, operator.id)
    return _to_profile_out(operator, profile)


@router.put(
    "/operator/profile",
    response_model=OperatorProfileOut,
    summary="自社プロフィール更新（編集可能項目のみ。審査確定項目は無視する）",
)
async def update_my_operator_profile(
    body: OperatorProfileUpdateRequest,
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> OperatorProfileOut:
    if not set(body.strong_categories).issubset(set(body.categories)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="strong_categories は categories の部分集合である必要があります。",
        )

    profile = await _get_or_create_profile(session, operator.id)
    profile.areas = body.areas
    profile.categories = body.categories
    profile.strong_categories = body.strong_categories
    profile.staff_count = body.staff_count
    profile.business_hours = body.business_hours
    profile.intro_message = body.intro_message
    profile.is_public = body.is_public
    profile.show_stats = body.show_stats
    profile.show_reviews = body.show_reviews
    profile.show_message = body.show_message
    profile.accept_unsellable = body.accept_unsellable

    await session.commit()
    await session.refresh(profile)
    await session.refresh(operator)
    return _to_profile_out(operator, profile)


@router.get(
    "/vendors/{operator_id}",
    response_model=OperatorPublicProfileOut,
    summary="業者公開プロフィール取得（is_public=false は404、show_*フラグに応じて項目を省く）",
)
async def get_vendor_public_profile(
    operator_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> OperatorPublicProfileOut:
    operator = await session.get(Operator, operator_id)
    if operator is None or operator.is_suspended:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="業者が見つかりません。")

    profile = await session.get(OperatorProfile, operator_id)
    if profile is None:
        # プロフィール行は業者が自分のプロフィール画面を開いた時に遅延作成される。
        # 既定は「公開」(is_public default=True) のため、行が無いだけの業者を 404 に
        # しない（チャットの「プロフィールを見る」導線が壊れる）。既定値の仮想
        # プロフィールとして扱う（GET で行は作成しない。SQLAlchemy の default は
        # flush 時適用のため、ここでは明示的に既定値を渡す）。
        profile = OperatorProfile(
            operator_id=operator_id,
            is_public=True,
            show_stats=True,
            show_reviews=True,
            show_message=True,
            accept_unsellable=False,
        )
    if not profile.is_public:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="業者が見つかりません。")

    reviews_out: list[ReviewOut] | None = None
    if profile.show_reviews:
        rows = (
            await session.scalars(
                select(Review)
                .join(Transaction, Review.transaction_id == Transaction.id)
                .join(Bid, Transaction.bid_id == Bid.id)
                .where(Bid.operator_id == operator_id)
                .order_by(Review.created_at.desc())
                .limit(50)
            )
        ).all()
        reviews_out = [ReviewOut.model_validate(r) for r in rows]

    return OperatorPublicProfileOut(
        operator_id=operator.id,
        company_name=operator.company_name,
        verified_at=operator.verified_at,
        areas=profile.areas or [],
        categories=profile.categories or [],
        strong_categories=profile.strong_categories or [],
        staff_count=profile.staff_count,
        business_hours=profile.business_hours,
        intro_message=profile.intro_message if profile.show_message else None,
        accept_unsellable=profile.accept_unsellable,
        rating=operator.rating if profile.show_stats else None,
        reviews=reviews_out,
    )
