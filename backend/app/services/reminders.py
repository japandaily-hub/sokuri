"""リマインド定期処理（r12 決定3 / 入札未決定は追加分）— 訪問日超過 / 入札ゼロ放置 /
入札未決定の掘り起こし。

``main.py`` の lifespan が 1 時間毎に :func:`run_reminders` を呼ぶほか、
``POST /admin/jobs/reminders`` から手動実行できる。どちらの経路でも実体は同じ関数で、
送信済み判定は DB 列（``transactions.overdue_reminded_at`` / ``cases.no_bid_reminded_at`` /
``cases.bids_pending_reminded_at``）だけに集約する（alembic 0033 / 0035）。メモリ上の
台帳を使わないため、再デプロイ・複数インスタンス・手動実行が混ざっても同一の
成約・案件へ二重に通知が飛ばない。

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
   dispatch_* の戻り値（:data:`app.services.notify_dispatch.DispatchOutcome`）を
   ``_dispatch_and_tally`` が種別ごとに集計し、``run_reminders`` が3種別を合算して
   1周につき最大1本のアラートへ集約する（失敗のたびに個別発報しない）。
   個別の失敗（``failed``）が1件も無いまま対象が全件 unreachable（= LINE未連携・
   仮メール等で誰にも届く経路が無く0件送信）になった場合は、それ自体を
   データ不整合の兆候とみなし ``reminder_all_unreachable`` という別キーで
   系統障害アラートを出す（:data:`_ALL_UNREACHABLE_MIN_ATTEMPTED` 件以上の場合のみ。
   security review Low-3 対応）。

対象抽出の計算量:
- いずれの抽出も「未リマインド行だけを対象にする部分索引」
  （``ix_transactions_overdue_reminder`` / ``ix_cases_no_bid_reminder`` /
  ``ix_cases_bids_pending_reminder``）に乗る。送信済みの行が何万件積み上がっても
  走査対象は増えない（入札未決定の抽出だけは、対象を絞る「最古の pending 入札の
  経過日数」自体はこの部分索引に乗らないサブクエリ判定のため、絞り込み後の
  ``status='bidding'`` 母集団に対する走査になる——案件全体に対する全走査ではない）。
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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.bid import BID_STATUS_PENDING, BID_STATUS_WITHDRAWN, Bid
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.services import alerts, notify_dispatch
from app.services.notify_dispatch import DELIVERED, FAILED, SKIPPED, DispatchOutcome

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

#: 入札未決定とみなすまでの日数（最古の pending 入札が届いてからの経過）。
BIDS_PENDING_GRACE_DAYS = 2

#: 掘り起こしの遡り上限（日）。これより古い放置は「今さら催促しても意味が無い」
#: ものとして対象外にする。窓が無いと、機能追加直後や長期停止からの復帰時に
#: サービス開始以来の全該当行へ一斉通知が飛ぶ（r12-review H-1）。
REMINDER_LOOKBACK_DAYS = 14

#: 1周で確保・通知する上限件数。外部 API（LINE / SMTP）へ一度に投げる量を抑え、
#: 失敗時の影響範囲も1周分に閉じ込める。積み残しは次の周期で処理される。
REMINDER_BATCH_LIMIT = 200

#: run_reminders 終了時のアラート本文に載せる失敗 context の上限件数。
#: alerts.send_alert の本文は 1800 文字で切り詰められるため、無制限に列挙しない。
_ALERT_FAILURE_SAMPLES = 5

#: 「全件 unreachable（= 誰にも通知経路が無く0件送信）」を系統障害として別アラート
#: で検知するための最小試行件数（security review Low-3）。failed が1件も無いまま
#: 全滅すると reminder_dispatch_failed の発報条件（failed_total > 0）に触れず
#: 沈黙してしまう（LINE連携テーブルの移行ミス等）。1〜2件程度の unreachable は
#: 「LINE未連携かつ仮メールの利用者がたまたま該当した」という平常運転でも起こり
#: うるため、ある程度まとまった件数が全滅したときだけ発報する。
_ALL_UNREACHABLE_MIN_ATTEMPTED = 10


@dataclass
class ReminderDispatchTally:
    """1周分の通知配送結果の集計（1種別ぶん）。run_reminders が3種別を合算する。"""

    attempted: int = 0
    delivered: int = 0
    failed: int = 0
    skipped: int = 0
    #: DispatchOutcome のいずれにも一致しない戻り値（実装バグ・想定外のモック等）。
    #: security review Low-1: delivered へ黙って倒すと「黙った不達」の再発になるため
    #: 独立カウンタで分離し、ログにだけ残す（誤アラート防止のため運営アラートの
    #: 発報条件には含めない）。
    unknown: int = 0
    #: FAILED になった呼び出しの context を先頭から最大 _ALERT_FAILURE_SAMPLES 件保持する。
    failure_contexts: list[str] = field(default_factory=list)


async def _run_overdue_visit_reminders(
    session: AsyncSession, now: datetime, tally: ReminderDispatchTally
) -> int:
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
        await _dispatch_and_tally(
            tally,
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


async def _run_no_bid_reminders(
    session: AsyncSession, now: datetime, tally: ReminderDispatchTally
) -> int:
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

    targets = await _load_case_owner_targets(session, claimed_ids)
    for line_user_id, email, case_id in targets:
        await _dispatch_and_tally(
            tally,
            notify_dispatch.dispatch_no_bid_reminder,
            line_user_id,
            email,
            case_id,
            context=f"no_bid case_id={case_id}",
        )
    return len(claimed_ids)


async def _load_case_owner_targets(
    session: AsyncSession, case_ids: Sequence[uuid.UUID]
) -> list[tuple[str | None, str | None, str]]:
    """確保済みの案件から依頼者の通知先を取り出し、読み取りTxを閉じる。

    入札ゼロ放置 (b) と入札未決定 (c) の両方で使う共通ローダー——どちらも
    「案件から依頼者本人だけに通知する」形が同じため。
    """
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


async def _run_bids_pending_reminders(
    session: AsyncSession, now: datetime, tally: ReminderDispatchTally
) -> int:
    """(c) 入札は届いているが依頼者が一定日数、決定していない案件を掘り起こす。

    (b) の「入札ゼロ放置」と対になる穴——入札が1件でも付くと (b) の対象から
    外れるが、届いた入札を依頼者が放置しているケースは (b) にも訪問日超過
    リマインド（成約前なので visit_date が無い）にも引っかからなかった。

    Returns:
        確保（= 送信済みマーカーを立てた）案件の件数。
    """
    newest_threshold = now - timedelta(days=BIDS_PENDING_GRACE_DAYS)
    oldest_threshold = now - timedelta(days=BIDS_PENDING_GRACE_DAYS + REMINDER_LOOKBACK_DAYS)
    # 「最古の pending 入札がいつ届いたか」で経過日数を測る（bidding へ遷移した
    # 時刻は追跡していない上、2件目以降の入札でも case.status への再代入により
    # updated_at が動きうるため、案件側の列を根拠にできない）。
    #
    # 選択できない入札（停止中・承認取消・退会済み業者のもの）は母集団から除外
    # する（security review Medium-1 対応）。bids.py の select_bid が弾く条件
    # （is_suspended / vendor_status != "active" / deleted_at）と揃えないと、
    # 「唯一残っている pending 入札が実は選べない」案件にも「決定してください」
    # の催促が飛び、依頼者がリンク先で選ぼうとすると必ず409で詰む。
    oldest_pending_bid_at = (
        select(func.min(Bid.created_at))
        .join(Operator, Operator.id == Bid.operator_id)
        .where(
            Bid.case_id == Case.id,
            Bid.status == BID_STATUS_PENDING,
            Operator.is_suspended.is_(False),
            Operator.vendor_status == "active",
            Operator.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    candidates = (
        select(Case.id)
        .where(
            Case.bids_pending_reminded_at.is_(None),
            Case.status == "bidding",
            Case.user_id.is_not(None),
            oldest_pending_bid_at.is_not(None),
            oldest_pending_bid_at < newest_threshold,
            oldest_pending_bid_at >= oldest_threshold,
        )
        .order_by(Case.created_at.asc())
        .limit(REMINDER_BATCH_LIMIT)
    )
    claimed_ids = (
        (
            await session.execute(
                update(Case)
                .where(Case.bids_pending_reminded_at.is_(None), Case.id.in_(candidates))
                .values(bids_pending_reminded_at=now)
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

    targets = await _load_case_owner_targets(session, claimed_ids)
    for line_user_id, email, case_id in targets:
        await _dispatch_and_tally(
            tally,
            notify_dispatch.dispatch_bids_pending_reminder,
            line_user_id,
            email,
            case_id,
            context=f"bids_pending case_id={case_id}",
        )
    return len(claimed_ids)


async def _dispatch_and_tally(
    tally: ReminderDispatchTally,
    dispatch: Callable[..., Awaitable[DispatchOutcome]],
    *args: object,
    context: str,
) -> None:
    """通知を送り、結果を ``tally`` へ集計する（アラート発報はしない）。

    アラートの発報は run_reminders に集約する（1周の途中経過ではなく、3種別を
    合算した最終結果で1本にまとめて上げるため）。

    送信済みマーカーは既に commit 済みのため、ここで例外を伝播させても再送には
    ならず「1周分の残りの通知を巻き添えで落とす」だけになる。dispatch_* 自体は
    ``_best_effort`` が例外を FAILED へ畳んで返すため通常はここへ例外が届かないが、
    ``_load_*`` 由来の想定外の例外に備えた保険として try/except は残す（到達時は
    failed 扱いにしてログへ残し、1周を壊さない）。
    """
    tally.attempted += 1
    try:
        outcome = await dispatch(*args)
    except Exception as exc:  # noqa: BLE001 -- 1件の通知失敗で1周を壊さない
        logger.exception(
            "reminders: 通知処理で想定外の例外（マーカー確定済みのため再送しない） - %s - %s",
            context,
            exc,
        )
        tally.failed += 1
        if len(tally.failure_contexts) < _ALERT_FAILURE_SAMPLES:
            tally.failure_contexts.append(context)
        return

    if outcome == FAILED:
        tally.failed += 1
        logger.error(
            "reminders: 通知の送信に失敗（マーカー確定済みのため再送しない） - %s",
            context,
        )
        if len(tally.failure_contexts) < _ALERT_FAILURE_SAMPLES:
            tally.failure_contexts.append(context)
    elif outcome == SKIPPED:
        tally.skipped += 1
        logger.info("reminders: 通知先が無く送信対象外 - %s", context)
    elif outcome == DELIVERED:
        tally.delivered += 1
    else:
        # 三値のいずれにも一致しない想定外の戻り値（実装バグの可能性）。誤アラート
        # 防止のため failed 扱いにはしないが、delivered として黙って倒すと
        # 「例外もなく黙って不達」という本件と同種の盲点を再生産するため、
        # 独立カウンタに分離した上で warning ログに残す（security review Low-1）。
        tally.unknown += 1
        logger.warning(
            "reminders: 未知の DispatchOutcome を受信（delivered/failed どちらにも計上しない） - %r - %s",
            outcome,
            context,
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

    確保件数（overdue/no_bid/bids_pending）とは別に、実際の配送結果を集計し、
    1周につき最大1本の運営アラートへ集約する（種別ごとに個別発報しない）。

    Returns:
        ``{"overdue": n, "no_bid": n, "bids_pending": n, "undelivered": m, "unreachable": k}``。
        n は「リマインド対象として確保し、送信済みマーカーを立てた件数」（宛先不達・
        通知失敗の分も含む）。m（undelivered）は実際に届かなかった件数（failed の
        合計）、k（unreachable）は試行できる宛先が無かった件数（skipped の合計）。
    """
    now = datetime.now(timezone.utc)
    overdue_tally = ReminderDispatchTally()
    no_bid_tally = ReminderDispatchTally()
    bids_pending_tally = ReminderDispatchTally()

    overdue = await _run_overdue_visit_reminders(session, now, overdue_tally)
    no_bid = await _run_no_bid_reminders(session, now, no_bid_tally)
    bids_pending = await _run_bids_pending_reminders(session, now, bids_pending_tally)

    attempted_total = (
        overdue_tally.attempted + no_bid_tally.attempted + bids_pending_tally.attempted
    )
    delivered_total = (
        overdue_tally.delivered + no_bid_tally.delivered + bids_pending_tally.delivered
    )
    failed_total = overdue_tally.failed + no_bid_tally.failed + bids_pending_tally.failed
    skipped_total = overdue_tally.skipped + no_bid_tally.skipped + bids_pending_tally.skipped
    unknown_total = overdue_tally.unknown + no_bid_tally.unknown + bids_pending_tally.unknown

    # 全件 unreachable（= 誰にも通知経路が無く0件送信）は failed_total==0 のまま
    # 沈黙しうるため、系統障害として別キーで検知する（security review Low-3）。
    is_systemic_unreachable = (
        failed_total == 0
        and unknown_total == 0
        and delivered_total == 0
        and attempted_total >= _ALL_UNREACHABLE_MIN_ATTEMPTED
    )

    if failed_total > 0:
        failure_samples = (
            overdue_tally.failure_contexts
            + no_bid_tally.failure_contexts
            + bids_pending_tally.failure_contexts
        )[:_ALERT_FAILURE_SAMPLES]
        alerts.fire_and_forget(
            alerts.send_alert(
                "リマインド通知の送信に失敗しました",
                f"掘り起こし通知 {attempted_total} 件中 {failed_total} 件が届いていません。"
                f"内訳: overdue={overdue_tally.failed} no_bid={no_bid_tally.failed} "
                f"bids_pending={bids_pending_tally.failed}。"
                "マーカー確定済みのため再送されません（再送は DB 列を NULL に戻して行います）。"
                f"失敗対象（先頭{len(failure_samples)}件）: {'; '.join(failure_samples)}",
                severity="warning",
                key="reminder_dispatch_failed",
            )
        )
    elif is_systemic_unreachable:
        alerts.fire_and_forget(
            alerts.send_alert(
                "リマインド通知が全件、送信経路なしでスキップされました",
                f"掘り起こし対象 {attempted_total} 件が全て LINE 未連携・仮メール等により"
                "送信対象外（0件送信）でした。通常は一部の宛先だけがこの状態になるため、"
                "LINE連携判定やメール判定のデータ不整合が起きていないか確認してください。",
                severity="warning",
                key="reminder_all_unreachable",
            )
        )
    else:
        if delivered_total > 0 and alerts.is_active("reminder_dispatch_failed"):
            alerts.fire_and_forget(
                alerts.resolve_alert(
                    "reminder_dispatch_failed",
                    "リマインド通知の送信が復旧しました",
                    f"直近の実行で {delivered_total} 件のリマインド通知が正常に届きました。"
                    "失敗していた間の通知は再送されません。",
                )
            )
        if delivered_total > 0 and alerts.is_active("reminder_all_unreachable"):
            alerts.fire_and_forget(
                alerts.resolve_alert(
                    "reminder_all_unreachable",
                    "リマインド通知の送信経路が復旧しました",
                    f"直近の実行で {delivered_total} 件のリマインド通知が正常に届きました。",
                )
            )

    logger.info(
        "reminders: 実行完了 - overdue=%s no_bid=%s bids_pending=%s undelivered=%s "
        "unreachable=%s unknown=%s",
        overdue,
        no_bid,
        bids_pending,
        failed_total,
        skipped_total,
        unknown_total,
    )
    return {
        "overdue": overdue,
        "no_bid": no_bid,
        "bids_pending": bids_pending,
        "undelivered": failed_total,
        "unreachable": skipped_total,
    }
