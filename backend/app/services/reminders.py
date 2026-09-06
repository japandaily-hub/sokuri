"""リマインド定期処理（r12 決定3）— 訪問日超過 / 入札ゼロ放置の掘り起こし。

``main.py`` の lifespan が 1 時間毎に :func:`run_reminders` を呼ぶほか、
``POST /admin/jobs/reminders`` から手動実行できる。どちらの経路でも実体は同じ関数で、
送信済み判定は DB 列（``transactions.overdue_reminded_at`` / ``cases.no_bid_reminded_at``）
だけに集約する（alembic 0033）。メモリ上の台帳を使わないため、再デプロイ・複数
インスタンス・手動実行が混ざっても同一の成約・案件へ二重に通知が飛ばない。

送信フロー（r12-review H-2 / M-5）:
1. ``UPDATE ... WHERE reminded_at IS NULL ... RETURNING id`` で **先に確保（claim）** する。
   SELECT→通知→末尾 commit だと、同時に走った2周（スケールアウト・手動実行と定期
   ループの重なり）が同じ行を掴んで二重送信しうる。UPDATE は行ロックを取り、
   ``reminded_at IS NULL`` を更新時点で再評価するため、確保できるのは常に一方だけ。
2. **claim を commit してから通知する**。外部 HTTP（LINE / SMTP）を DB
   トランザクション内で待たない（接続をプールへ即返す）。
3. 通知が失敗しても **再送しない**（マーカーは既に立っている）。ログと運営アラート
   （warning）に落とすだけに留める。二重送信の害（同じ催促が何通も飛ぶ）の方が、
   1通の取りこぼしより大きいという判断。運用上の再送は admin で列を戻して行う。

対象抽出の計算量:
- どちらの抽出も「未リマインド行だけを対象にする部分索引」
  （``ix_transactions_overdue_reminder`` / ``ix_cases_no_bid_reminder``）に乗る。
  送信済みの行が何万件積み上がっても走査対象は増えない。
- さらに **遡り窓**（:data:`REMINDER_LOOKBACK_DAYS`）と :data:`REMINDER_BATCH_LIMIT`
  で1周あたりの上限を固定する。列を追加した直後や長期停止からの復帰で「過去の
  該当行すべて」へ一斉通知が飛ぶ事故を防ぐ（r12-review H-1。0033 側でも既存行を
  既送信扱いに埋めてある＝二重の歯止め）。
- 通知の宛先（依頼者）はループ内で1件ずつ引かず、``user_id`` をまとめて
  ``IN (...)`` で1回だけ引く（N+1 の回避）。業者側は ``selectinload`` で
  ``Transaction.bid -> Bid.operator`` を先読みする。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.bid import BID_STATUS_WITHDRAWN, Bid
from app.db.models.case import Case
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.services import alerts, notify_dispatch

logger = logging.getLogger(__name__)

#: 日本時間。訪問日（``transactions.visit_date``）は日本のユーザーが日本の暦で
#: 指定した日付のため、「今日」の判定は UTC ではなく JST で行う（UTC 判定だと
#: 日本の 0:00〜9:00 の間だけ1日ズレたリマインドが飛ぶ）。
JST = timezone(timedelta(hours=9), name="Asia/Tokyo")

#: 訪問日超過リマインドの対象とする成約ステータス（= 訪問予定が生きている状態）。
#: "completed" / "cancelled" は終端でリマインドの意味が無い。日程確定で
#: "visiting" になるため実質は visiting だが、``visit_date`` が入ったまま
#: 別状態へ戻された行も拾えるよう "pending" も含める。
SCHEDULED_TXN_STATUSES: tuple[str, ...] = ("pending", "visiting")

#: 入札ゼロ放置とみなすまでの日数（案件作成からの経過）。
NO_BID_GRACE_DAYS = 3

#: 掘り起こしの遡り上限（日）。これより古い放置は「今さら催促しても意味が無い」
#: ものとして対象外にする。窓が無いと、機能追加直後や長期停止からの復帰時に
#: サービス開始以来の全該当行へ一斉通知が飛ぶ（r12-review H-1）。
REMINDER_LOOKBACK_DAYS = 14

#: 1周で確保・通知する上限件数。外部 API（LINE / SMTP）へ一度に投げる量を抑え、
#: 失敗時の影響範囲も1周分に閉じ込める。積み残しは次の周期で処理される。
REMINDER_BATCH_LIMIT = 200


async def _run_overdue_visit_reminders(session: AsyncSession, now: datetime) -> int:
    """(a) 訪問予定日を過ぎたまま完了確定されていない成約を掘り起こす。

    Returns:
        確保（= 送信済みマーカーを立てた）成約の件数。
    """
    today_jst = now.astimezone(JST).date()
    oldest_visit_date = today_jst - timedelta(days=REMINDER_LOOKBACK_DAYS)
    candidates = (
        select(Transaction.id)
        .where(
            Transaction.overdue_reminded_at.is_(None),
            Transaction.status.in_(SCHEDULED_TXN_STATUSES),
            Transaction.visit_date.is_not(None),
            # JST の「今日」は対象外（当日中の完了確定を待つ）。前日以前だけを拾う。
            Transaction.visit_date < today_jst,
            Transaction.visit_date >= oldest_visit_date,
        )
        .order_by(Transaction.visit_date.asc())
        .limit(REMINDER_BATCH_LIMIT)
    )
    # 外側の WHERE にも overdue_reminded_at IS NULL を残すのが要点。副問い合わせは
    # スナップショット時点の候補集合でしかなく、同時実行の相手が先にマークした行を
    # 含みうるため、UPDATE 時点の再評価で確実に弾く（PostgreSQL の READ COMMITTED
    # では行ロック解放後に WHERE が再評価される）。
    claimed_ids = (
        (
            await session.execute(
                update(Transaction)
                .where(
                    Transaction.overdue_reminded_at.is_(None),
                    Transaction.id.in_(candidates),
                )
                .values(overdue_reminded_at=now)
                .returning(Transaction.id)
                .execution_options(synchronize_session=False)
            )
        )
        .scalars()
        .all()
    )
    await session.commit()
    if not claimed_ids:
        return 0

    targets = await _load_overdue_targets(session, claimed_ids)
    for line_user_id, email, transaction_id, recipient_party in targets:
        await _dispatch_or_warn(
            notify_dispatch.dispatch_visit_overdue,
            line_user_id,
            email,
            transaction_id,
            recipient_party,
            context=f"visit_overdue transaction_id={transaction_id} party={recipient_party}",
        )
    return len(claimed_ids)


async def _load_overdue_targets(
    session: AsyncSession, transaction_ids: Sequence[uuid.UUID]
) -> list[tuple[str | None, str | None, str, str]]:
    """確保済みの成約から通知先をプリミティブ値で取り出し、読み取りTxを閉じる。

    ORM インスタンスを通知処理へ持ち込まない（外部 HTTP の待機中に遅延ロードが
    走らないようにする）。戻り値は ``(line_user_id, email, transaction_id, party)``。
    """
    transactions = (
        await session.scalars(
            select(Transaction)
            .where(Transaction.id.in_(transaction_ids))
            .options(
                selectinload(Transaction.case),
                selectinload(Transaction.bid).selectinload(Bid.operator),
            )
            .order_by(Transaction.visit_date.asc())
        )
    ).all()
    owners = await _load_owners(
        session, [t.case.user_id for t in transactions if t.case is not None]
    )

    targets: list[tuple[str | None, str | None, str, str]] = []
    for txn in transactions:
        transaction_id = str(txn.id)
        case = txn.case
        owner = (
            owners.get(case.user_id)
            if case is not None and case.user_id is not None
            else None
        )
        if owner is not None and _is_reachable_user(owner):
            targets.append((owner.line_user_id, owner.email, transaction_id, "user"))
        operator = txn.bid.operator if txn.bid is not None else None
        if operator is not None and not operator.is_suspended and operator.deleted_at is None:
            targets.append(
                (operator.line_user_id, operator.contact_email, transaction_id, "operator")
            )
    # 通知（外部 HTTP）はトランザクション外で行う（r12-review M-5）。SELECT が
    # 開いた暗黙のトランザクションをここで閉じ、接続をプールへ返す。
    await session.commit()
    return targets


async def _run_no_bid_reminders(session: AsyncSession, now: datetime) -> int:
    """(b) 作成から一定日数、入札が1件も付かないまま open の案件を掘り起こす。

    Returns:
        確保（= 送信済みマーカーを立てた）案件の件数。
    """
    newest_created_at = now - timedelta(days=NO_BID_GRACE_DAYS)
    oldest_created_at = now - timedelta(days=NO_BID_GRACE_DAYS + REMINDER_LOOKBACK_DAYS)
    # 取り下げ済み（レガシー withdrawn）は「入札あり」として数えない。依頼者から
    # 見えている件数（_to_case_out の bid_count）と同じ集合で判定する。
    has_bid = (
        select(Bid.id)
        .where(Bid.case_id == Case.id, Bid.status != BID_STATUS_WITHDRAWN)
        .exists()
    )
    candidates = (
        select(Case.id)
        .where(
            Case.no_bid_reminded_at.is_(None),
            Case.status == "open",
            Case.created_at < newest_created_at,
            Case.created_at >= oldest_created_at,
            Case.user_id.is_not(None),
            ~has_bid,
        )
        .order_by(Case.created_at.asc())
        .limit(REMINDER_BATCH_LIMIT)
    )
    claimed_ids = (
        (
            await session.execute(
                update(Case)
                .where(Case.no_bid_reminded_at.is_(None), Case.id.in_(candidates))
                .values(no_bid_reminded_at=now)
                .returning(Case.id)
                .execution_options(synchronize_session=False)
            )
        )
        .scalars()
        .all()
    )
    await session.commit()
    if not claimed_ids:
        return 0

    targets = await _load_no_bid_targets(session, claimed_ids)
    for line_user_id, email, case_id in targets:
        await _dispatch_or_warn(
            notify_dispatch.dispatch_no_bid_reminder,
            line_user_id,
            email,
            case_id,
            context=f"no_bid case_id={case_id}",
        )
    return len(claimed_ids)


async def _load_no_bid_targets(
    session: AsyncSession, case_ids: Sequence[uuid.UUID]
) -> list[tuple[str | None, str | None, str]]:
    """確保済みの案件から依頼者の通知先を取り出し、読み取りTxを閉じる。"""
    cases = (
        await session.scalars(
            select(Case).where(Case.id.in_(case_ids)).order_by(Case.created_at.asc())
        )
    ).all()
    owners = await _load_owners(session, [c.user_id for c in cases])

    targets: list[tuple[str | None, str | None, str]] = []
    for case in cases:
        owner = owners.get(case.user_id) if case.user_id is not None else None
        if owner is not None and _is_reachable_user(owner):
            targets.append((owner.line_user_id, owner.email, str(case.id)))
    await session.commit()
    return targets


async def _dispatch_or_warn(
    dispatch: Callable[..., Awaitable[None]], *args: object, context: str
) -> None:
    """通知を送る。失敗しても **再送はせず**、ログと運営アラートに落とす。

    送信済みマーカーは既に commit 済みのため、ここで例外を伝播させても再送には
    ならず「1周分の残りの通知を巻き添えで落とす」だけになる。よって握り潰し、
    運営が気付けるよう warning のアラートを1本上げる（key でクールダウン）。
    """
    try:
        await dispatch(*args)
    except Exception as exc:  # noqa: BLE001 -- 1件の通知失敗で1周を壊さない
        logger.error(
            "reminders: 通知の送信に失敗（マーカー確定済みのため再送しない） - %s - %s",
            context,
            exc,
            exc_info=True,
        )
        alerts.fire_and_forget(
            alerts.send_alert(
                "リマインド通知の送信に失敗しました",
                "掘り起こし通知が1件届いていない可能性があります（再送はされません）。"
                f"対象: {context} / エラー: {type(exc).__name__}: {str(exc)[:200]}",
                severity="warning",
                key="reminder_dispatch_failed",
            )
        )


async def _load_owners(
    session: AsyncSession, user_ids: list[uuid.UUID | None]
) -> dict[uuid.UUID, User]:
    """依頼者を1クエリでまとめて引く（ループ内 PK 取得による N+1 の回避）。"""
    unique_ids = {uid for uid in user_ids if uid is not None}
    if not unique_ids:
        return {}
    users = (await session.scalars(select(User).where(User.id.in_(unique_ids)))).all()
    return {u.id: u for u in users}


def _is_reachable_user(user: User) -> bool:
    """退会・停止中の依頼者へはリマインドを送らない。

    退会済みは通知先そのものが匿名化済み（``notify.is_deleted_account_email``）で、
    停止中は「まず解除の問い合わせをしてもらう」導線が別にあるため、
    行動を促すリマインドを重ねない。
    """
    return not user.is_suspended and user.deleted_at is None


async def run_reminders(session: AsyncSession) -> dict[str, int]:
    """リマインドを1周実行し、送信した件数を返す。

    Returns:
        ``{"overdue": n, "no_bid": n}``。n は「リマインド対象として確保し、
        送信済みマーカーを立てた件数」（宛先不達・通知失敗の分も含む）。
    """
    now = datetime.now(timezone.utc)
    overdue = await _run_overdue_visit_reminders(session, now)
    no_bid = await _run_no_bid_reminders(session, now)
    logger.info("reminders: 実行完了 - overdue=%s no_bid=%s", overdue, no_bid)
    return {"overdue": overdue, "no_bid": no_bid}
