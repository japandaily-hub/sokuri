"""成約エンドポイント — 詳細 / 完了 / キャンセル。

住所詳細・連絡先は本エンドポイントでのみ開示する（品質基準）:
- 開示先は「所有ユーザー」と「落札業者」のみ。サーバーサイドで判定する。
"""

from __future__ import annotations

import math

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor
from app.api.rate_limit_deps import RateLimitGuard
from app.core.limits import (
    COMPLETION_REQUEST_COOLDOWN_HOURS,
    MAX_COMPLETION_REQUESTS_PER_TRANSACTION,
    MAX_REDUCTION_REQUESTS_PER_TRANSACTION,
    MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION,
    MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION,
)
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
    ScheduleAcceptRequest,
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
from app.services.visit_schedule import (
    VisitCandidate,
    candidate_label,
    fixed_visit_time_slot_candidate,
    format_visit_label,
    is_candidate_expired,
    latest_visit_date,
    now_jst,
    parse_proposal_meta,
    time_label,
    today_jst,
)

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
# 日程確定済み（visiting）の取引への日程候補の再提示を拒否する 409。confirm_schedule は
# status=="pending" のときのみ日程確定を許可するため、visiting のまま候補を提示し続けても
# 依頼者は確定できない（提示そのものを止める）。TRANSACTION_CLOSED_DETAIL と同じ dict
# detail 方式。
SCHEDULE_ALREADY_CONFIRMED_DETAIL: dict[str, str] = {
    "code": "schedule_already_confirmed",
    "message": "訪問日程は確定済みです。変更が必要な場合はメッセージでご相談ください。",
}
# 開いたままの旧画面からの日程の送信を、何も書き込まずに止める 422（日程構造化 DESIGN §2.1・
# §2.3・§7）。旧 web も dict の detail の message をそのまま表示するため、再読み込みを案内できる。
# 日程まわりの 422 は数値で書く（Starlette 1.x で status.HTTP_422_UNPROCESSABLE_ENTITY が
# 非推奨になり、後継の HTTP_422_UNPROCESSABLE_CONTENT は古い版に無いため）。
SCHEDULE_PROPOSE_CLIENT_OUTDATED_DETAIL: dict[str, str] = {
    "code": "schedule_client_outdated",
    "message": "画面が古いため送信できませんでした。ページを再読み込みしてから、もう一度候補日を送ってください。",
}
SCHEDULE_CONFIRM_CLIENT_OUTDATED_DETAIL: dict[str, str] = {
    "code": "schedule_client_outdated",
    "message": "この画面からは確定できません。ページを再読み込みしてから、もう一度お選びください。",
}
# 業者の提示からの確定（accept）で、選んだ提示・候補では確定できないときの detail
# （日程構造化 DESIGN §2.2）。web は code で理由を出し分け、メッセージと取引を取り直す。
SCHEDULE_PROPOSAL_SUPERSEDED_DETAIL: dict[str, str] = {
    "code": "schedule_proposal_superseded",
    "message": "業者から新しい候補日が届いています。最新の候補からお選びください。",
}
SCHEDULE_CANDIDATE_EXPIRED_DETAIL: dict[str, str] = {
    "code": "schedule_candidate_expired",
    "message": "この候補日は過ぎています。業者に新しい候補を依頼するか、日程調整ページからお選びください。",
}
SCHEDULE_PROPOSAL_LEGACY_DETAIL: dict[str, str] = {
    "code": "schedule_proposal_legacy",
    "message": "この候補は古い形式のため、ここでは確定できません。日程調整ページからお選びください。",
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


def _rate_limit_account_key(actor: Actor) -> str:
    """レート制限のアカウント軸キー（``"{typ}:{id}"``）を組み立てる。

    user と operator は別テーブルの UUID のため、名前空間を付けずに
    ``str(actor.id)`` だけをキーにすると、両テーブル間でUUIDが一致した場合に
    別人同士が同じバケットを共有してしまう（rate_limit_deps._scope_spec の
    docstring にある「識別子自体を名前空間分離すること」と同じ考え方。auth.py の
    login が "user:{email}" / "operator:{email}" で分離しているのと同型）。
    管理者は _assert_party で "user" 側の当事者として通るが、キーは管理者自身の
    User.id になる（依頼者本人のバケットは消費しない）。
    """
    return f"{actor.typ}:{actor.id}"


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
            visit_time_slot=t.visit_time_slot,
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


def _user_side_actor_role(txn: Transaction, actor: Actor) -> Literal["user", "admin"]:
    """依頼者側の操作を誰が行ったか（"user"＝案件の所有者本人 / "admin"＝代理の運営）。

    _assert_party は所有者本人と管理者の両方を "user" として通すため、所有者ではない
    管理者の代理操作を見分ける（完了確定の completed_by・日程確定の confirmed_by・
    代理の日程確定でのひとことの拒否に共通で使う）。_assert_party が "user" を返した後に呼ぶこと。
    """
    assert actor.user is not None
    if actor.user.role == "admin" and txn.case.user_id != actor.user.id:
        return "admin"
    return "user"


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
    # 減額申請の消費回数と上限（r10 V-M4）。reductions.py の 409 判定と
    # 同じ定数（core/limits.py）を返し、web が自前のリテラルを持たないようにする。
    out.reduction_request_count = len(txn.reduction_requests)
    out.reduction_request_limit = MAX_REDUCTION_REQUESTS_PER_TRANSACTION
    # 完了確定の依頼の消費回数・上限・次に依頼できる時刻（r10 V-M4 と同じ考え方）。
    completion_request_count, last_completion_requested_at = await _completion_request_stats(
        session, txn.id
    )
    out.completion_request_count = completion_request_count
    out.completion_request_limit = MAX_COMPLETION_REQUESTS_PER_TRANSACTION
    out.completion_request_available_at = _completion_request_available_at(
        last_completion_requested_at
    )
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


async def _completion_request_stats(
    session: AsyncSession, txn_id: uuid.UUID
) -> tuple[int, datetime | None]:
    """指定取引の完了確定依頼（kind="complete_request"）の件数と最終送信時刻を1クエリで集計する。

    request_completion の 409/429 判定と TransactionDetailOut の3フィールドの
    単一の出所にする（DB（messages）に残るため再起動・複数インスタンスでもすり抜けない）。
    """
    row = (
        await session.execute(
            select(func.count(), func.max(Message.created_at)).where(
                Message.transaction_id == txn_id,
                Message.kind == "complete_request",
            )
        )
    ).one()
    count, last_created_at = row
    return int(count), last_created_at


def _completion_request_available_at(last_requested_at: datetime | None) -> datetime | None:
    """直近の完了確定依頼から COMPLETION_REQUEST_COOLDOWN_HOURS 経過後に依頼可能になる時刻。

    まだクールダウン中なら次に依頼できる時刻を、依頼履歴が無い・経過済みなら None
    （今すぐ依頼できる）を返す。created_at が naive な場合は UTC とみなす
    （SQLite はタイムゾーン情報を保持しないため。cases.py:93 と同じ規約）。
    """
    if last_requested_at is None:
        return None
    if last_requested_at.tzinfo is None:
        last_requested_at = last_requested_at.replace(tzinfo=timezone.utc)
    available_at = last_requested_at + timedelta(hours=COMPLETION_REQUEST_COOLDOWN_HOURS)
    return available_at if available_at > datetime.now(timezone.utc) else None


def _today_jst(now_utc: datetime | None = None) -> date:
    """日本時間での「今日」の日付（実体は services/visit_schedule.today_jst）。

    now_utc を省略すると現在時刻を使うが、テストから固定時刻を注入できるように
    引数化している（monkeypatch で本関数自体を差し替えれば date.today() に依存せず
    日付境界を固定できる。request_completion の訪問日ゲートのテストがこの名前を
    差し替えるため、このモジュールに残す）。
    """
    return today_jst(now_utc)


def _now_jst() -> datetime:
    """日本時間の現在時刻（実体は services/visit_schedule.now_jst）。

    日程の提示・確定の判定（日付の範囲・当日の終わった枠・候補の期限）は、1リクエストで
    この関数を1回だけ呼んで「今」を決める（日付と時刻の判定の間に日付が変わらないように）。
    テストは本関数を monkeypatch して時刻を固定する。
    """
    return now_jst()


@router.post(
    "/transactions/{transaction_id}/complete",
    response_model=TransactionOut,
    summary="成約完了（ユーザーが確定）",
)
async def complete_transaction(
    transaction_id: uuid.UUID,
    background: BackgroundTasks,
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
    final_amount = txn.final_amount
    # _assert_party は「本人」または「admin」を "user" として通す。案件所有者本人
    # ではない管理者が代行確定した場合を監査できるよう meta に記録する（通知文面は
    # どちらでも同一のまま。「誰が確定したか」に依存させない）。
    completed_by = _user_side_actor_role(txn, actor)
    # 完了確定を両当事者のチャットに記録として残す（confirm_schedule の
    # schedule_confirmed と同じ「状態遷移の記録は system 名義」の方針）。
    session.add(
        Message(
            transaction_id=txn.id,
            sender_type="system",
            sender_id=None,
            body=f"作業完了が確定しました（確定額 {final_amount:,} 円）。",
            kind="completed",
            meta={"final_amount": final_amount, "completed_by": completed_by},
        )
    )
    # commit 前にプリミティブ値へ取り出す（detached インスタンスの遅延ロードによる
    # MissingGreenlet を避ける。confirm_schedule と同じ規約）。
    operator_line_user_id = txn.bid.operator.line_user_id
    operator_email = txn.bid.operator.contact_email
    txn_id_str = str(txn.id)
    await session.commit()
    await session.refresh(txn)

    background.add_task(
        notify_dispatch.dispatch_transaction_completed,
        operator_line_user_id,
        operator_email,
        txn_id_str,
        final_amount,
    )
    return TransactionOut.model_validate(txn)


@router.post(
    "/transactions/{transaction_id}/complete/request",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="完了確定の依頼（落札業者のみ・24時間に1回・1取引3回まで）",
)
async def request_completion(
    transaction_id: uuid.UUID,
    background: BackgroundTasks,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    # 認可（当事者性）はロック取得より前に確認する（r6-verify-fix M1 と同じパターン）。
    await _assert_party_before_lock(session, transaction_id, actor)
    # 判定と Message 追加を原子的にするため、他の状態遷移（complete/cancel/
    # confirm_schedule）と同じ行ロックへ参加してから読み直す（連打の直列化）。
    await _lock_txn_rows(session, transaction_id)
    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    if party != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="完了確定の依頼は落札業者のみ行えます。",
        )
    # 終了済み取引への依頼を拒否する（r8-H3 と同じ方針。_assert_txn_open を再利用）。
    _assert_txn_open(txn)
    # 訪問日程の確定（visiting）前は依頼できない。pending のまま依頼を許すと、
    # 依頼者が訪問日も知らないまま「完了確定を」と言われる状態になる。
    if txn.status != "visiting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="訪問日程の確定後に依頼できます。",
        )
    # 訪問予定日より前の依頼は「まだ訪問していないのに完了確定を求める」ことになる。
    if txn.visit_date is not None and txn.visit_date > _today_jst():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"訪問日（{txn.visit_date.month}月{txn.visit_date.day}日）以降に依頼できます。",
        )
    # 依頼者（案件所有者）が利用停止中だと完了確定操作ができず、依頼しても
    # ユーザーから永久に応答されない（r8-M4 と同じ「相手が無応答の理由」対応）。
    # owner はここで取得し、以降の通知（dispatch_completion_requested）でも使い回す。
    owner = await _owner(session, txn)
    if owner is not None and owner.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ユーザーが利用停止中のため、完了確定を依頼できません。運営へお問い合わせください。",
        )
    # 未回答の減額申請を残したまま依頼すると、ユーザーが完了確定した直後に
    # decide_reduction が通って確定額が事後に書き換わる穴になる（complete_transaction
    # の pending 減額ガードと同じ理由）。
    if any(r.status == "pending" for r in txn.reduction_requests):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="減額申請への回答待ちのため、完了確定を依頼できません。ユーザーの回答後にお試しください。",
        )

    request_count, last_requested_at = await _completion_request_stats(session, txn.id)
    if request_count >= MAX_COMPLETION_REQUESTS_PER_TRANSACTION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"完了確定の依頼は1取引につき{MAX_COMPLETION_REQUESTS_PER_TRANSACTION}回までです。"
                "ユーザーから確定がない場合は運営へお問い合わせください。"
            ),
        )
    available_at = _completion_request_available_at(last_requested_at)
    if available_at is not None:
        retry_after_seconds = max(
            math.ceil((available_at - datetime.now(timezone.utc)).total_seconds()), 1
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"完了確定の依頼は{COMPLETION_REQUEST_COOLDOWN_HOURS}時間に1回までです。"
                "時間をおいて再度お試しください。"
            ),
            headers={"Retry-After": str(retry_after_seconds)},
        )

    # 業者名義（押した業者本人）で送る。依頼者の未読数（_count_unread は相手側
    # sender_type のみ数える）に乗るため「業者とチャット（未読1）」でも気づける。
    # 相手に行動を求める要求は行為者名義（schedule_proposal と同じ）、状態遷移の記録は system 名義。
    message = Message(
        transaction_id=txn.id,
        sender_type="operator",
        sender_id=actor.id,
        body=(
            "作業完了の確定をお願いします。引き取りが済んでいれば、"
            "マイ案件の「作業完了を確定する」から確定してください。"
        ),
        kind="complete_request",
        meta=None,
    )
    session.add(message)

    owner_line_user_id = owner.line_user_id if owner is not None else None
    owner_email = owner.email if owner is not None else None
    case_id_str = str(txn.case_id)

    await session.commit()
    await session.refresh(message)

    background.add_task(
        notify_dispatch.dispatch_completion_requested,
        owner_line_user_id,
        owner_email,
        case_id_str,
    )
    return _to_message_out(message, party)


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
    # 運営（所有者ではない管理者）による依頼者名義のキャンセルは拒否する（security review
    # L-5）。_assert_party は管理者を "user" として通すため、そのままでは cancelled_by="user"
    # として記録され、入力した理由が依頼者本人の理由として相手方（業者）の取引詳細に
    # 表示されてしまう。運営は cancelled_by="admin" を記録する強制終了
    # （PATCH /admin/transactions/{id}/cancel）を使う。
    if party == "user" and _user_side_actor_role(txn, actor) == "admin":
        logger.warning(
            "transactions: 運営による依頼者名義のキャンセルを拒否 - transaction_id=%s admin_id=%s",
            txn.id,
            actor.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="運営はこの操作を代理で行えません。強制終了を使ってください。",
        )
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


