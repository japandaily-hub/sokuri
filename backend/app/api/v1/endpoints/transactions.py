"""成約エンドポイント — 詳細 / 完了 / キャンセル。

住所詳細・連絡先は本エンドポイントでのみ開示する（品質基準）:
- 開示先は「所有ユーザー」と「落札業者」のみ。サーバーサイドで判定する。
"""

from __future__ import annotations

import re

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor
from app.db.models.bid import Bid
from app.db.models.case import Case, CaseItem
from app.db.models.message import Message
from app.db.models.operator import Operator
from app.db.models.transaction import Cancellation, Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    MessageCreateRequest,
    MessageOut,
    OperatorPublicOut,
    ReductionOut,
    ReviewOut,
    ScheduleConfirmRequest,
    ScheduleProposeRequest,
    TransactionAddressOut,
    TransactionCancellationOut,
    TransactionCancelRequest,
    TransactionDetailOut,
    TransactionListItem,
    TransactionOut,
)
from app.services import notify, notify_dispatch
from app.services.case_lock import lock_transaction_rows
from app.services.case_view import build_case_masked_out

logger = logging.getLogger(__name__)

router = APIRouter()

# 終了済み（cancelled / completed）取引への書き込みを拒否する共通の 409（r8-H3）。
# web はキャンセル通知メールのリンクからこの取引のチャット画面に着地しうるため、
# 機械可読な code と、そのまま表示できる日本語 message の両方を返す契約にする
# （deps.SUSPENDED_ACCOUNT_DETAIL と同じ dict detail 方式）。
TRANSACTION_CLOSED_DETAIL: dict[str, str] = {
    "code": "transaction_closed",
    "message": "この取引は終了しています。",
}
# 書き込みを許可する取引ステータス。既読ポインタ更新（mark_messages_read）は
# 「過去ログを読んだ」記録に過ぎず終了後も正当なため、意図的に対象外とする。
_ACTIVE_TXN_STATUSES = ("pending", "visiting")


def _assert_txn_open(txn: Transaction) -> None:
    """終了済み取引への書き込み（メッセージ送信・日程候補提示）を 409 で拒否する。"""
    if txn.status not in _ACTIVE_TXN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=TRANSACTION_CLOSED_DETAIL
        )


@router.get(
    "/transactions",
    response_model=list[TransactionListItem],
    summary="成約一覧（ユーザー: 自分の成約 / 業者: 落札案件）",
)
async def list_transactions(
    limit: int = Query(100, ge=1, le=200, description="取得件数の上限"),
    offset: int = Query(0, ge=0, description="取得開始位置"),
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> list[TransactionListItem]:
    # limit/offset を付けるまでは全件を eager load していたため、成約が積み上がる
    # ほど一覧が線形に重くなっていた（r6-verify-backend ADD-2）。応答形状（配列）は
    # 変えず、既定100件・上限200件に制限する。
    stmt = (
        select(Transaction)
        .join(Case, Transaction.case_id == Case.id)
        .join(Bid, Transaction.bid_id == Bid.id)
        .options(
            selectinload(Transaction.case),
            selectinload(Transaction.bid).selectinload(Bid.operator),
            selectinload(Transaction.reduction_requests),
            selectinload(Transaction.reviews),
        )
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if actor.typ == "user":
        assert actor.user is not None
        stmt = stmt.where(Case.user_id == actor.user.id)
    else:
        assert actor.operator is not None
        stmt = stmt.where(Bid.operator_id == actor.operator.id)

    txns = (await session.scalars(stmt)).all()
    unread_map = await _unread_counts(session, [t.id for t in txns], actor.typ)
    suspended_users = await _suspended_user_ids(
        session, [t.case.user_id for t in txns if t.case.user_id is not None]
    )
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
            has_review=any(rv.reviewer_type == "user" for rv in t.reviews),
            unread_count=unread_map.get(t.id, 0),
            user_suspended=t.case.user_id in suspended_users,
        )
        for t in txns
    ]


