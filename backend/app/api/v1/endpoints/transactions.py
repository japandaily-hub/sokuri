"""成約エンドポイント — 詳細 / 完了 / キャンセル。

住所詳細・連絡先は本エンドポイントでのみ開示する（品質基準）:
- 開示先は「所有ユーザー」と「落札業者」のみ。サーバーサイドで判定する。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor
from app.db.models.bid import Bid
from app.db.models.case import Case
from app.db.models.message import Message
from app.db.models.transaction import Cancellation, Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    CaseMaskedOut,
    CasePhotoOut,
    MessageCreateRequest,
    MessageOut,
    OperatorPublicOut,
    ReductionOut,
    ReviewOut,
    ScheduleConfirmRequest,
    ScheduleProposeRequest,
    TransactionAddressOut,
    TransactionCancelRequest,
    TransactionDetailOut,
    TransactionListItem,
    TransactionOut,
)
from app.services import notify, notify_dispatch

logger = logging.getLogger(__name__)

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
    """当事者チェック。'user'（所有者/管理者）か 'operator'（落札業者）を返す。"""
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
        winning_operator = txn.bid.operator
        # 承認済み(active)以外（pending/limitedいずれも）は住所非開示にする（安全側）。
        # pending業者が入札できていたレガシーデータや、承認が取り消された業者の
        # 落札残存ケースを含めて一般化する。
        operator_not_active = (
            party == "operator" and winning_operator.vendor_status != "active"
        )
        if operator_not_active:
            out.awaiting_approval = True
        else:
            out.address = TransactionAddressOut(
                prefecture=case.prefecture,
                city=case.city,
                address_detail=case.address_detail,
            )
            if party == "operator":
                owner_email = await _owner_email(session, txn)
                # LINE専用ユーザーの仮メール（実メール未設定）はそのまま業者に開示しない。
                # 実在しないドメインの開示は業者側の連絡試行を無意味に失敗させるため、
                # 案内文言に置き換える（LINE経由での連絡を促す）。
                out.contact_email = (
                    "LINEにて連絡"
                    if notify.is_placeholder_email(owner_email)
                    else owner_email
                )
            else:
                out.contact_email = txn.bid.operator.contact_email

    out.unread_count = await _count_unread(session, txn, party)
    return out


async def _count_unread(session: AsyncSession, txn: Transaction, party: str) -> int:
    """相手が送信した、自分の last_read_at より後のメッセージ数を数える。"""
    my_last_read = txn.user_last_read_at if party == "user" else txn.operator_last_read_at
    peer_sender_type = "operator" if party == "user" else "user"
    stmt = select(func.count()).select_from(Message).where(
        Message.transaction_id == txn.id,
        Message.sender_type == peer_sender_type,
    )
    if my_last_read is not None:
        stmt = stmt.where(Message.created_at > my_last_read)
    count = await session.scalar(stmt)
    return int(count or 0)


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


# ──────────────────────────── チャット ────────────────────────────
#
# 承認待ち（awaiting_approval=true）業者が落札した成約でもメッセージの送受信は
# 許可する（住所非開示のみで会話自体は許可という確定方針）。したがって本セクションの
# エンドポイントは当事者性（_assert_party）のみで判定し、vendor_status は問わない。


def _to_message_out(message: Message, party: str) -> MessageOut:
    out = MessageOut.model_validate(message)
    out.mine = message.sender_type == party
    return out


@router.get(
    "/transactions/{transaction_id}/messages",
    response_model=list[MessageOut],
    summary="チャットメッセージ一覧（当事者のみ。after指定で差分取得）",
)
async def list_messages(
    transaction_id: uuid.UUID,
    after: datetime | None = Query(default=None, description="ISO8601。指定時はそれ以降の差分のみ返す"),
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)

    stmt = (
        select(Message)
        .where(Message.transaction_id == txn.id)
        .order_by(Message.created_at.asc())
    )
    if after is not None:
        stmt = stmt.where(Message.created_at > after)
    messages = (await session.scalars(stmt)).all()
    return [_to_message_out(m, party) for m in messages]


@router.post(
    "/transactions/{transaction_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="チャットメッセージ送信（当事者のみ）",
)
async def create_message(
    transaction_id: uuid.UUID,
    body: MessageCreateRequest,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)

    # sender_type はクライアント入力を受け取らず actor から自動判定する（なりすまし防止）。
    message = Message(
        transaction_id=txn.id,
        sender_type=party,
        sender_id=actor.id,
        body=body.body,
        kind="text",
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return _to_message_out(message, party)


@router.post(
    "/transactions/{transaction_id}/messages/read",
    response_model=TransactionOut,
    summary="既読ポインタ更新（当事者のみ・自分側のみ更新）",
)
async def mark_messages_read(
    transaction_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> TransactionOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)

    now = datetime.now(timezone.utc)
    if party == "user":
        txn.user_last_read_at = now
    else:
        txn.operator_last_read_at = now
    await session.commit()
    await session.refresh(txn)
    return TransactionOut.model_validate(txn)


# ──────────────────────────── 日程調整 ────────────────────────────


@router.post(
    "/transactions/{transaction_id}/schedule/propose",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="訪問日程の候補提示（落札業者のみ）",
)
async def propose_schedule(
    transaction_id: uuid.UUID,
    body: ScheduleProposeRequest,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    if party != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="日程候補の提示は落札業者のみ行えます。",
        )

    message = Message(
        transaction_id=txn.id,
        sender_type="operator",
        sender_id=actor.id,
        body=f"訪問日程の候補を{len(body.slots)}件提示しました。",
        kind="schedule_proposal",
        meta={"slots": body.slots},
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return _to_message_out(message, party)


@router.post(
    "/transactions/{transaction_id}/schedule/confirm",
    response_model=TransactionOut,
    summary="訪問日程の確定（所有ユーザーのみ）",
)
async def confirm_schedule(
    transaction_id: uuid.UUID,
    body: ScheduleConfirmRequest,
    background: BackgroundTasks,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> TransactionOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    if party != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="日程確定はユーザー側のみ行えます。",
        )
    if txn.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="日程確定できる状態ではありません。",
        )

    txn.visit_date = body.visit_date
    txn.visit_time_slot = body.visit_time_slot
    txn.status = "visiting"

    confirm_body = f"訪問日程が {body.visit_date} {body.visit_time_slot} に確定しました。"
    if body.note:
        confirm_body += f" ({body.note})"
    session.add(
        Message(
            transaction_id=txn.id,
            sender_type="system",
            sender_id=None,
            body=confirm_body,
            kind="schedule_confirmed",
            meta={"visit_date": body.visit_date.isoformat(), "visit_time_slot": body.visit_time_slot},
        )
    )
    operator_email = txn.bid.operator.contact_email
    operator_line_user_id = txn.bid.operator.line_user_id
    await session.commit()
    await session.refresh(txn)

    background.add_task(
        notify_dispatch.dispatch_schedule_confirmed,
        operator_line_user_id,
        operator_email,
        str(txn.id),
        body.visit_date.isoformat(),
    )
    return TransactionOut.model_validate(txn)