async def _count_messages(
    session: AsyncSession,
    txn_id: uuid.UUID,
    *,
    kind: str,
    sender_type: str | None = None,
) -> int:
    """当該取引のメッセージ件数を **1クエリ**で数える（``_count_unread`` と同型）。

    ``ix_messages_transaction_id_created_at`` の先頭列（transaction_id）で当該
    取引だけを走査するため、取引数が積み上がってもこのクエリ自体のコストは
    増えない（提示・通常発言とも上限があるため走査行数自体も頭打ちになる）。
    """
    stmt = select(func.count()).select_from(Message).where(
        Message.transaction_id == txn_id, Message.kind == kind
    )
    if sender_type is not None:
        stmt = stmt.where(Message.sender_type == sender_type)
    count = await session.scalar(stmt)
    return int(count or 0)


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
    # 応答件数は MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION（当事者ごと）×2 ＋
    # MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION ＋少数のシステムメッセージで頭打ちになる
    # （L-4）。将来ページングを入れる場合、after は created_at の厳密な > 比較で、
    # 同じ DB トランザクション内で作られた行は created_at が同じになり得るため、
    # 件数で途中を切ると取りこぼす（(created_at, id) の複合カーソルが要る）。
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
    request: Request,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("message_send")),
) -> MessageOut:
    # コストDoS対策のレート制限（アカウント軸のみ・全取引合計）。重い _get_txn より
    # 前に数える（cases.cancel_case と同じ方式。成功・失敗を問わずハンドラ冒頭で
    # 毎回カウントする）。
    request.state.rate_limit.hit_account(_rate_limit_account_key(actor))

    txn = await _get_txn(session, transaction_id)
    party = _assert_party(txn, actor)
    # 運営（所有者ではない管理者）の代理発言は拒否する（pdca admin H-2）。_assert_party は
    # 管理者を "user" として通すため、そのまま保存すると業者に「依頼者本人の発言」として
    # 見えてしまう（なりすまし）。確定・完了の代理実行は confirmed_by / completed_by で
    # 記録されるため許可を残し、チャットだけを閲覧専用にする。
    if party == "user" and _user_side_actor_role(txn, actor) == "admin":
        logger.warning(
            "messages: 運営による代理発言を拒否 - transaction_id=%s admin_id=%s",
            txn.id,
            actor.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="運営はチャットを代理で送信できません。",
        )
    # キャンセル済み・完了済みの取引には発言できない（r8-H3）。従来は 201 を返し、
    # 相手方に「終了済み案件への発言」が届き続けていた。
    _assert_txn_open(txn)

    # 1取引・当事者（sender_type）ごとの送信件数上限（L-4）。数える単位は
    # アカウントではなく sender_type のため、管理者が "user" 側として送った発言も
    # 依頼者側の件数に入る（_assert_party の既存の扱い）。行ロックは取らない
    # （チャットに行ロック待ちを持ち込まないため）。同時送信では上限を超えうるが、
    # 超過は「同時に COUNT〜COMMIT の間にいられる件数」＝DB 接続プール
    # （db_pool_size+db_max_overflow、既定 5+5=10）で頭打ちになり、1インスタンス
    # あたり最大でも +9 件（レート制限の窓内バーストの方が大きいので、効いているのは
    # プール）。利用者が書き込める kind（画像など）を増やすときは、この件数と
    # list_messages の天井に含めること。
    existing_count = await _count_messages(session, txn.id, kind="text", sender_type=party)
    if existing_count >= MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION:
        by_admin = actor.typ == "user" and actor.user is not None and actor.user.role == "admin"
        logger.warning(
            "messages: 送信上限に到達 - transaction_id=%s party=%s by_admin=%s count=%d limit=%d",
            txn.id,
            party,
            by_admin,
            existing_count,
            MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この取引で送れるメッセージの上限に達しました。運営へお問い合わせください。",
        )

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
    recipient_email: str | None = None
    recipient_email_opt_in = True
    if party == "operator":
        recipient_party: str = "user"
        recipient_line_user_id: str | None = None
        owner_id = txn.case.user_id
        if owner_id is not None:
            owner = await session.get(User, owner_id)
            if owner is not None:
                recipient_line_user_id = owner.line_user_id
                # メール通知（LINE 未連携の依頼者向け・pdca seller 高#5）。退会済み・停止中の
                # 依頼者には送らない（退会済みは墓標メールでも is_placeholder_email が弾くが多層防御）。
                if owner.deleted_at is None and not owner.is_suspended:
                    recipient_email = owner.email
                    recipient_email_opt_in = owner.email_notify_opt_in
    else:
        recipient_party = "operator"
        recipient_line_user_id = txn.bid.operator.line_user_id
    txn_id_str = str(txn.id)

    await session.commit()
    await session.refresh(message)

    if recipient_line_user_id or recipient_email:
        background.add_task(
            notify_dispatch.dispatch_message_received,
            recipient_line_user_id,
            txn_id_str,
            recipient_party,
            email=recipient_email,
            email_notify_opt_in=recipient_email_opt_in,
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

    # 運営（所有者ではない管理者）の閲覧では既読にしない（pdca admin H-2）。依頼者本人が
    # まだ読んでいない新着の未読バッジが、運営の確認で消えてしまうため。
    if party == "user" and _user_side_actor_role(txn, actor) == "admin":
        return TransactionOut.model_validate(txn)

    now = datetime.now(timezone.utc)
    if party == "user":
        txn.user_last_read_at = now
    else:
        txn.operator_last_read_at = now
    await session.commit()
    await session.refresh(txn)
    return TransactionOut.model_validate(txn)


# ──────────────────────────── 日程調整 ────────────────────────────

# 同一取引への候補提示の通知間隔。業者が短時間に何度も提示し直すたびに
# 依頼者へ通知が飛ぶと迷惑になるため、直近にこの間隔内の提示が無いときだけ通知する
# （DB基準・判定は propose_schedule 内で行う）。
_SCHEDULE_PROPOSAL_NOTIFY_INTERVAL = timedelta(minutes=5)
# 同一取引への候補提示の通知回数上限。これ以上は「またか」の通知疲れになるため、
# 提示そのものは拒否せず通知だけ止める（既存 API の挙動は変えない）。
_SCHEDULE_PROPOSAL_NOTIFY_MAX = 3


async def _schedule_proposal_stats(
    session: AsyncSession, txn_id: uuid.UUID
) -> tuple[int, datetime | None]:
    """指定取引の日程候補提示（kind="schedule_proposal"）の件数と最終提示時刻を1クエリで集計する。

    _completion_request_stats と同じ形（1回の集計クエリで件数・上限判定・間隔判定の
    両方に使う値を取る）。
    """
    row = (
        await session.execute(
            select(func.count(), func.max(Message.created_at)).where(
                Message.transaction_id == txn_id,
                Message.kind == "schedule_proposal",
            )
        )
    ).one()
    count, last_created_at = row
    return int(count), last_created_at


def _is_within_schedule_proposal_notify_interval(last_proposed_at: datetime | None) -> bool:
    """直近の候補提示が通知の抑止間隔内（既定5分）に収まっているか。

    created_at が naive な場合は UTC とみなす（SQLite 対策。
    _completion_request_available_at と同じ規約）。
    """
    if last_proposed_at is None:
        return False
    if last_proposed_at.tzinfo is None:
        last_proposed_at = last_proposed_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_proposed_at < _SCHEDULE_PROPOSAL_NOTIFY_INTERVAL


async def _latest_schedule_proposal_seq(session: AsyncSession, txn_id: uuid.UUID) -> int:
    """指定取引の提示の seq の最大値（v2 の提示が無ければ 0）を1クエリで求める
    （日程構造化 DESIGN §4・§13.3）。

    「最新の提示」は件数や created_at ではなく seq の最大値で判定する（created_at は
    PostgreSQL ではトランザクション開始時刻のため、ロック待ちで提示の順と逆転しうる。
    件数は将来メッセージを削除できるようになると採番と食い違う）。seq を持たない v1 の
    提示（meta.slots だけ）は集計で NULL として無視される。PostgreSQL では
    COALESCE(MAX(CAST(messages.meta ->> 'seq' AS INTEGER)), 0) になり、走査は
    messages.transaction_id の索引で当該取引の行に限られる。呼び出し元は取引の行ロックを
    持っていること（propose の採番と accept の最新判定を直列化する）。
    """
    latest_seq = await session.scalar(
        select(func.coalesce(func.max(Message.meta["seq"].as_integer()), 0)).where(
            Message.transaction_id == txn_id,
            Message.kind == "schedule_proposal",
        )
    )
    return int(latest_seq or 0)


def _assert_proposal_candidates_acceptable(
    candidates: list[VisitCandidate], now: datetime
) -> None:
    """提示する候補の意味の検証（日程構造化 DESIGN §13.3。日付範囲 → 当日の終わった枠 → 重複の順）。

    正規の画面でも踏みうる検証のため、画面に出せる文字列の detail で 422 を返す
    （Pydantic の配列形式の detail は画面で汎用文言になる）。日付は日本時間で判定する。
    """
    today = today_jst(now)
    last_day = latest_visit_date(today)
    if any(not today <= candidate.date <= last_day for candidate in candidates):
        raise HTTPException(
            status_code=422,
            detail="候補日は本日（日本時間）から1年以内の日付を選んでください。",
        )
    if any(is_candidate_expired(candidate, now) for candidate in candidates):
        raise HTTPException(status_code=422, detail="終わった時間帯は候補にできません。")
    # VisitCandidate は (date, start, end) で等価・ハッシュ可能な frozen dataclass。
    if len(set(candidates)) != len(candidates):
        raise HTTPException(
            status_code=422, detail="同じ日付・時間帯の候補が重複しています。"
        )


@router.post(
    "/transactions/{transaction_id}/schedule/propose",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="訪問日程の候補提示（落札業者のみ）",
)
async def propose_schedule(
    transaction_id: uuid.UUID,
    body: ScheduleProposeRequest,
    background: BackgroundTasks,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("schedule_propose")),
) -> MessageOut:
    # コストDoS対策のレート制限（アカウント軸のみ・全取引合計）。重い _get_txn より
    # 前に数える（cases.cancel_case と同じ方式。成功・失敗を問わずハンドラ冒頭で
    # 毎回カウントする）。
    request.state.rate_limit.hit_account(_rate_limit_account_key(actor))

    # 認可（当事者性）はロック取得より前に確認する（r6-verify-fix M1 と同じパターン）。
    await _assert_party_before_lock(session, transaction_id, actor)
    # 通知件数・間隔の判定と seq の採番を、他の同時提示・候補からの確定（accept）と
    # 直列化する（request_completion と同じ順序）。
    await _lock_txn_rows(session, transaction_id)
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
    # 日程確定済み（visiting）への再提示も拒否する。confirm_schedule は
    # status=="pending" のときのみ確定を許可するため、visiting のまま候補を
    # 提示し続けても依頼者は確定できず「選ぶと日程が確定します」が事実と違う。
    # これにより以降は必ず pending のみ到達するため、通知条件に status を含める
    # 必要はない。
    if txn.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=SCHEDULE_ALREADY_CONFIRMED_DETAIL
        )
    # 開いたままの旧タブ（自由記述の {"slots": [...]}）からの送信は何も書き込まず、
    # 再読み込みを促す（日程構造化 DESIGN §2.1・§7）。件数を Render のログで数え、7日連続で
    # 0件になったら旧形式の判定を片付ける。業者の自由記述（ラベル本文）はログに出さない。
    if body.candidates is None:
        logger.warning(
            "schedule.legacy_client path=propose transaction_id=%s operator_id=%s",
            txn.id,
            actor.id,
        )
        raise HTTPException(status_code=422, detail=SCHEDULE_PROPOSE_CLIENT_OUTDATED_DETAIL)
    candidates = [
        VisitCandidate(date=candidate.date, start=candidate.start, end=candidate.end)
        for candidate in body.candidates
    ]
    _assert_proposal_candidates_acceptable(candidates, _now_jst())

    # Message 追加前に判定する（追加後だと今回分が常に1件以上ヒットし、通知が
    # 永久に抑止されてしまう）。
    proposal_count, last_proposed_at = await _schedule_proposal_stats(session, txn.id)
    should_notify = (
        # 既に上限件数以上を提示済みなら、これ以上の通知は疲れさせるだけ。
        proposal_count < _SCHEDULE_PROPOSAL_NOTIFY_MAX
        # 直近の抑止間隔内の提示があれば送らない（既存の5分抑止）。
        and not _is_within_schedule_proposal_notify_interval(last_proposed_at)
    )
    seq = await _latest_schedule_proposal_seq(session, txn.id) + 1

    # 1取引あたりの提示回数上限（L-4）。依頼者は最新の提示か日程調整ページ
    # （固定の時間帯）から確定できるので取引は止まらない。提示メッセージの行数の天井になる。
    # 上の _lock_txn_rows で取引の行を直列化しているため、同時提示でも上限は超えない。
    existing_count = await _count_messages(session, txn.id, kind="schedule_proposal")
    if existing_count >= MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION:
        logger.warning(
            "schedule_propose: 提示上限に到達 - transaction_id=%s party=%s count=%d limit=%d",
            txn.id,
            party,
            existing_count,
            MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"日程候補の提示は1取引につき{MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION}"
                "回までです。調整はメッセージでご相談ください。"
            ),
        )

    message = Message(
        transaction_id=txn.id,
        sender_type="operator",
        sender_id=actor.id,
        body=f"訪問日程の候補を{len(candidates)}件提示しました。",
        kind="schedule_proposal",
        # 表示（label）はサーバーだけが作る（日程構造化 DESIGN §3）。v2 に slots は持たせない
        # （保存した重複データは消せず、将来ラベルを再解析する入口になるため）。
        meta={
            "v": 2,
            "seq": seq,
            "candidates": [
                {
                    "date": candidate.date.isoformat(),
                    "start": candidate.start,
                    "end": candidate.end,
                    "label": candidate_label(candidate),
                }
                for candidate in candidates
            ],
        },
    )
    session.add(message)

    owner_line_user_id: str | None = None
    owner_email: str | None = None
    owner_email_opt_in = True
    should_dispatch = False
    if should_notify:
        owner = await _owner(session, txn)
        if owner is not None:
            owner_line_user_id = owner.line_user_id
            owner_email = owner.email if owner.deleted_at is None else None
            owner_email_opt_in = owner.email_notify_opt_in
            should_dispatch = True
    txn_id_str = str(txn.id)

    await session.commit()
    await session.refresh(message)

    if should_dispatch:
        background.add_task(
            notify_dispatch.dispatch_schedule_proposed,
            owner_line_user_id,
            owner_email,
            txn_id_str,
            owner_email_opt_in,
        )
    return _to_message_out(message, party)


