"""入札エンドポイント — 一覧 / 入札 / 業者選択（落札）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor, get_current_user, get_verified_operator
from app.db.models.bid import Bid
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import BidCreateRequest, BidOut, TransactionOut
from app.services import notify, notify_dispatch
from app.services.message_guard import contains_contact_info

router = APIRouter()


async def _get_case(session: AsyncSession, case_id: uuid.UUID) -> Case:
    case = await session.scalar(
        select(Case)
        .where(Case.id == case_id)
        .options(
            selectinload(Case.bids).selectinload(Bid.operator),
            selectinload(Case.bids).selectinload(Bid.transaction),
        )
    )
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    return case


def _bid_out(bid: Bid) -> BidOut:
    out = BidOut.model_validate(bid)
    if bid.status == "selected" and bid.transaction is not None:
        out.transaction_id = bid.transaction.id
    return out


@router.get(
    "/cases/{case_id}/bids",
    response_model=list[BidOut],
    summary="入札一覧（所有ユーザー: 全件 / 業者: 自社分のみ）",
)
async def list_bids(
    case_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> list[BidOut]:
    case = await _get_case(session, case_id)

    if actor.typ == "user":
        assert actor.user is not None
        if case.user_id != actor.user.id and actor.user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
            )
        return [_bid_out(b) for b in case.bids]

    assert actor.operator is not None
    return [_bid_out(b) for b in case.bids if b.operator_id == actor.operator.id]


@router.post(
    "/cases/{case_id}/bids",
    response_model=BidOut,
    status_code=status.HTTP_201_CREATED,
    summary="入札する（承認済み業者のみ）",
)
async def create_bid(
    case_id: uuid.UUID,
    body: BidCreateRequest,
    background: BackgroundTasks,
    operator: Operator = Depends(get_verified_operator),
    session: AsyncSession = Depends(get_session),
) -> BidOut:
    case = await _get_case(session, case_id)
    if case.status not in ("open", "bidding"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は入札を受け付けていません。",
        )
    if any(b.operator_id == operator.id for b in case.bids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件には既に入札済みです。",
        )
    # プラットフォーム外への直接連絡を誘導する電話番号/URL/メールアドレスの
    # 埋め込みは利用規約の禁止行為のため、入札作成時に拒否する（security review Low指摘対応）。
    if contains_contact_info(body.message):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="入札メッセージに連絡先（電話番号・メールアドレス）やURLは記載できません。",
        )

    bid = Bid(case_id=case.id, operator_id=operator.id, amount=body.amount, message=body.message)
    session.add(bid)
    case.status = "bidding"
    await session.commit()
    await session.refresh(bid)
    bid.operator = operator

    if case.user_id is not None:
        owner = await session.get(User, case.user_id)
        # LINE専用ユーザーの仮メール（実メール未設定）宛には送信しない。
        # 配送不能なだけでなく、実在しないドメインへの送信試行をログに残さないため。
        if owner is not None and not notify.is_placeholder_email(owner.email):
            background.add_task(
                notify.send_bid_received,
                owner.email,
                str(case.id),
                operator.company_name,
                bid.amount,
            )
    return BidOut.model_validate(bid)


@router.post(
    "/cases/{case_id}/bids/{bid_id}/select",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="業者を選択して落札確定（成約レコード作成）",
)
async def select_bid(
    case_id: uuid.UUID,
    bid_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TransactionOut:
    case = await _get_case(session, case_id)
    if case.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
        )
    if case.status != "bidding":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="選択可能な状態ではありません（入札待ちまたは成約済み）。",
        )

    target: Bid | None = next((b for b in case.bids if b.id == bid_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="入札が見つかりません。"
        )
    if target.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="この入札は選択できません。"
        )

    target.status = "selected"
    # 落選業者への通知はcommit後にプリミティブ値で行う（ORMオブジェクトを
    # BackgroundTasksへ渡さない。commit後はセッションがdetachされうるため）。
    losers: list[tuple[str | None, str]] = []
    for b in case.bids:
        if b.id != target.id and b.status == "pending":
            b.status = "rejected"
            losers.append((b.operator.line_user_id, b.operator.contact_email))
    case.status = "closed"
    txn = Transaction(
        case_id=case.id,
        bid_id=target.id,
        initial_amount=target.amount,
        fee_amount=0,
        status="pending",
    )
    session.add(txn)
    winner_line_user_id = target.operator.line_user_id
    winner_contact_email = target.operator.contact_email
    winner_amount = target.amount
    case_id_str = str(case.id)
    await session.commit()
    await session.refresh(txn)

    background.add_task(
        notify_dispatch.dispatch_bid_selected,
        winner_line_user_id,
        winner_contact_email,
        str(txn.id),
        winner_amount,
    )
    for loser_line_user_id, loser_email in losers:
        background.add_task(
            notify_dispatch.dispatch_bid_lost,
            loser_line_user_id,
            loser_email,
            case_id_str,
        )
    return TransactionOut.model_validate(txn)
