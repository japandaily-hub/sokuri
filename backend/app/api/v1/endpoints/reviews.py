"""レビューエンドポイント — 成約完了後の双方向評価。

reviewer_type はトークン種別から導出する（クライアント指定を信用しない）。
評価は verdict（よかった／伸びしろ）。旧形式（rating のみ）も 0042 までは受け付ける
（入力規則は schemas_katadzuke.ReviewCreateRequest）。
ユーザー → 業者のレビュー投稿時は operators の集計列（good_count / improve_count /
review_count ほか）を再計算する。
当事者性と状態はロック前にロック無しで確かめ（第三者は行ロックを取れない）、同じ取引への
同時投稿は Case → Transaction の行ロックで直列化する。それでも一意制約に当たった場合
（ロックを取らない旧コードとの重なり等）は 409 にする。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor
from app.db.models.bid import Bid
from app.db.models.case import Case
from app.db.models.transaction import (
    COMPAT_RATING_BY_VERDICT,
    Review,
    Transaction,
    verdict_from_rating,
)
from app.db.session import get_session
from app.schemas_katadzuke import ReviewCreateRequest, ReviewOut
from app.services.case_lock import lock_transaction_rows
from app.services.review_stats import recalc_operator_review_stats

logger = logging.getLogger(__name__)

router = APIRouter()


def _reviewer_type_if_allowed(
    actor: Actor,
    *,
    case_user_id: uuid.UUID,
    bid_operator_id: uuid.UUID,
    txn_status: str,
) -> str:
    """当事者チェックと状態判定を行い、reviewer_type（トークン種別から導出）を返す。

    ロック前の軽量照会とロック後の読み直しの両方で使う（同じ判定・同じ文言・同じ順序:
    403 当事者でない → 409 成約完了前）。
    """
    if actor.typ == "user":
        assert actor.user is not None
        if case_user_id != actor.user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
            )
        reviewer_type = "user"
    else:
        assert actor.operator is not None
        if bid_operator_id != actor.operator.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この成約への権限がありません。"
            )
        reviewer_type = "operator"
    if txn_status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="レビューは成約完了後に投稿できます。",
        )
    return reviewer_type


@router.post(
    "/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="レビュー投稿（成約完了後・当事者のみ）",
)
async def create_review(
    body: ReviewCreateRequest,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> ReviewOut:
    # (1) ロックの前に、ロック無しの軽量な読み取りで存在・当事者性・状態を確かめる（判定順
    #     404 → 403 → 409 と文言は従来どおり）。transactions.py の _assert_party_before_lock
    #     （r6-verify-fix M1）と同じ規約: 認可より先にロックを取ると、無関係な第三者が他人の
    #     transaction_id を送りつけるだけで当事者の完了・キャンセル等を待たせられる（ロック争奪
    #     DoS）。第三者・存在しない取引・未完了の投稿はここで返り、行ロックを取らない。
    party_row = (
        await session.execute(
            select(Case.user_id, Bid.operator_id, Transaction.status)
            .select_from(Transaction)
            .join(Case, Transaction.case_id == Case.id)
            .join(Bid, Transaction.bid_id == Bid.id)
            .where(Transaction.id == body.transaction_id)
        )
    ).first()
    if party_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )
    _reviewer_type_if_allowed(
        actor,
        case_user_id=party_row[0],
        bid_operator_id=party_row[1],
        txn_status=party_row[2],
    )

    # (2) 同じ取引への同時投稿（二度押し・リトライ）を直列化するため、減額申請・完了・キャンセルと
    #     同じロック規約（services/case_lock.lock_transaction_rows: Case → Transaction）に参加し、
    #     ロック後に読み直して (1) と同じ判定と重複判定をやり直す（(1) とロックの間の競合に対する
    #     多層防御。transactions.py と同型）。後発は先発のコミットを待ち、読み直した txn.reviews に
    #     よりアプリ層の 409 になる。集計の業者行ロック（recalc_operator_review_stats）はその後に
    #     取るため順序は Case → Transaction → Operator（transactions.cancel と同じ）で、新たな
    #     デッドロックを作らない。SQLite（テスト）は FOR UPDATE を出力しないため挙動は変わらない。
    #     最後の砦は uq_reviews_transaction_reviewer で、下の try が 409 に変換する。
    if await lock_transaction_rows(session, body.transaction_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )
    txn = await session.scalar(
        select(Transaction)
        .where(Transaction.id == body.transaction_id)
        .options(
            selectinload(Transaction.case),
            selectinload(Transaction.bid),
            selectinload(Transaction.reviews),
        )
        # 同じセッションに以前読んだ状態が残っていても、ロック後の最新の値で読み直す。
        .execution_options(populate_existing=True)
    )
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="成約情報が見つかりません。"
        )
    reviewer_type = _reviewer_type_if_allowed(
        actor,
        case_user_id=txn.case.user_id,
        bid_operator_id=txn.bid.operator_id,
        txn_status=txn.status,
    )
    if any(r.reviewer_type == reviewer_type for r in txn.reviews):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="既にレビュー投稿済みです。"
        )

    # 入力規則: verdict を優先し、保存する rating は互換値（good=5／improve=2）。
    # rating のみの旧形式は値をそのまま保存し、verdict は★から導く（★4以上＝よかった）。
    if body.verdict is not None:
        verdict = body.verdict
        rating = COMPAT_RATING_BY_VERDICT[verdict]
    elif body.rating is not None:
        rating = body.rating
        verdict = verdict_from_rating(rating)
        # 旧 web からの投稿がまだ届いているかの証跡。0042（rating の削除）の実施時期は、
        # このログが出なくなったことを Render のログで確かめてから決める。
        logger.info(
            "review_legacy_rating_payload transaction=%s reviewer_type=%s rating=%s",
            txn.id,
            reviewer_type,
            rating,
        )
    else:
        # ReviewCreateRequest の model_validator が先に 422 を返すため通常は到達しない。
        # assert は python -O で消えるため、検証が外れても素通りさせない明示の分岐にする。
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="評価（よかった／伸びしろ）を選んでください。",
        )

    review = Review(
        transaction_id=txn.id,
        reviewer_type=reviewer_type,
        verdict=verdict,
        rating=rating,
        comment=body.comment,
    )
    session.add(review)
    # flush・集計・commit のどこで一意制約違反が出ても 409 にする。ロックを取らない書き手
    # （デプロイ切替中の旧コード等）と重なった後発は INSERT＝flush の時点で
    # uq_reviews_transaction_reviewer に当たる（従来は try が commit だけを囲み 500 だった）。
    try:
        await session.flush()
        # ユーザー → 業者評価なら operators の集計列（good_count / improve_count / review_count /
        # 互換の rating / latest_review_comment）を再計算する（正本は services/review_stats.py。
        # 対象 operators 行を排他ロックしてから集計するため同時投稿でもずれない）。
        if reviewer_type == "user":
            await recalc_operator_review_stats(session, txn.bid.operator_id)
        await session.commit()
    except IntegrityError as exc:
        # uq_reviews_transaction_reviewer（同一取引・同一投稿者は1件）。アプリ層の
        # 重複チェックをすり抜けた二重送信は 500 ではなく 409 にする（security review L-3）。
        await session.rollback()
        # rollback 後は ORM 属性が失効するため、リクエスト値とローカル変数だけを記録する。
        # 例外本文は SQL のパラメータ（口コミ本文）を含みうるため出さず、ドライバの例外名に留める。
        logger.warning(
            "review_create_conflict transaction=%s reviewer_type=%s error=%s",
            body.transaction_id,
            reviewer_type,
            type(exc.orig).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="既にレビュー投稿済みです。"
        ) from None
    await session.refresh(review)
    return ReviewOut.model_validate(review)