@router.post(
    "/transactions/{transaction_id}/schedule/proposals/{proposal_id}/accept",
    response_model=TransactionOut,
    summary="業者が提示した候補での訪問日程の確定（所有ユーザーのみ・最新の提示のみ）",
)
async def accept_schedule_proposal(
    transaction_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ScheduleAcceptRequest,
    background: BackgroundTasks,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("schedule_accept")),
) -> TransactionOut:
    # コストDoS対策のレート制限（アカウント軸のみ・全取引合計。propose と同じ方式）。
    request.state.rate_limit.hit_account(_rate_limit_account_key(actor))

    # 認可（当事者性）はロック取得より前に確認する（r6-verify-fix M1）。
    await _assert_party_before_lock(session, transaction_id, actor)
    # 提示（propose）・完了・キャンセルと同じ行ロックで直列化する。propose と同時に押されても、
    # 結果は「確定して、後から来た提示は 409」か「新しい提示が先に入り、この確定は
    # superseded の 409」のどちらか一方に必ず決まる（日程構造化 DESIGN §4）。
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
    # 提示は id・取引・種別の3条件で1行だけ引く（他の取引の提示や通常のメッセージの id を
    # 渡されても確定に使わない＝IDOR 防止。ロックを持ったまま全提示を読み込まない）。
    proposal = await session.scalar(
        select(Message).where(
            Message.id == proposal_id,
            Message.transaction_id == txn.id,
            Message.kind == "schedule_proposal",
        )
    )
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="候補日の提示が見つかりません。ページを再読み込みしてください。",
        )
    parsed = parse_proposal_meta(proposal.meta)
    if parsed.version != "v2":
        # v1（業者の自由記述だけの旧形式）は解析せず、日程調整ページへ案内する。
        # 構造化の反映前に本番でできた提示の残り具合を数えるため件数をログに残す。
        logger.warning(
            "schedule.legacy_proposal path=accept transaction_id=%s proposal_id=%s version=%s",
            txn.id,
            proposal.id,
            parsed.version,
        )
        raise HTTPException(status_code=422, detail=SCHEDULE_PROPOSAL_LEGACY_DETAIL)
    # 確定できるのは最新の提示だけ（ユーザー決定 2026-09-27）。最新は seq の最大値で判定する。
    if parsed.seq != await _latest_schedule_proposal_seq(session, txn.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=SCHEDULE_PROPOSAL_SUPERSEDED_DETAIL
        )
    if body.candidate_index >= len(parsed.candidates):
        raise HTTPException(
            status_code=422, detail="候補が見つかりません。ページを再読み込みしてください。"
        )
    candidate = parsed.candidates[body.candidate_index]
    if is_candidate_expired(candidate, _now_jst()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=SCHEDULE_CANDIDATE_EXPIRED_DETAIL
        )
    return await _apply_schedule_confirmation(
        session,
        background,
        txn,
        actor,
        candidate,
        source_meta={
            "source": "proposal",
            "proposal_id": str(proposal.id),
            "candidate_index": body.candidate_index,
        },
        note_text="",
    )


