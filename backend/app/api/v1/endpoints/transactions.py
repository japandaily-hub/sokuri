"""成約エンドポイント — 一覧 / 詳細 / 完了 / キャンセル。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor
from app.db.models.bid import Bid
from app.db.models.case import Case
from app.db.models.transaction import Cancellation, Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    CaseMaskedOut,
    CasePhotoOut,
    OperatorPublicOut,
    ReductionOut,
    ReviewOut,
    TransactionAddressOut,
    TransactionCancelRequest,
    TransactionDetailOut,
    TransactionListItem,
    TransactionOut,
)

router = APIRouter()


@router.get(
    "/transactions",
    response_model=list[TransactionListItem],
    summary="成約一覧（ユーザー: 自分の成約 / 業者: 落札案件）",
)
async def list_transactions(
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> list[TransactionListItem]:
    stmt = (
        select(Transaction)
        .join(Case, Transaction.case_id == Case.id)
        .join(Bid, Transaction.bid_id == Bid.id)
        .options(
            selectinload(Transaction.case),
            selectinload(Transaction.bid).selectinload(Bid.operator),
            selectinload(Transaction.reduction_requests),
        )
        .order_by(Transaction.created_at.desc())
    )
    if actor.typ == "user":
        assert actor.user is not None
        stmt = stmt.where(Case.user_id == actor.user.id)
    else:
        assert actor.operator is not None
        stmt = stmt.where(Bid.operator_id == actor.operator.id)

    txns = (await session.scalars(stmt)).all()
    return [
        TransactionListItem(
            id=t.id,
            case_id=t.case_id,
            status=t.status,
            initial_amount=t.initial_amount,
            final_amount=t.final_amount,
            visit_date=t.visit_date,
            created_at=t.created_at,
            purpose=t.case.purpose,
            prefecture=t.case.prefecture,
            city=t.case.city,
            company_name=t.bid.operator.company_name if actor.typ == "user" else None,
            has_pending_reduction=any(
                r.status == "pending" for r in t.reduction_requests
            ),
        )
        for t in txns
    ]


_TXN_LOAD = (
    selectinload(Transaction.case).selectinload(Case.photos),
    selectinload(Transaction.bid).selectinload(Bid.operator),
    selectinload(Transaction.reduction_requests),
    selectinload(Transaction.reviews),
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


def _assert_party(txn: Transaction, actor: Actor) -> str:
    if actor.typ == "user":
        assert actor.user is not None
        if txn.case.user_id == actor.user.id or actor.user.role == "admin":
            return "user"
    else:
        assert actor.operator is not None
        if txn.bid.operator_id == actor.operator.id:
            return "operator"
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
    )


async def _owner_email(session: AsyncSession, txn: Transaction) -> str | None:
    if txn.case.user_id is None:
        return None
    owner = await session.get(User, txn.case.user_id)
    return owner.email if owner else None


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionDetailOut,
    summary="成約詳細（落札業者へ住所詳細を開示）",
)
async def get_transaction(
    transaction_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> TransactionDetailOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)

    case = txn.case
    base = TransactionOut.model_validate(txn)
    out = TransactionDetailOut(**base.model_dump())
    out.case = CaseMaskedOut(
        id=case.id,
        status=case.status,
        purpose=case.purpose,
        prefecture=case.prefecture,
        city=case.city,
        housing_type=case.housing_type,
        floor_plan=case.floor_plan,
        floor_number=case.floor_number,
        has_elevator=case.has_elevator,
        ai_summary=case.ai_summary,
        created_at=case.created_at,
        photos=[CasePhotoOut.model_validate(p) for p in case.photos],
    )
    out.operator = OperatorPublicOut.model_validate(txn.bid.operator)
    out.reduction_requests = [ReductionOut.model_validate(r) for r in txn.reduction_requests]
    out.reviews = [ReviewOut.model_validate(r) for r in txn.reviews]

    if txn.status != "cancelled":
        out.address = TransactionAddressOut(
            prefecture=case.prefecture,
            city=case.city,
            address_detail=case.address_detail,
        )
        if party == "operator":
            out.contact_email = await _owner_email(session, txn)
        else:
            out.contact_email = txn.bid.operator.contact_email
    return out


@router.post(
    "/transactions/{transaction_id}/complete",
    response_model=TransactionOut,
    summary="成約完了（ユーザーが確定）",
)
async def complete_transaction(
    transaction_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> TransactionOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    if party != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="完了確定はユーザー側のみ行えます。",
        )
    if txn.status not in ("pending", "visiting"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="完了にできる状態ではありません。"
        )
    if txn.final_amount is None:
        txn.final_amount = txn.initial_amount
    txn.status = "completed"
    await session.commit()
    await session.refresh(txn)
    return TransactionOut.model_validate(txn)


@router.post(
    "/transactions/{transaction_id}/cancel",
    response_model=TransactionOut,
    summary="成約キャンセル（当事者いずれか）",
)
async def cancel_transaction(
    transaction_id: uuid.UUID,
    body: TransactionCancelRequest,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> TransactionOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    if txn.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="キャンセルできる状態ではありません。"
        )

    txn.status = "cancelled"
    txn.case.status = "cancelled"
    session.add(
        Cancellation(
            case_id=txn.case_id,
            transaction_id=txn.id,
            cancelled_by=party,
            reason=body.reason,
        )
    )
    if party == "operator":
        txn.bid.operator.cancel_count += 1
    await session.commit()
    await session.refresh(txn)
    return TransactionOut.model_validate(txn)
