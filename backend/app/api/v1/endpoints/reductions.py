"""減額申請エンドポイント — 申請（業者）/ 承認・却下（ユーザー）。

品質基準: reason はサーバーサイドで必須（Pydantic min_length=10 + DB NOT NULL）。
承認時のみ transaction.final_amount を更新する。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_operator, get_current_user
from app.db.models.bid import Bid
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.models.transaction import ReductionRequest, Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    ReductionCreateRequest,
    ReductionDecisionRequest,
    ReductionOut,
)

router = APIRouter()

_TXN_LOAD = (
    selectinload(Transaction.case),
    selectinload(Transaction.bid),
    selectinload(Transaction.reduction_requests),
)


async def _get_txn(session: AsyncSession, txn_id: uuid.UUID) -> Transaction:
    txn = await session.scalar(
        select(Transaction).where(Transaction.id == txn_id).options(*_TXN_LOAD)
    )
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )
    return txn


@router.post(
    "/transactions/{transaction_id}/reduction",
    response_model=ReductionOut,
    status_code=status.HTTP_201_CREATED,
    summary="減額申請（落札業者・理由必須）",
)
async def create_reduction(
    transaction_id: uuid.UUID,
    body: ReductionCreateRequest,
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> ReductionOut:
    txn = await _get_txn(session, transaction_id)
    if txn.bid.operator_id != operator.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
        )
    if txn.status not in ("pending", "visiting"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="減額申請できる状態ではありません。",
        )
    if any(r.status == "pending" for r in txn.reduction_requests):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="未回答の減額申請があります。回答をお待ちください。",
        )

    original = txn.final_amount if txn.final_amount is not None else txn.initial_amount
    if body.requested_amount >= original:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="減額後の金額は現在の金額より小さい必要があります。",
        )

    # reason は Pydantic（min_length=10）+ DB NOT NULL の二重で強制される
    reduction = ReductionRequest(
        transaction_id=txn.id,
        operator_id=operator.id,
        original_amount=original,
        requested_amount=body.requested_amount,
        reason=body.reason,
    )
    session.add(reduction)
    await session.commit()
    await session.refresh(reduction)
    return ReductionOut.model_validate(reduction)


@router.patch(
    "/transactions/{transaction_id}/reduction/{reduction_id}",
    response_model=ReductionOut,
    summary="減額申請への回答（ユーザー: 承認 / 却下）",
)
async def decide_reduction(
    transaction_id: uuid.UUID,
    reduction_id: uuid.UUID,
    body: ReductionDecisionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReductionOut:
    txn = await _get_txn(session, transaction_id)
    if txn.case.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
        )
    reduction = next((r for r in txn.reduction_requests if r.id == reduction_id), None)
    if reduction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="減額申請が見つかりません。"
        )
    if reduction.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="既に回答済みの申請です。"
        )

    if body.action == "approve":
        reduction.status = "approved"
        txn.final_amount = reduction.requested_amount
    else:
        reduction.status = "rejected"
    await session.commit()
    await session.refresh(reduction)
    return ReductionOut.model_validate(reduction)