@router.post(
    "/transactions/{transaction_id}/schedule/confirm",
    response_model=TransactionOut,
    summary="訪問日程の確定（日程調整ページ専用・所有ユーザーのみ）",
)
async def confirm_schedule(
    transaction_id: uuid.UUID,
    body: ScheduleConfirmRequest,
    background: BackgroundTasks,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("schedule_accept")),
) -> TransactionOut:
    # 検証エラーの連打で自分の取引の行ロックを取り続け、業者の propose や cancel を待たせるのを防ぐ
    # （security review L-1）。accept と同じ「日程の確定」の枠を共有する（アカウント軸のみ）。
    request.state.rate_limit.hit_account(_rate_limit_account_key(actor))

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
    # 日程調整ページ（/schedule）の固定5種だけを受け付ける。旧依頼者タブが業者の候補ラベルで
    # 確定する等の固定5種以外は、何も書き込まず再読み込みを促す（日程構造化 DESIGN §2.3・§7）。
    # 送られてきた値（任意の文字列）はログに出さない。
    candidate = fixed_visit_time_slot_candidate(body.visit_date, body.visit_time_slot)
    if candidate is None:
        logger.warning(
            "schedule.legacy_client path=confirm transaction_id=%s user_id=%s",
            txn.id,
            actor.id,
        )
        raise HTTPException(status_code=422, detail=SCHEDULE_CONFIRM_CLIENT_OUTDATED_DETAIL)
    now = _now_jst()
    today = today_jst(now)
    if body.visit_date < today:
        raise HTTPException(status_code=422, detail="訪問日は本日以降を指定してください。")
    if body.visit_date > latest_visit_date(today):
        raise HTTPException(status_code=422, detail="訪問日は1年以内で指定してください。")
    if is_candidate_expired(candidate, now):
        raise HTTPException(
            status_code=422,
            detail="終わった時間帯は選べません。別の時間帯か日付をお選びください。",
        )
    note_text = body.note.strip() if body.note is not None else ""
    # 運営の代理の確定ではひとことを受け付けない（依頼者本人の発言として保存されてしまうため。
    # 日程検証レビュー SEC-I7）。空白だけのひとことはメッセージにならないため拒否しない。
    if note_text and _user_side_actor_role(txn, actor) == "admin":
        raise HTTPException(
            status_code=422, detail="運営による代理の確定では、ひとことは送れません。"
        )
    return await _apply_schedule_confirmation(
        session,
        background,
        txn,
        actor,
        candidate,
        source_meta={"source": "calendar"},
        note_text=note_text,
    )


