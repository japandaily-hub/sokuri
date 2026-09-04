"""減額申請エンドポイント — 申請（業者）/ 承認・却下（ユーザー）。

品質基準: reason はサーバーサイドで必須（Pydantic min_length=10 + DB NOT NULL）。
承認時のみ transaction.final_amount を更新する。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from app.services import notify_dispatch
from app.services.case_lock import lock_transaction_rows

router = APIRouter()

# 1取引あたりの減額申請の上限回数（却下後に1回だけ再申請できる）。r8-M3 対応。
_MAX_REDUCTION_REQUESTS = 2

_TXN_LOAD = (
    selectinload(Transaction.case),
    # Bid.operator は減額の往路（依頼者への申請通知）・復路（業者への決定通知）
    # いずれの通知先解決にも必要なため eager load する（R3-H2 / ADD-2対応）。
    selectinload(Transaction.bid).selectinload(Bid.operator),
    selectinload(Transaction.reduction_requests),
)


async def _get_txn(session: AsyncSession, txn_id: uuid.UUID) -> Transaction:
    txn = await session.scalar(
        select(Transaction)
        .where(Transaction.id == txn_id)
        .options(*_TXN_LOAD)
        # 行ロック取得後に読み直す経路（create_reduction）があるため、identity map の
        # 陳腐化した reduction_requests を掴まないよう常に再読込する（r8-review M-6）。
        # 本番はリクエストごとに新規セッションのため実質no-opだが、単一セッションを
        # 共有するテストハーネスでは必須（bids._get_case と同じ理由・同じ作法）。
        .execution_options(populate_existing=True)
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
    background: BackgroundTasks,
    operator: Operator = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> ReductionOut:
    # 上限判定（下記 _MAX_REDUCTION_REQUESTS）と pending 判定は read→check→write が
    # 非原子で、2件目が pending のまま「依頼者の却下」と「業者の再申請」が同時着弾
    # すると、uq_reduction_requests_pending（pending 2行のみを禁じる）を素通りして
    # 3件目が入りうる（r8-review M-6）。当事者経路と同一のロック規約
    # （Case → Transaction）に参加し、ロック後に読み直してから判定する。
    # 認可判定より前にロックを取るが、対象は「自分が当事者でない成約」でも
    # transaction_id を知る必要があり、かつ保持は本リクエスト内の数ms（admin の
    # 強制終了・transactions.cancel と同じ作法）のためロック争奪DoSの実効性は無い。
    if await lock_transaction_rows(session, transaction_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )
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
    # 却下後の再申請は1回まで（r8-M3）。無制限だと、依頼者の「作業完了を確定する」は
    # pending 減額があると 409（transactions.complete）になるため、業者が却下のたびに
    # 再申請するだけで依頼者を完了不能に閉じ込められる（ループ可能）。
    # 同時2リクエストは uq_reduction_requests_pending（0028）が pending 2行を禁じるため、
    # 「1件が却下されるまで次は入らない」の直列化と本カウントの併用で上限が保たれる。
    if len(txn.reduction_requests) >= _MAX_REDUCTION_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="減額申請は1つの取引につき2回までです。",
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
    try:
        await session.commit()
    except IntegrityError as exc:
        # 上記の in-memory チェック（any(...)）は同時2リクエスト（二度押し・リトライ）を
        # 防げない。pending が2行残ると以後その判定により業者が恒久的に409で締め出される
        # ため、真の一意性は uq_reduction_requests_pending（0028 の部分一意索引）で担保し、
        # 違反はここで409へ変換する（bids.create_bid と同じ多層防御パターン）。
        # 注: 部分一意索引（postgresql_where と sqlite_where を併記）は PostgreSQL・
        # SQLite の双方で発火する。SQLite 用テストでも実際に IntegrityError を検証する。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="未回答の減額申請があります。回答をお待ちください。",
        ) from exc
    await session.refresh(reduction)

    # 依頼者への通知（ADD-2対応: 往路の通知が無いと、依頼者が気づかない限り
    # pending中は次の申請が409で拒否され続け、業者が無期限にブロックされる）。
    # BackgroundTasks へは ORM オブジェクトではなくプリミティブ値のみを渡す
    # （commit後はセッションがdetachされうるため。bids.py と同じ規約）。
    owner_line_user_id: str | None = None
    owner_email: str | None = None
    if txn.case.user_id is not None:
        owner = await session.get(User, txn.case.user_id)
        if owner is not None:
            owner_line_user_id = owner.line_user_id
            owner_email = owner.email
    background.add_task(
        notify_dispatch.dispatch_reduction_requested,
        owner_line_user_id,
        owner_email,
        str(txn.case_id),
        reduction.requested_amount,
    )
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
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReductionOut:
    txn = await _get_txn(session, transaction_id)
    if txn.case.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
        )
    # 完了・キャンセル済みの取引では回答を受け付けない。受け付けると
    # complete_transaction が確定させた final_amount が事後に書き換わる
    # （r6-flow ADD-2 / r6-backend M-3）。create_reduction と同じ条件式を使う。
    if txn.status not in ("pending", "visiting"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="回答できる状態ではありません。",
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

    approved = body.action == "approve"
    if approved:
        reduction.status = "approved"
        txn.final_amount = reduction.requested_amount
    else:
        reduction.status = "rejected"

    # 業者への通知（R3-H2対応）。commit前にプリミティブ値へ取り出す
    # （bids.py の select_bid と同じ規約。txn.bid.operator は _TXN_LOAD で
    # eager load 済み）。
    operator_line_user_id = txn.bid.operator.line_user_id
    operator_contact_email = txn.bid.operator.contact_email
    transaction_id_str = str(txn.id)
    decided_amount = reduction.requested_amount

    await session.commit()
    await session.refresh(reduction)

    background.add_task(
        notify_dispatch.dispatch_reduction_decided,
        operator_line_user_id,
        operator_contact_email,
        transaction_id_str,
        approved,
        decided_amount,
    )
    return ReductionOut.model_validate(reduction)
