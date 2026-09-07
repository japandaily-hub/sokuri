"""入札エンドポイント — 一覧 / 入札 / 業者選択（落札）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    Actor,
    assert_operator_not_suspended,
    get_case_viewer_actor,
    get_current_user,
    get_verified_operator,
)
from app.core.limits import BID_RAISE_MIN_STEP, MAX_BID_REVISIONS
from app.db.models.bid import (
    BID_STATUS_PENDING,
    BID_STATUS_REJECTED,
    BID_STATUS_SELECTED,
    BID_STATUS_WITHDRAWN,
    Bid,
    BidAmountHistory,
)
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import BidCreateRequest, BidOut, BidUpdateRequest, TransactionOut
from app.services import notify_dispatch
from app.services.case_lock import lock_case_row, lock_operator_row
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
    # 停止業者の入札は一覧から除外せず旗を立てる（除外すると依頼者からは入札が
    # 黙って消えたようにしか見えず、選択できない理由も伝わらない）。実際の選択
    # 禁止は select_bid 側の409で担保する。r6-flow ADD-1 対応。
    # 退会済み（deleted_at 非null）業者も同じ旗を流用する（r8-review H-1対応。
    # スキーマに operator_deleted を追加する本筋改修は別途）。
    out.operator_suspended = bool(bid.operator.is_suspended) or bid.operator.deleted_at is not None
    return out


@router.get(
    "/cases/{case_id}/bids",
    response_model=list[BidOut],
    summary="入札一覧（依頼者本人: 取り下げ済みを除く全件 / admin: 全件 / 業者: 自社分のみ）",
)
async def list_bids(
    case_id: uuid.UUID,
    actor: Actor = Depends(get_case_viewer_actor),
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
    # 2026-09-07 決定（r12 決定2からの方針転換）: 業者へは取り下げ済みを除く
    # 全入札を返す。ただし他社分は社名・コメント・業者IDを非開示にする匿名開示
    # （amount・status・created_at・updated_at・revision_count・operator_suspended
    # は開示）。自社分のみ従来どおり全フィールド（operator込み）を返す。
    # 未承認・停止中の業者は get_case_viewer_actor が 403 で弾いている（r12 決定1）。
    visible_bids = [b for b in case.bids if b.status != BID_STATUS_WITHDRAWN]

    # security review Medium指摘対応: 案件が open/bidding を離れた（closed/
    # cancelled 等）後は「落札額の事後開示」になってしまうため、他社分は
    # 一切返さない（自社分のみ）。承認取消の再確認などで自社の過去入札を
    # 見返すニーズは残すため、自社分は状態に関わらず返す。
    case_is_active = case.status in ("open", "bidding")
    # security review Medium指摘対応: 他社金額の開示先は vendor_status="active"
    # の業者のみ。"limited"（許可証提出済みで入札不可のレガシー値）は閲覧は
    # 許可されるが、価格競争の当事者ではないため他社分は非開示にする。
    disclose_others = case_is_active and actor.operator.vendor_status == "active"

    visible_bids.sort(key=lambda b: b.amount, reverse=True)
    results: list[BidOut] = []
    for b in visible_bids:
        if b.operator_id == actor.operator.id:
            out = _bid_out(b)
            out.is_mine = True
            results.append(out)
            continue
        if not disclose_others:
            continue
        # security review Medium指摘対応: 停止中・退会済み業者の入札は
        # select_bid でも選択不可（依頼者は選べない）ため、他社への開示対象
        # からも除外する（「幻の最高額・幻の競合」を作らない）。bid_count
        # （自社分含む live_bids の件数）には影響させない。
        if b.operator.is_suspended or b.operator.deleted_at is not None:
            continue
        # 他社分: 匿名開示。operator/message/transaction_id を落とし、
        # is_mine=False のまま。operator_suspended は依頼者側の選択可否判断と
        # 同じ理由で False 固定にする（他社が停止中かは業者間で開示しない）。
        masked = BidOut.model_validate(b)
        masked.operator = None
        masked.message = None
        masked.transaction_id = None
        masked.is_mine = False
        masked.operator_suspended = False
        results.append(masked)
    return results


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
    # cancel_case/select との競合（出品取り下げ・選択の処理中に古い case.status を
    # 読んでしまい、後勝ちで不整合な値を上書きする）を防ぐため、案件取得前に
    # Case行をロックする（TOCTOU対策。create_bid のみこのロック規約に未参加
    # だった。security review 指摘対応）。
    await lock_case_row(session, case_id)
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
            detail="この案件には既に入札済みです。金額の変更は入札の引き上げから行えます。",
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
            detail="この案件には既に入札済みです。金額の変更は入札の引き上げから行えます。",
        ) from exc
    await session.refresh(bid)
    bid.operator = operator

    if case.user_id is not None:
        owner = await session.get(User, case.user_id)
        # LINE優先→メールフォールバック。仮メール（LINE専用ユーザー）判定は
        # dispatch 側へ集約する（仮メールでもLINE連携済みならLINEには届けるため）。
        # detached 対策として ORM ではなくプリミティブ値のみを add_task に渡す。
        if owner is not None:
            background.add_task(
                notify_dispatch.dispatch_bid_received,
                owner.line_user_id,
                owner.email,
                str(case.id),
                operator.company_name,
                bid.amount,
            )
    return BidOut.model_validate(bid)


@router.patch(
    "/cases/{case_id}/bids/me",
    response_model=BidOut,
    summary="自社入札の引き上げ（現在額より高い金額へのみ変更可・承認済み業者のみ）",
)
async def update_my_bid(
    case_id: uuid.UUID,
    body: BidUpdateRequest,
    background: BackgroundTasks,
    operator: Operator = Depends(get_verified_operator),
    session: AsyncSession = Depends(get_session),
) -> BidOut:
    """自社の入札額を現在額より高い金額へ引き上げる。

    1案件1業者1入札の一意制約（uq_bids_case_operator）と封印入札（他社額の
    非開示）は維持したまま、価格競争を働かせるための引き上げ専用API
    （設計確定済み）。下げる方向の変更は許可しない（封印入札のまま値下げ
    合戦を防ぐ）。

    create_bid と同じ理由（cancel_case/select との競合防止）で、案件取得前に
    Case行をロックする（TOCTOU対策）。
    """
    await lock_case_row(session, case_id)
    # security review Low指摘対応: cancel_case/select と同じ理由で、自社
    # Operator行もロックし停止（is_suspended）・退会（deleted_at）を同一
    # トランザクション内で再検証する（停止処理との競合窓を閉じる。
    # get_verified_operator の判定は依存性解決時点のスナップショットのため、
    # 直後に運営が当該業者を停止しても本処理は素通りしてしまう）。
    operator_deleted_at = await lock_operator_row(session, operator.id)
    if operator_deleted_at is not None:
        # get_current_operator の論理削除ゲート（_CRED_EXC・401）と同一の
        # 契約に揃える（退会済みトークンは呼び出し経路によらず同じ扱いにする）。
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await session.refresh(operator)
    # get_current_operator と同一の SUSPENDED_ACCOUNT_DETAIL（403）を再利用する
    # （security review Low指摘対応: ロック取得後の最新状態で停止処理との
    # 競合を再検証する）。
    assert_operator_not_suspended(operator)

    case = await _get_case(session, case_id)
    if case.status not in ("open", "bidding"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は入札を受け付けていません。",
        )
    bid = next((b for b in case.bids if b.operator_id == operator.id), None)
    if bid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="この案件への入札がありません。"
        )
    if bid.status != BID_STATUS_PENDING:
        if bid.status == BID_STATUS_WITHDRAWN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="この案件の入札は取り下げ済みのため変更できません。",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この入札は現在の状態では変更できません。",
        )
    # security review High指摘対応: 最小引き上げ幅（1円単位の無意味な引き上げ
    # 連打による通知の増幅・履歴膨張を防ぐ。web の入力刻みと同じ）。
    if body.amount < bid.amount + BID_RAISE_MIN_STEP:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"現在の入札額（¥{bid.amount:,}）より"
                f"{BID_RAISE_MIN_STEP:,}円以上高い金額を指定してください。"
            ),
        )
    # security review High指摘対応: 引き上げ回数の上限（通知の増幅と
    # bid_amount_history の無制限な膨張を防ぐ）。
    if bid.revision_count >= MAX_BID_REVISIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"この入札の引き上げ回数が上限（{MAX_BID_REVISIONS}回）に達しました。",
        )
    # security review Medium指摘対応: message は body に含まれた場合のみ更新する
    # （null を明示すればクリア、省略なら現在値を維持する）。従来は
    # BidUpdateRequest のデフォルト値 None がそのまま上書きに使われ、message を
    # 省略しただけで既存メッセージが意図せず消えていた。
    message_provided = "message" in body.model_fields_set
    new_message = body.message if message_provided else bid.message
    # create_bid と同じ理由（プラットフォーム外への直接連絡誘導の禁止）。
    # メッセージが更新対象の場合のみ検査する（維持する既存メッセージは
    # 作成時に既に検査済みのため再検査不要）。
    if message_provided and contains_contact_info(new_message):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="入札メッセージに連絡先（電話番号・メールアドレス）やURLは記載できません。",
        )

    old_amount = bid.amount
    old_message = bid.message
    # QA M4対応（通知の増幅防止）: 依頼者への「引き上げ」通知は、その引き上げで自社が
    # 最高額になった時だけ送る（既に首位のまま上乗せ／首位に届かない上乗せは、依頼者の
    # 選定判断を変えないため通知しない。金額自体は案件画面で常に見える）。母集団は
    # 依頼者が実際に選べる入札＝取り下げ・停止中・退会済みを除く他社の入札。
    top_other_before = max(
        (
            b.amount
            for b in case.bids
            if b.operator_id != operator.id
            and b.status != BID_STATUS_WITHDRAWN
            and not b.operator.is_suspended
            and b.operator.deleted_at is None
        ),
        default=None,
    )
    became_top = top_other_before is None or (
        old_amount <= top_other_before < body.amount
    )
    history = BidAmountHistory(
        bid_id=bid.id,
        old_amount=old_amount,
        new_amount=body.amount,
        old_message=old_message,
        new_message=new_message,
    )
    session.add(history)
    bid.amount = body.amount
    bid.message = new_message
    bid.revision_count += 1
    await session.commit()
    await session.refresh(bid)
    bid.operator = operator

    if case.user_id is not None and became_top:
        owner = await session.get(User, case.user_id)
        # create_bid と同じ理由（detached対策のプリミティブ値のみをadd_taskへ渡す）。
        if owner is not None:
            background.add_task(
                notify_dispatch.dispatch_bid_updated,
                owner.line_user_id,
                owner.email,
                str(case.id),
                operator.company_name,
                old_amount,
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
    # だけで正規の出品取り下げ・選択処理を待たせるロック争奪DoSを誘発できて
    # しまうため、ロック取得前に所有権を確認する（cancel_caseと同じ
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

    # cancel_case（出品取り下げ）との競合（取り下げ処理中に選択される／
    # その逆）を防ぐため、所有権・存在確認後にCase行をロックする（TOCTOU対策）。
    await lock_case_row(session, case_id)
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
    # 入札後に運営が業者を停止した場合、その入札を選択すると「成立直後から
    # 業者側の全操作が403（deps.assert_operator_not_suspended）になる成約」が
    # 生まれ、依頼者は他の入札を捨てた上で詰む。ロック取得後（＝停止操作との
    # 競合後）の最新状態で弾く（r6-flow ADD-1 対応）。
    if target.operator.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この業者は現在利用停止中のため選択できません。運営にお問い合わせください。",
        )
    # 承認が取り消された（vendor_status != "active"）業者も同様に弾く。選択できて
    # しまうと住所非開示（awaiting_approval=true）のまま停滞する成約になる
    # （transactions.get_transaction の判定と同じ基準に揃える）。
    # 注: "limited" はレガシー値で入札自体が不可（deps.py の get_verified_operator）
    # のため、選定側も "active" のみを許可する。
    if target.operator.vendor_status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この業者は現在選択できません。運営にお問い合わせください。",
        )
    # 退会済み（deleted_at 非null）業者も選択不可（r8-review H-1）。
    # ここは退会（operator_profile.delete_my_operator_account）との**直列化点**
    # でもある: Operator行を FOR UPDATE で掴んでから ``deleted_at`` を同一
    # トランザクション内で再読込する。退会側が先にこの行を掴んでいれば本文の
    # ロック取得がブロックされ、解放後に読む値は必ずコミット済みになる（＝退会
    # commit 後の落札は必ず409）。逆順なら退会側が本成約を検出して409になる。
    # ロック順序は Case（上の lock_case_row）→ Operator。退会側はCase行を掴まない
    # ため循環は生じない。identity map 上の ``target.operator`` は共有セッションの
    # テストハーネスで陳腐化しうるため、判定には必ずこの再読込値を使う。
    operator_deleted_at = await lock_operator_row(session, target.operator_id)
    if operator_deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この業者は退会済みのため選択できません。運営にお問い合わせください。",
        )

    # 条件付きUPDATE（status=pendingであることをWHERE句で再検証してから更新）。
    # 直接代入によるUPDATEでは、cancel_case側が同時に同じ行を pending→rejected へ
    # 更新した場合に「出品が取り下げられたのに選定されてしまう」事故が起こり得る
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
    case_prefecture = case.prefecture
    case_city = case.city
    case_purpose = case.purpose
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
            case_prefecture,
            case_city,
            case_purpose,
        )
    return TransactionOut.model_validate(txn)