async def _apply_schedule_confirmation(
    session: AsyncSession,
    background: BackgroundTasks,
    txn: Transaction,
    actor: Actor,
    candidate: VisitCandidate,
    *,
    source_meta: dict[str, str | int],
    note_text: str,
) -> TransactionOut:
    """訪問日程を確定する（accept と confirm の共通の状態遷移。日程構造化 DESIGN §3・§4）。

    呼び出し元が行ロック・当事者・状態・入力の判定を済ませていること。visit_date・
    visit_time_slot（時刻だけの表示＝固定5種と同じ書式）・確定メッセージの本文は、どれも
    サーバーが構造化データから作る（業者の自由記述も依頼者のひとことも本文に連結しない）。
    note_text は前後の空白を除いた依頼者本人のひとこと（無ければ空文字）。
    """
    visit_time_slot = time_label(candidate.start, candidate.end)
    label = format_visit_label(candidate.date, visit_time_slot)
    txn.visit_date = candidate.date
    txn.visit_time_slot = visit_time_slot
    txn.status = "visiting"
    confirmed_message = Message(
        transaction_id=txn.id,
        sender_type="system",
        sender_id=None,
        body=f"訪問日程が {label} に確定しました。",
        kind="schedule_confirmed",
        meta={
            "v": 2,
            **source_meta,
            "visit_date": candidate.date.isoformat(),
            "visit_time_slot": visit_time_slot,
            "label": label,
            # 完了確定の completed_by と同じ判定（所有者でない管理者の代理なら "admin"）。
            "confirmed_by": _user_side_actor_role(txn, actor),
        },
    )
    session.add(confirmed_message)

    # commit 前にプリミティブ値へ取り出す（detached インスタンスの遅延ロードによる
    # MissingGreenlet を避ける。下の flush より前に読む）。
    operator_email = txn.bid.operator.contact_email
    operator_line_user_id = txn.bid.operator.line_user_id
    txn_id_str = str(txn.id)
    visit_date_str = candidate.date.isoformat()

    # note（業者へのひとこと）は運営名義のシステムメッセージ本文に連結しない。
    # schedule_confirmed はチャット上で運営名義（アバター表示「運」・
    # white-space: pre-wrap）として表示されるため、依頼者の自由記述をそのまま
    # 連結すると運営のお知らせを装った文面を作れてしまう
    # （2026-09-25 セキュリティレビュー Low 対応）。依頼者本人の発言として
    # 別メッセージに分離する。
    if note_text:
        # created_at は TimestampMixin の server_default=func.now()（PostgreSQL では
        # トランザクション開始時刻・テストの SQLite は秒精度）で決まるため、同一
        # トランザクション内で追加した2件は同時刻になり、list_messages の
        # created_at 昇順では並び順が定まらない。confirmed_message を先に flush して
        # DB が払い出した created_at を読み取り、note メッセージにはその
        # 1マイクロ秒後を明示することで「確定→ひとこと」の順を固定する
        # （アプリ側の時計 datetime.now() は使わない。DB時計とのずれで
        # list_messages の after= 差分ポーリングから漏れ得るため）。
        await session.flush()
        await session.refresh(confirmed_message, attribute_names=["created_at"])
        session.add(
            Message(
                transaction_id=txn.id,
                sender_type="user",
                sender_id=actor.id,
                body=note_text,
                kind="text",
                created_at=confirmed_message.created_at + timedelta(microseconds=1),
            )
        )
        # LINE・メールの日程確定通知（dispatch_schedule_confirmed）は訪問日と
        # 取引URLだけを送り、note は含まない（services/line_notify.py の
        # push_schedule_confirmed・services/notify.py の send_schedule_confirmed
        # 参照）。業者はその通知から開くチャットで note を読む（本対応前も note は
        # schedule_confirmed の確定メッセージ内にあり、同じくチャットで読む経路
        # だった点は変わらない）。そのため新着メッセージ通知
        # （dispatch_message_received）は重ねて送らない。

    await session.commit()
    await session.refresh(txn)

    background.add_task(
        notify_dispatch.dispatch_schedule_confirmed,
        operator_line_user_id,
        operator_email,
        txn_id_str,
        visit_date_str,
    )
    return TransactionOut.model_validate(txn)
