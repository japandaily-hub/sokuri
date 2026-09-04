"""案件エンドポイント — 作成 / 一覧 / 詳細。

住所詳細（address_detail）の開示制御（品質基準）:
- 所有ユーザー: CaseOut（住所詳細あり）
- 業者:        CaseMaskedOut（prefecture / city のみ。詳細は落札後に
               GET /transactions/{id} で開示する）
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor, get_current_user
from app.api.rate_limit_deps import RateLimitGuard
from app.db.models.bid import BID_STATUS_PENDING, BID_STATUS_REJECTED, BID_STATUS_WITHDRAWN, Bid
from app.db.models.case import Case, CaseItem, CasePhoto
from app.db.models.transaction import Cancellation
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    BidOut,
    CaseCancelRequest,
    CaseCreateRequest,
    CaseMaskedOut,
    CaseOut,
)
from app.services import notify, notify_dispatch, storage
from app.services.case_lock import lock_case_row
from app.services.case_view import build_case_masked_out
from app.services.summary import (
    ItemAnalysisInput,
    MAX_PHOTOS_FOR_AI,
    generate_case_ai,
    generate_case_summary,
    photo_url_for_ai,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_case_out(case: Case) -> CaseOut:
    out = CaseOut.model_validate(case)
    # 取り下げ済み入札は依頼者側に完全非表示にする方針のため件数からも除外する
    # （業者の入札取り下げ機能は廃止済みだが、過去データの withdrawn 行との
    # 表示整合のためフィルタは残す。tests/test_bid_withdrawn_legacy.py 参照）。
    out.bid_count = sum(1 for b in case.bids if b.status != BID_STATUS_WITHDRAWN)
    out.item_count = len(case.items)
    out.photo_count = len(case.photos)
    return out


def _to_masked_out(case: Case, my_operator_id: uuid.UUID | None = None) -> CaseMaskedOut:
    out = build_case_masked_out(case)
    my_bid = None
    if my_operator_id is not None:
        for bid in case.bids:
            if bid.operator_id == my_operator_id:
                my_bid = BidOut.model_validate(bid)
                if bid.status == "selected" and bid.transaction is not None:
                    my_bid.transaction_id = bid.transaction.id
                break
    # 取り下げ済み入札は依頼者・業者いずれの集計からも除外する（_to_case_out と同じ理由）。
    out.bid_count = sum(1 for b in case.bids if b.status != BID_STATUS_WITHDRAWN)
    out.my_bid = my_bid
    # 最高入札額（自社入札を含む全業者の最高額。取り下げ済みは除く）。入札が無ければ None。
    # 秘匿しない方針（確定済み製品判断）のため全業者に開示する。
    out.top_bid_amount = max(
        (bid.amount for bid in case.bids if bid.status != BID_STATUS_WITHDRAWN),
        default=None,
    )
    return out


_CASE_LOAD = (
    selectinload(Case.photos),
    selectinload(Case.items).selectinload(CaseItem.photos),
    selectinload(Case.bids).selectinload(Bid.operator),
    selectinload(Case.bids).selectinload(Bid.transaction),
)


async def _get_case(session: AsyncSession, case_id: uuid.UUID) -> Case:
    case = await session.scalar(
        select(Case)
        .where(Case.id == case_id)
        .options(*_CASE_LOAD)
        # populate_existing: 同一リクエストスコープ外（同一セッション内での複数回の
        # 呼び出し）でも常に最新の関連（items/photos/bids）へ同期する。identity map
        # 上に既にロード済みの Case が残っている場合、指定しないと eager load が
        # 陳腐化したコレクションを上書きしない（bids.py の同種問題を参照）。
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    return case


@router.post(
    "/cases",
    response_model=CaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="案件作成（写真 + 住居情報 + AI 要約）",
)
async def create_case(
    body: CaseCreateRequest,
    background: BackgroundTasks,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("case_create")),
) -> CaseOut:
    # AI解析(Gemini呼び出し)を伴うコストDoS対策（security review 指摘対応）。
    # IP軸は Depends(RateLimitGuard(...)) が既にカウント・判定済み。アカウント軸は
    # user_id が Depends 解決後にしか判明しないため、ここで明示的にカウントする
    # （成功/失敗を問わず毎リクエストをコストとして数える。login等の失敗時のみ
    # カウント方式とは異なる）。
    request.state.rate_limit.hit_account(str(user.id))

    case = Case(
        user_id=user.id,
        purpose=body.purpose,
        status="open",
        prefecture=body.prefecture,
        city=body.city,
        address_detail=body.address_detail,
        housing_type=body.housing_type,
        floor_plan=body.floor_plan,
        floor_number=body.floor_number,
        has_elevator=body.has_elevator,
    )
    # 直下（未分類）写真。case.photos は「案件の全写真（未分類 + 商品紐づけ）」の
    # 合算ビューとして扱う（CasePhoto.item_id 経由の写真も case.photos に含める。
    # case_view.build_case_masked_out の photo_count 計算がこの前提に依存する）。
    # そのため AI 解析用の「未分類写真」参照は case.photos からではなく、この
    # ループで作る flat_photos から独立して集計する。
    flat_photos: list[CasePhoto] = []
    for photo_in in body.photos:
        if not storage.is_valid_key(photo_in.storage_key):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="storage_key が不正です。presign からやり直してください。",
            )
        photo = CasePhoto(
            storage_key=photo_in.storage_key,
            url=storage.public_url(photo_in.storage_key),
            sort_order=photo_in.sort_order,
        )
        case.photos.append(photo)
        flat_photos.append(photo)

    # items[].photos[].storage_key にも既存の is_valid_key() を必ず適用する
    # （新規経路の抜け漏れ防止）。sort_order は items 経路のみサーバ側で配列
    # インデックスに正規化し、クライアント指定値は信用しない（既存のフラット
    # photos 経路の sort_order 挙動は変更しない）。
    #
    # 各写真は item.photos（商品への紐づけ = case_item_id 管理）と case.photos
    # （案件全体の合算ビュー = case_id 管理）の両方へ追加する。CaseItem.photos /
    # CasePhoto.item 関係は foreign_keys=[case_item_id] に限定しているため
    # case_id はここで case.photos 経由の関係が単独で管理し、競合しない。
    for item_idx, item_in in enumerate(body.items):
        item = CaseItem(name=item_in.name, sort_order=item_idx)
        for photo_idx, photo_in in enumerate(item_in.photos):
            if not storage.is_valid_key(photo_in.storage_key):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="storage_key が不正です。presign からやり直してください。",
                )
            photo = CasePhoto(
                storage_key=photo_in.storage_key,
                url=storage.public_url(photo_in.storage_key),
                sort_order=photo_idx,
            )
            item.photos.append(photo)
            case.photos.append(photo)
        case.items.append(item)

    total_photo_count = len(case.photos)
    try:
        if case.items:
            # 予算配分（どの写真が実際に解析されるか）が確定した後に初めて
            # photo_url_for_ai（base64データURL化）を呼ぶよう、ここでは
            # (storage_key, url) の生タプルのみを渡す（summary.py 側の
            # _analyze_items_with_budget / generate_case_ai 内で遅延解決する。
            # 全写真を先行してbase64化するとメモリ/CPUを無駄に消費するため。
            # security review 指摘対応）。
            item_inputs = [
                ItemAnalysisInput(
                    name=item.name,
                    photo_refs=[(p.storage_key, p.url) for p in item.photos],
                )
                for item in case.items
            ]
            ungrouped_photo_refs = [(p.storage_key, p.url) for p in flat_photos]
            case.ai_summary, item_results = await generate_case_ai(
                purpose=case.purpose,
                housing_type=case.housing_type,
                floor_plan=case.floor_plan,
                items=item_inputs,
                ungrouped_refs=ungrouped_photo_refs,
            )
            for item, result in zip(case.items, item_results):
                item.ai_detected_name = result.ai_detected_name
                item.ai_condition = result.ai_condition
                item.ai_summary = result.ai_summary
        else:
            # レガシー（items無し）経路: generate_case_summary の既存契約
            # （解決済み文字列のリストを渡す）は温存する。解析対象は先頭
            # MAX_PHOTOS_FOR_AI 枚のみのため、その分だけを base64 化する
            # （案件上限が 150 枚になり、全件の先行解決はメモリを浪費するため）。
            ungrouped_refs: list[str] = []
            for p in flat_photos[:MAX_PHOTOS_FOR_AI]:
                ref = await photo_url_for_ai(p.storage_key, p.url)
                if ref is not None:
                    ungrouped_refs.append(ref)
            case.ai_summary = await generate_case_summary(
                purpose=case.purpose,
                housing_type=case.housing_type,
                floor_plan=case.floor_plan,
                photo_urls=ungrouped_refs,
            )
    except Exception as exc:
        logger.error("cases: AI サマリー生成に失敗（フォールバック） - %s", exc)
        case.ai_summary = f"利用目的: {case.purpose}。写真 {total_photo_count} 枚。"

    session.add(case)
    try:
        await session.commit()
    except IntegrityError as exc:
        # case_photos.storage_key の DB UNIQUE制約違反（security review 指摘対応・H-1、
        # case_items.py の add_case_item_photo と同じ多層防御）。他人が既にアップロード
        # 済みの storage_key を新規案件作成時に流用しようとした場合もここで一律拒否する
        # （素通しで500になるのを防ぐ）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="指定された写真の一部は既に別の案件で使用されています。presign からやり直してください。",
        ) from exc
    # session.refresh(case, attribute_names=["items"]) だけでは CaseItem.photos が
    # ネストしてeager loadされず、商品の写真が0枚のケースで応答シリアライズ時に
    # 未ロードのlazy loadが走りMissingGreenlet(500)になる（items内のphotosが1枚以上
    # あるケースはpre-commitのPython側状態がたまたま生き残り顕在化しないため見逃しやすい）。
    # _get_case() の eager load 定義（_CASE_LOAD）を再利用して確実に全関連をロードする。
    case = await _get_case(session, case.id)

    # LINE専用ユーザーの仮メール（実メール未設定）宛には送信しない。
    if not notify.is_placeholder_email(user.email):
        background.add_task(notify.send_case_created, user.email, str(case.id))
    return _to_case_out(case)


@router.get(
    "/cases",
    summary="案件一覧（ユーザー: 自分の案件 / 業者: 入札可能案件）",
)
async def list_cases(
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> list[CaseOut] | list[CaseMaskedOut]:
    if actor.typ == "user":
        assert actor.user is not None
        cases = (
            await session.scalars(
                select(Case)
                .where(Case.user_id == actor.user.id)
                .options(*_CASE_LOAD)
                .order_by(Case.created_at.desc())
            )
        ).all()
        return [_to_case_out(c) for c in cases]

    assert actor.operator is not None
    # 案件の「閲覧」は vendor_status を問わず許可する（pending/limited/active いずれも可）。
    # 入札のみ get_verified_operator（vendor_status == "active"）で別途ブロックする。
    # is_suspended（アカウント停止）は get_current_actor 側で既に弾かれている。
    cases = (
        await session.scalars(
            select(Case)
            .where(Case.status.in_(["open", "bidding"]))
            .options(*_CASE_LOAD)
            .order_by(Case.created_at.desc())
        )
    ).all()
    return [_to_masked_out(c, actor.operator.id) for c in cases]


@router.get(
    "/cases/{case_id}",
    summary="案件詳細（業者には住所詳細をマスク）",
)
async def get_case(
    case_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> CaseOut | CaseMaskedOut:
    case = await _get_case(session, case_id)

    if actor.typ == "user":
        assert actor.user is not None
        if case.user_id != actor.user.id and actor.user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
            )
        return _to_case_out(case)

    assert actor.operator is not None
    # 一覧同様、閲覧は vendor_status を問わず許可する（入札は別ゲートでブロック）。
    return _to_masked_out(case, actor.operator.id)


@router.post(
    "/cases/{case_id}/cancel",
    response_model=CaseOut,
    summary="出品を取り下げる（依頼者本人のみ・open/bidding のみ）",
)
async def cancel_case(
    case_id: uuid.UUID,
    body: CaseCancelRequest,
    background: BackgroundTasks,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("case_cancel")),
) -> CaseOut:
    # Case行の排他ロック取得・pending入札の一括却下・監査レコード書き込みを
    # 伴うコストDoS対策（旧 bid_withdraw と同じ operator_id 相当の軸で、
    # ここでは user_id 軸をカウントする。security review 指摘対応）。
    request.state.rate_limit.hit_account(str(user.id))

    # 所有権の事前照会（軽量・ロック無し）。認可判定（案件の所有権確認）より
    # 前にCase行の排他ロックを取得すると、他人のcase_idを大量に送りつける
    # だけで正規の出品取り下げ・選択処理を待たせるロック争奪DoSを誘発できて
    # しまうため、ロック取得前に所有権を確認する（bids.py の select_bid と
    # 同じパターン。security review 2周目 Medium指摘対応）。
    owner_id = await session.scalar(select(Case.user_id).where(Case.id == case_id))
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    if owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
        )

    # select（落札）との競合を防ぐため、所有権確認後にCase行をロックする
    # （TOCTOU対策。bids.py の lock_case_row を共有利用する）。
    await lock_case_row(session, case_id)
    case = await _get_case(session, case_id)
    if case.user_id != user.id:
        # 上記の所有権事前照会とCase行ロックの間の競合に対する多層防御
        # （通常は到達しない）。
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
        )

    if case.status == "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件はまだ出品されていません。",
        )
    if case.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="成約済みの案件は取引のキャンセルから手続きしてください。",
        )
    if case.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は既に取り下げ済みです。",
        )
    if case.status not in ("open", "bidding"):
        # 将来 status の値が拡張された場合の多層防御（到達しない想定）。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この案件は取り下げできない状態です。",
        )

    # 却下対象（元pending）業者への通知プリミティブ値は、bidsを更新する前
    # （in-memory状態がまだpendingのまま）に収集する（select_bid のlosersループ
    # と同じパターン。ORMオブジェクトをBackgroundTasksへ渡さない。commit後は
    # セッションがdetachされうるため）。依頼者本人への通知は不要
    # （自身の操作のため）。
    #
    # 注意: 下記の一括UPDATE（update(Bid)...）はSQLAlchemyのORM Update構文
    # のデフォルト同期方式（synchronize_session='auto'）により、この時点で
    # 既にセッションのidentity map上のBidオブジェクト（case.bidsが参照する
    # ものと同一）の.statusをその場で書き換えてしまう。そのため losers の
    # 収集は必ず一括UPDATEの**前**に行うこと（後に回すと全滅する）。
    losers: list[tuple[str | None, str]] = [
        (b.operator.line_user_id, b.operator.contact_email)
        for b in case.bids
        if b.status == BID_STATUS_PENDING
    ]

    # pending入札を条件付きUPDATEで一括却下する（select_bidの条件付きUPDATEと
    # 同じ堅牢化パターン。Case行ロックにより通常は排他されるが、多層防御として
    # Bid単位でも状態をWHERE句で再検証してから更新する）。
    await session.execute(
        update(Bid)
        .where(Bid.case_id == case.id, Bid.status == BID_STATUS_PENDING)
        .values(status=BID_STATUS_REJECTED)
    )

    # 条件付きUPDATE（status=open/biddingであることをWHERE句で再検証してから
    # 更新する）。select_bid・create_bid と同じ多層防御パターン。
    result = await session.execute(
        update(Case)
        .where(Case.id == case.id, Case.status.in_(("open", "bidding")))
        .values(status="cancelled")
    )
    if result.rowcount != 1:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="案件の状態が変わったため取り下げできませんでした。",
        )
    case.status = "cancelled"

    session.add(
        Cancellation(
            case_id=case.id,
            transaction_id=None,
            cancelled_by="user",
            reason=body.reason,
        )
    )

    case_id_str = str(case.id)
    case_prefecture = case.prefecture
    case_city = case.city
    case_purpose = case.purpose

    try:
        await session.commit()
    except IntegrityError as exc:
        # Case行ロック＋条件付きUPDATEにより通常は到達しないが、変換しないと
        # 素通しで500になるため保険として捕捉する（create_bid/select_bid と
        # 同じ多層防御パターン）。
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="案件の状態が変わったため取り下げできませんでした。",
        ) from exc

    case = await _get_case(session, case.id)

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
    return _to_case_out(case)