async def _suspended_user_ids(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """停止中の依頼者IDを **1クエリ**で引く（r8-M4。取引ごとの個別取得は N+1 になる）。

    停止中の行だけを返す（大半のユーザーは停止されていないため転送量が最小になる）。
    """
    if not user_ids:
        return set()
    rows = await session.scalars(
        select(User.id).where(User.id.in_(set(user_ids)), User.is_suspended.is_(True))
    )
    return set(rows.all())


async def _unread_counts(
    session: AsyncSession, txn_ids: list[uuid.UUID], party: str
) -> dict[uuid.UUID, int]:
    """取引ごとの未読数を **1クエリ**（GROUP BY）で数える（r6-flow M-3）。

    既読ポインタ（user_last_read_at / operator_last_read_at）は取引ごとに異なるため、
    transactions を join して行ごとの比較条件に使う。取引数ぶん _count_unread を
    呼ぶ実装は N+1 になるため採らない。
    """
    if not txn_ids:
        return {}
    read_col = (
        Transaction.user_last_read_at if party == "user" else Transaction.operator_last_read_at
    )
    peer_sender_type = "operator" if party == "user" else "user"
    rows = await session.execute(
        select(Message.transaction_id, func.count())
        .join(Transaction, Transaction.id == Message.transaction_id)
        .where(
            Message.transaction_id.in_(txn_ids),
            Message.sender_type == peer_sender_type,
            or_(read_col.is_(None), Message.created_at > read_col),
        )
        .group_by(Message.transaction_id)
    )
    return {txn_id: int(count) for txn_id, count in rows}

_TXN_LOAD = (
    selectinload(Transaction.case).selectinload(Case.photos),
    # items の eager load を忘れると成約詳細（CaseMaskedOut.items）参照時に
    # MissingGreenlet(500)になる（build_case_masked_out が case.items /
    # item.photos を同期的に参照するため）。
    selectinload(Transaction.case)
    .selectinload(Case.items)
    .selectinload(CaseItem.photos),
    selectinload(Transaction.bid).selectinload(Bid.operator),
    selectinload(Transaction.reduction_requests),
    selectinload(Transaction.reviews),
)


async def _get_txn(session: AsyncSession, txn_id: uuid.UUID) -> Transaction:
    txn = await session.scalar(
        select(Transaction)
        .where(Transaction.id == txn_id)
        .options(*_TXN_LOAD)
        # populate_existing: cases.py/bids.py と同じ理由（identity map 上の
        # 既ロードインスタンス再利用による関連コレクションの陳腐化防止）。
        .execution_options(populate_existing=True)
    )
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )
    return txn


async def _lock_txn_rows(session: AsyncSession, txn_id: uuid.UUID) -> None:
    """成約の状態遷移用の行ロック（実体は services/case_lock.lock_transaction_rows）。

    ロック手順そのものは admin の強制終了（r8-M5）と共有するため services へ移設した。
    本ラッパーは「見つからなければ 404」という当エンドポイント群の契約のみを担う。
    """
    if await lock_transaction_rows(session, txn_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )


async def _assert_party_before_lock(
    session: AsyncSession, txn_id: uuid.UUID, actor: Actor
) -> None:
    """認可（当事者性）の事前照会（軽量・ロック無し）。

    _lock_txn_rows を認可判定より先に呼ぶと、無関係な第三者が他人の
    transaction_id を大量に送りつけるだけで正規の complete/cancel/confirm_schedule
    処理を待たせるロック争奪DoSを誘発できてしまう（r6-verify-fix M1）。
    bids.select_bid・cases.cancel_case と同じパターンで、ロック取得前に
    Case.user_id / Bid.operator_id のみを読んで当事者性を確認する。
    ロック取得後は _get_txn + _assert_party を必ず再実行すること（本関数と
    ロックの間の競合に対する多層防御。上記2エンドポイントと同型）。
    """
    row = (
        await session.execute(
            select(Case.user_id, Bid.operator_id)
            .select_from(Transaction)
            .join(Case, Transaction.case_id == Case.id)
            .join(Bid, Transaction.bid_id == Bid.id)
            .where(Transaction.id == txn_id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )
    case_user_id, bid_operator_id = row
    if actor.typ == "user":
        assert actor.user is not None
        if case_user_id == actor.user.id or actor.user.role == "admin":
            return
    else:
        assert actor.operator is not None
        if bid_operator_id == actor.operator.id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
    )


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


async def _owner(session: AsyncSession, txn: Transaction) -> User | None:
    """案件所有者（依頼者）を1クエリ（PK取得）で引く。

    ``_owner_email`` を置き換える（メールに加えて停止状態 is_suspended も要るため。
    r8-M4）。case.user_id は退会・匿名化後も残る（NULL になるのは案件削除時のみ）。
    """
    if txn.case.user_id is None:
        return None
    return await session.get(User, txn.case.user_id)


async def _latest_cancellation(
    session: AsyncSession, txn_id: uuid.UUID
) -> Cancellation | None:
    """当該成約のキャンセル記録（最新1件）を引く。

    uq_cancellations_transaction_id（0028）により成約あたり最大1行だが、制約が
    緩められた場合に備えて created_at 降順の先頭を返す（LIMIT 1 で走査は定数）。
    """
    return await session.scalar(
        select(Cancellation)
        .where(Cancellation.transaction_id == txn_id)
        .order_by(Cancellation.created_at.desc(), Cancellation.id.desc())
        .limit(1)
    )


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
    owner = await _owner(session, txn)
    base = TransactionOut.model_validate(txn)
    out = TransactionDetailOut(**base.model_dump())
    out.case = build_case_masked_out(case)
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
                owner_email = owner.email if owner is not None else None
                # 内部専用メールはそのまま業者に開示しない。実在しないドメインの開示は
                # 業者側の連絡試行を無意味に失敗させ、退会トムストンは内部UUIDの漏出にもなる。
                # 退会済み→「退会済みユーザー」、LINE専用の仮メール→LINE経由の連絡を促す。
                if notify.is_deleted_account_email(owner_email):
                    out.contact_email = "退会済みユーザー"
                elif notify.is_placeholder_email(owner_email):
                    out.contact_email = "LINEにて連絡"
                else:
                    out.contact_email = owner_email
            else:
                # 業者退会（r8-M6）後は contact_email が同型のトムストンになるため、
                # 依頼者側にも同じ扱い（内部UUIDを開示しない）を適用する。
                operator_email = txn.bid.operator.contact_email
                out.contact_email = (
                    "退会済み業者"
                    if notify.is_deleted_account_email(operator_email)
                    else operator_email
                )

    # 業者が利用停止されると当該業者の全操作が403（deps）になり、依頼者側は
    # 「相手が無応答」の理由が分からないまま待たされる。依頼者に停止の事実だけを
    # 伝える（停止事由は開示しない）。r6-flow H-2 対応。
    out.operator_suspended = bool(txn.bid.operator.is_suspended)
    # 退会（deleted_at 非null）は停止と違い復帰しない。依頼者が「無応答の理由」を
    # 知り、キャンセル等の次の手を打てるよう独立した旗で伝える（r8-review M-5）。
    # 住所未開示のまま退会された場合、contact_email の「退会済み業者」分岐には
    # 到達しないため、この旗が唯一の手掛かりになる。
    out.operator_deleted = txn.bid.operator.deleted_at is not None
    # 逆方向（依頼者の停止）も業者に伝える。停止中の依頼者は日程確定・完了確定
    # （ユーザー専用操作）ができず取引が固定されるため、業者が待ち続ける理由を
    # 知れるようにする。停止事由は開示しない。r8-M4 対応。
    out.user_suspended = bool(owner is not None and owner.is_suspended)

    # キャンセル済みの場合のみ「誰が・なぜ・いつ」を返す（r8-H2）。理由は当事者の
    # 自由文であり、相手方・運営が経緯を把握する唯一の手段。
    if txn.status == "cancelled":
        cancellation = await _latest_cancellation(session, txn.id)
        if cancellation is not None:
            out.cancellation = TransactionCancellationOut.model_validate(cancellation)

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
    # 認可（当事者性）はロック取得より前に確認する（r6-verify-fix M1）。
    await _assert_party_before_lock(session, transaction_id, actor)
    # Case → Transaction の順で行ロックを取ってから読み直す（同時実行の cancel と
    # 後勝ちで矛盾しないようにする。r6-backend M-1）。
    await _lock_txn_rows(session, transaction_id)
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
    # 未回答の減額申請を残したまま完了すると final_amount=initial_amount で確定した
    # 後に decide_reduction が通り、確定額が事後に書き換わる（r6-flow ADD-2）。
    # decide_reduction 側の status ガードと対で、両方向の穴を塞ぐ。
    if any(r.status == "pending" for r in txn.reduction_requests):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="減額申請への回答が必要です。承認または却下のうえ完了してください。",
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
    background: BackgroundTasks,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> TransactionOut:
    # 認可（当事者性）はロック取得より前に確認する（r6-verify-fix M1）。
    await _assert_party_before_lock(session, transaction_id, actor)
    # complete との同時実行・二重送信を直列化する（r6-backend M-1 / M-2）。
    await _lock_txn_rows(session, transaction_id)
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    if txn.status in ("completed", "cancelled"):
        # 冪等化ではなく409。既に cancelled の取引に2行目の Cancellation を積まず、
        # cancel_count も二重加算しない（ロック取得後の再判定なので確実に効く）。
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
        # read-modify-write（+= 1）だと、同一業者の別成約のキャンセルと同時実行した
        # 際に更新が失われる。Case行ロックは案件単位のため業者行までは守れないので、
        # DB側で原子的に加算する（r6-verify-backend M-1 の指摘対応）。
        await session.execute(
            update(Operator)
            .where(Operator.id == txn.bid.operator_id)
            .values(cancel_count=Operator.cancel_count + 1)
        )

    # 相手方（キャンセルした側の逆）への通知（ADD-1対応: 通知が無いと、業者が
    # 依頼者のキャンセルに気づかないまま解約済み現場へ訪問しうる）。commit前に
    # プリミティブ値へ取り出す（bids.py/reductions.py と同じ規約）。
    if party == "user":
        recipient_party = "operator"
        recipient_line_user_id = txn.bid.operator.line_user_id
        recipient_email = txn.bid.operator.contact_email
    else:
        recipient_party = "user"
        recipient_line_user_id = None
        recipient_email = None
        if txn.case.user_id is not None:
            owner = await session.get(User, txn.case.user_id)
            if owner is not None:
                recipient_line_user_id = owner.line_user_id
                recipient_email = owner.email
    txn_id_str = str(txn.id)

    try:
        await session.commit()
    except IntegrityError as exc:
        # uq_cancellations_transaction_id（0028）違反を409へ変換する。行ロックにより
        # 通常は到達しないが、変換しないと素通しで500になる（bids.py と同じ多層防御）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="キャンセルできる状態ではありません。",
        ) from exc
    await session.refresh(txn)

    background.add_task(
        notify_dispatch.dispatch_transaction_cancelled,
        recipient_line_user_id,
        recipient_email,
        txn_id_str,
        recipient_party,
    )
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
    background: BackgroundTasks,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    # キャンセル済み・完了済みの取引には発言できない（r8-H3）。従来は 201 を返し、
    # 相手方に「終了済み案件への発言」が届き続けていた。
    _assert_txn_open(txn)

    # sender_type はクライアント入力を受け取らず actor から自動判定する（なりすまし防止）。
    message = Message(
        transaction_id=txn.id,
        sender_type=party,
        sender_id=actor.id,
        body=body.body,
        kind="text",
    )
    session.add(message)

    # 送信者の反対側（受信者）の LINE 宛に新着通知を出す。BackgroundTasks は
    # セッションクローズ後に走るため、commit 前にプリミティブ値へ取り出しておく
    # （detached インスタンスの遅延ロードによる MissingGreenlet を避ける）。
    # txn.case / txn.bid.operator は _TXN_LOAD で eager load 済みだが、
    # case.user_id からの User は未ロードのため明示取得する（PK取得=1クエリ）。
    if party == "operator":
        recipient_party: str = "user"
        recipient_line_user_id: str | None = None
        owner_id = txn.case.user_id
        if owner_id is not None:
            owner = await session.get(User, owner_id)
            recipient_line_user_id = owner.line_user_id if owner is not None else None
    else:
        recipient_party = "operator"
        recipient_line_user_id = txn.bid.operator.line_user_id
    txn_id_str = str(txn.id)

    await session.commit()
    await session.refresh(message)

    if recipient_line_user_id:
        background.add_task(
            notify_dispatch.dispatch_message_received,
            recipient_line_user_id,
            txn_id_str,
            recipient_party,
        )
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
    # 終了済み取引への候補提示を拒否する（r8-H3）。confirm_schedule 側は既に
    # status=="pending" のみ許可しているため、往路（提示）だけが穴になっていた。
    _assert_txn_open(txn)

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
    # 認可（当事者性）はロック取得より前に確認する（r6-verify-fix M1）。
    await _assert_party_before_lock(session, transaction_id, actor)
    # complete / cancel との競合で「キャンセル済みなのに visiting へ戻る」等の
    # 後勝ち上書きを防ぐ（r6-backend M-1。同型の遷移すべてに適用する）。
    await _lock_txn_rows(session, transaction_id)
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

    # 候補日ラベル（例「9月7日（日）10:00〜12:00」）に日付が含まれる場合は ISO 日付を重ねて出さない
    if re.search(r"\d+月\d+日", body.visit_time_slot):
        confirm_body = f"訪問日程が {body.visit_time_slot} に確定しました。"
    else:
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
