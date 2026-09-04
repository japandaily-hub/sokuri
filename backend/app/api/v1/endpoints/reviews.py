"""レビューエンドポイント — 成約完了後の双方向評価。

reviewer_type はトークン種別から導出する（クライアント指定を信用しない）。
ユーザー → 業者のレビュー投稿時は operators.rating（平均値）を再計算する。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor
from app.db.models.transaction import Review, Transaction
from app.db.session import get_session
from app.schemas_katadzuke import ReviewCreateRequest, ReviewOut
from app.services.review_stats import recalc_operator_review_stats

router = APIRouter()


@router.post(
    "/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="レビュー投稿（成約完了後・当事者のみ）",
)
async def create_review(
    body: ReviewCreateRequest,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> ReviewOut:
    txn = await session.scalar(
        select(Transaction)
        .where(Transaction.id == body.transaction_id)
        .options(
            selectinload(Transaction.case),
            selectinload(Transaction.bid),
            selectinload(Transaction.reviews),
        )
    )
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )

    # 当事者チェック + reviewer_type 導出
    if actor.typ == "user":
        assert actor.user is not None
        if txn.case.user_id != actor.user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
            )
        reviewer_type = "user"
    else:
        assert actor.operator is not None
        if txn.bid.operator_id != actor.operator.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
            )
        reviewer_type = "operator"

    if txn.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="レビューは成約完了後に投稿できます。",
        )
    if any(r.reviewer_type == reviewer_type for r in txn.reviews):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="既にレビュー投稿済みです。"
        )

    review = Review(
        transaction_id=txn.id,
        reviewer_type=reviewer_type,
        rating=body.rating,
        comment=body.comment,
    )
    session.add(review)
    await session.flush()

    # ユーザー → 業者評価なら operators の集計列（rating / review_count /
    # latest_review_comment）を再計算する（正本は services/review_stats.py。
    # 対象 operators 行を排他ロックしてから集計するため同時投稿でもずれない）。
    if reviewer_type == "user":
        await recalc_operator_review_stats(session, txn.bid.operator_id)

    try:
        await session.commit()
    except IntegrityError:
        # uq_reviews_transaction_reviewer（同一取引・同一投稿者は1件）。アプリ層の
        # 重複チェックをすり抜けた二重送信は 500 ではなく 409 にする（security review L-3）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="既にレビュー投稿済みです。"
        ) from None
    await session.refresh(review)
    return ReviewOut.model_validate(review)
