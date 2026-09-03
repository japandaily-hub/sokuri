"""入札エンドポイント — 一覧 / 入札 / 業者選択（落札）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor, get_current_user, get_verified_operator
from app.api.rate_limit_deps import RateLimitGuard
from app.db.models.bid import (
    BID_STATUS_PENDING,
    BID_STATUS_REJECTED,
    BID_STATUS_SELECTED,
    BID_STATUS_WITHDRAWN,
    Bid,
    BidWithdrawal,
)
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import BidCreateRequest, BidOut, TransactionOut
from app.services import notify, notify_dispatch
from app.services.message_guard import contains_contact_info

router = APIRouter()


async def _lock_case_row(session: AsyncSession, case_id: uuid.UUID) -> None:
    """親Case行をロックする（TOCTOU対策）。

    select（落札）と withdraw（取り下げ）はいずれも同一案件・同一入札の並行更新
    （落札処理中に取り下げられる／取り下げ処理中に選択される、等）を伴う。
    処理冒頭でCase行を明示ロックし、片方の処理が完了するまでもう片方を
    待機させることで、この競合を防ぐ（設計指示に基づく実装）。ロック取得のみが
    目的のため取得列は主キーのみに絞る。
    """
    await session.execute(select(Case.id).where(Case.id == case_id).with_for_update())


async def _get_case(session: AsyncSession, case_id: uuid.UUID) -> Case:
    case = await session.scalar(
        select(Case)
        .where(Case.id == case_id)
        .options(
            selectinload(Case.bids).selectinload(Bid.operator),
            selectinload(Case.bids).selectinload(Bid.transaction),
        )
        # populate_existing: 本番の get_session() はリクエストごとに新規セッションを
        # 払い出すため、identity map の汚染（同一セッション内での陳腐化）は本番では
        # 原理上発生しない。この指定が実際に意味を持つのは、単一セッションを複数
        # リクエストで共有するテストハーネス（test_*.py の create_test_app が
        # get_session を単一の db_session に override するパターン）に限られる
        # （QAレビューで訂正済み。当初「本番で重複入札チェックが破られる重大バグ」と
        # 診断していたが誤りだった）。したがってこれは共有セッション下での防御的な
        # 措置に過ぎず、重複入札の真の防止保証は DB のユニーク制約
        # （``uq_bids_case_operator``、bids テーブルの (case_id, operator_id)）である。
        # アプリ層の in-memory チェック（後述の any(...)）はDB往復を伴わないUX向上の
        # ための早期リターンに過ぎず、同時実行下での一意性の最終防衛線ではない
        # （create_bid の IntegrityError ハンドリング参照）。
        .execution_options(populate_existing=True)
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
    summary="入札一覧（依頼者本人: 取り下げ済みを除く全件 / admin: 全件 / 業者: 自社分のみ）",
)
async def list_bids(
    case_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> list[BidOut]:
    case = await _get_case(session, case_id)

    if actor.typ == "user":
        assert actor.user is not None
        is_owner = case.user_id == actor.user.id
        if not is_owner and actor.user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
            )
        if is_owner:
            # 取り下げ済み入札は依頼者本人には非表示にする方針（設計確定済み。
            # cases.py の _to_case_out / _to_masked_out と同じ理由）。admin が
            # 他ユーザーの案件を監査目的で閲覧する場合は取り下げ済みも含め
            # 全件返す（security review 指摘対応）。
            return [_bid_out(b) for b in case.bids if b.status != BID_STATUS_WITHDRAWN]
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
    # withdraw/select との競合（取り下げ・選択の処理中に古い case.status を
    # 読んでしまい、後勝ちで不整合な値を上書きする）を防ぐため、案件取得前に
    # Case行をロックする（TOCTOU対策。create_bid のみこのロック規約に未参加
    # だった。security review 指摘対応）。
    await _lock_case_row(session, case_id)
    case = await _get_case(session, case_id)
    if case.status not in ("open", "bidding"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は入札を受け付けていません。",
        )
    existing_bid = next((b for b in case.bids if b.operator_id == operator.id), None)
    if existing_bid is not None:
        # 取り下げ済み（withdrawn）でも uq_bids_case_operator 制約により再入札は
        # 不可（設計確定済み）。原因を区別できるようメッセージを分岐する。
        if existing_bid.status == BID_STATUS_WITHDRAWN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="この案件の入札は取り下げ済みのため、再入札はできません。",
            )
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
    try:
        await session.commit()
    except IntegrityError as exc:
        # 上記の in-memory チェック（any(...)）はDB往復前のUX向上目的の早期
        # リターンに過ぎず、同時実行下でのTOCTOU（2リクエストが同時に同一案件・
        # 同一業者で入札）を防げない。真の一意性保証は DB のユニーク制約
        # （uq_bids_case_operator）であり、違反時はここで捕捉して409へ変換する
        # （変換しない場合、素通しで500になってしまう。security review 指摘対応）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件には既に入札済みです。",
        ) from exc
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
    # 所有権の事前照会（軽量・ロック無し）。認可判定（案件の所有権確認）より
    # 前にCase行の排他ロックを取得すると、他人のcase_idを大量に送りつける
    # だけで正規の取り下げ・選択処理を待たせるロック争奪DoSを誘発できて
    # しまうため、ロック取得前に所有権を確認する（withdraw_bidと同じ
    # パターン。security review 2周目 Medium指摘対応）。
    owner_id = await session.scalar(select(Case.user_id).where(Case.id == case_id))
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    if owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
        )

    # 対象bidの事前存在確認（軽量・ロック無し）。上記と同じ理由で、存在しない
    # ／他案件のbid_idを送りつけるロック争奪も避けるためロック取得前に済ませる
    # （bid側の状態(pending等)の最終判定は従来通りロック後の条件付きUPDATEに
    # 委ねる。security review 2周目 Medium指摘対応）。
    target_exists = await session.scalar(
        select(Bid.id).where(Bid.id == bid_id, Bid.case_id == case_id)
    )
    if target_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="入札が見つかりません。"
        )

    # withdraw との競合（取り下げ処理中に選択される／その逆）を防ぐため、
    # 所有権・存在確認後にCase行をロックする（TOCTOU対策）。
    await _lock_case_row(session, case_id)
    case = await _get_case(session, case_id)
    if case.user_id != user.id:
        # 上記の所有権事前照会とCase行ロックの間の競合に対する多層防御
        # （通常は到達しない）。
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
        # 上記の存在事前照会とCase行ロックの間の競合に対する多層防御
        # （通常は到達しない）。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="入札が見つかりません。"
        )
    if target.status != BID_STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="この入札は選択できません。"
        )

    # 条件付きUPDATE（status=pendingであることをWHERE句で再検証してから更新）。
    # 直接代入によるUPDATEでは、withdraw側が同時に同じ行を pending→withdrawn へ
    # 更新した場合に「取り下げたのに選定されてしまう」事故が起こり得る
    # （設計指示に基づく堅牢化。Case行ロックにより通常は排他されるが、
    # 多層防御としてBid単位でも再検証する）。
    result = await session.execute(
        update(Bid)
        .where(Bid.id == target.id, Bid.status == BID_STATUS_PENDING)
        .values(status=BID_STATUS_SELECTED)
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="この入札は選択できません。"
        )
    target.status = BID_STATUS_SELECTED
    # 落選業者への通知はcommit後にプリミティブ値で行う（ORMオブジェクトを
    # BackgroundTasksへ渡さない。commit後はセッションがdetachされうるため）。
    losers: list[tuple[str | None, str]] = []
    for b in case.bids:
        if b.id != target.id and b.status == BID_STATUS_PENDING:
            b.status = BID_STATUS_REJECTED
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
    try:
        await session.commit()
    except IntegrityError as exc:
        # transactions.case_id の UNIQUE 制約違反を409へ変換する（create_bid と
        # 同じ多層防御パターン）。Case行ロック＋条件付きUPDATEにより通常は
        # 到達しないが、変換しない場合は素通しで500になってしまうため
        # 保険として捕捉する（security review 指摘対応）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は既に成約済みです。",
        ) from exc
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


@router.post(
    "/cases/{case_id}/bids/{bid_id}/withdraw",
    response_model=BidOut,
    status_code=status.HTTP_200_OK,
    summary="入札を取り下げる（業者本人のみ・再入札不可）",
)
async def withdraw_bid(
    case_id: uuid.UUID,
    bid_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("bid_withdraw")),
) -> BidOut:
    # get_verified_operator ではなく get_current_actor を使う（vendor_status
    # 降格後も取り下げは許可すべき de-escalating 操作のため。設計指示に基づく）。
    if actor.typ != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="業者アカウントのみ操作できます。"
        )
    assert actor.operator is not None
    operator = actor.operator

    # Case行の排他ロック取得・監査レコード書き込みを伴うコストDoS対策
    # （security review 指摘対応）。case_create と同じ「全リクエストを
    # 無条件でカウント」方式で operator_id 軸のみをカウントする。
    request.state.rate_limit.hit_account(str(operator.id))

    # 所有権の事前照会（軽量・ロック無し）。認可判定（bidの所有権確認）より
    # 前にCase行の排他ロックを取得すると、他社のbid_idを大量に送りつける
    # だけで正規の取り下げ・選択処理を待たせるロック争奪DoSを誘発できて
    # しまうため、ロック取得前に所有権を確認する（security review 指摘対応）。
    owned_bid_id = await session.scalar(
        select(Bid.id).where(
            Bid.id == bid_id, Bid.case_id == case_id, Bid.operator_id == operator.id
        )
    )
    if owned_bid_id is None:
        # 案件自体が存在しない場合（case_id不正）と、bidが見つからない場合
        # （他社のbid_id等）のいずれも同一メッセージ・404にする。メッセージを
        # 分けると case_id の存在有無を攻撃者に漏らしてしまうため（設計指示に
        # 基づく。403にしないのも同じ理由）。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="入札が見つかりません。"
        )

    # select（落札）との競合を防ぐため、所有権確認後にCase行をロックする
    # （TOCTOU対策）。
    await _lock_case_row(session, case_id)
    try:
        case = await _get_case(session, case_id)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            # 直前の所有権確認で存在を確認済みのため通常は到達しないが、
            # 万一の競合でもメッセージを「入札が見つかりません。」に統一する
            # （上記と同じ理由。_get_case 自体の挙動・メッセージは他エンドポイント
            # と共有のため変更しない）。
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="入札が見つかりません。"
            ) from exc
        raise

    target: Bid | None = next(
        (b for b in case.bids if b.id == bid_id and b.operator_id == operator.id),
        None,
    )
    if target is None:
        # 上記の所有権事前照会とCase行ロックの間の競合に対する多層防御
        # （通常は到達しない）。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="入札が見つかりません。"
        )
    if target.status == BID_STATUS_SELECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="落札済みの入札は取り下げできません。成約のキャンセルから手続きしてください。",
        )
    if target.status in (BID_STATUS_REJECTED, BID_STATUS_WITHDRAWN):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="この入札は取り下げできません。"
        )
    if case.status not in ("open", "bidding"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は入札を受け付けていません。",
        )

    # 条件付きUPDATE（status=pendingであることをWHERE句で再検証してから更新）。
    # Case行ロックにより通常は排他されるが、多層防御としてBid単位でも再検証する
    # （select_bid の同種堅牢化と対になる。設計指示に基づく）。
    result = await session.execute(
        update(Bid)
        .where(
            Bid.id == target.id,
            Bid.operator_id == operator.id,
            Bid.status == BID_STATUS_PENDING,
        )
        .values(status=BID_STATUS_WITHDRAWN)
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="この入札は取り下げできません。"
        )
    target.status = BID_STATUS_WITHDRAWN

    # 取り下げの監査証跡を1件作成する（security review 指摘対応）。
    # 回数制限・閾値アラート等の業務ロジックはこのスコープに含めない
    # （数値基準を推測で決めることになるため。設計指示に基づく。永続化のみ）。
    # company_name/amount は非正規化スナップショット（bid_withdrawals のFKは
    # ON DELETE RESTRICTだが、将来の運用変更でも取り下げ時点の事実関係を
    # 再構成できるようにするための多層防御。security review 2周目 Medium指摘対応）。
    session.add(
        BidWithdrawal(
            bid_id=target.id,
            case_id=case.id,
            operator_id=operator.id,
            company_name=operator.company_name,
            amount=target.amount,
        )
    )

    # 残pending件数をCase行ロック下で再取得し、0件ならcase.statusをopenへ戻す
    # （biddingのまま放置すると、依頼者側の一覧から「入札受付中」なのに
    # 表示される入札が0件という不整合な状態になるため）。
    remaining_pending = await session.scalar(
        select(func.count())
        .select_from(Bid)
        .where(Bid.case_id == case.id, Bid.status == BID_STATUS_PENDING)
    )
    if remaining_pending == 0 and case.status == "bidding":
        case.status = "open"

    # 通知はcommit後にプリミティブ値で行う（ORMオブジェクトをBackgroundTasksへ
    # 渡さない。commit後はセッションがdetachされうるため。既存の select_bid と
    # 同じパターン）。依頼者の取得・メール判定はcommit前に済ませておく。
    owner_email: str | None = None
    if case.user_id is not None:
        owner = await session.get(User, case.user_id)
        if owner is not None and not notify.is_placeholder_email(owner.email):
            owner_email = owner.email
    company_name = operator.company_name
    case_id_str = str(case.id)

    try:
        await session.commit()
    except IntegrityError as exc:
        # bid_withdrawals の一意制約（uq_bid_withdrawals_bid_id）/ FK RESTRICT 違反を
        # 409へ変換する（create_bid / select_bid と同じ多層防御パターン）。
        # Case行ロック＋条件付きUPDATEにより通常は到達しないが、変換しないと
        # 素通しで500になりDB制約名が露出するため保険として捕捉する
        # （security review 指摘対応）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この入札は既に取り下げ済みか、取り下げできない状態です。",
        ) from exc
    await session.refresh(target)
    target.operator = operator

    if owner_email is not None:
        background.add_task(
            notify.send_bid_withdrawn,
            owner_email,
            case_id_str,
            company_name,
        )
    return _bid_out(target)
