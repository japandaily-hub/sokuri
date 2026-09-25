"""レビューエンドポイント — 成約完了後の双方向評価。

reviewer_type はトークン種別から導出する（クライアント指定を信用しない）。
評価は verdict（よかった／伸びしろ）のみ（旧形式の★は alembic 0042 で撤去済みで、rating は
モデルにも無い＝DB 列は 0044 で削除。入力規則は schemas_katadzuke.ReviewCreateRequest）。
ユーザー → 業者のレビュー投稿時は operators の集計列（good_count / improve_count /
review_count ほか）を再計算する。
当事者性と状態はロック前にロック無しで確かめ（第三者は行ロックを取れない）、同じ取引への
同時投稿は Case → Transaction の行ロックで直列化する。それでも一意制約に当たった場合
（ロックを取らない旧コードとの重なり等）は 409 にし、それ以外の整合性違反（NOT NULL・CHECK 等）は
障害として 500 にする。
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
from app.db.models.transaction import Review, Transaction
from app.db.session import get_session
from app.schemas_katadzuke import ReviewCreateRequest, ReviewOut
from app.services.case_lock import lock_transaction_rows
from app.services.review_stats import recalc_operator_review_stats

logger = logging.getLogger(__name__)

router = APIRouter()


# 同一取引・同一投稿者は1件（uq_reviews_transaction_reviewer）。この一意制約の違反だけを 409 にする。
_DUPLICATE_REVIEW_CONSTRAINT = "uq_reviews_transaction_reviewer"
_PG_UNIQUE_VIOLATION = "23505"
# SQLite（テスト）は sqlstate も制約名も返さないため、一意制約の列の組を含む文言で判別する。
_SQLITE_DUPLICATE_REVIEW_MESSAGE = (
    "UNIQUE constraint failed: reviews.transaction_id, reviews.reviewer_type"
)


def _classify_integrity_error(exc: IntegrityError) -> tuple[bool, str | None, str | None]:
    """IntegrityError を (uq_reviews_transaction_reviewer の違反か, sqlstate, 制約名) に分類する。

    PostgreSQL（asyncpg）: SQLAlchemy の asyncpg アダプタ（sqlalchemy/dialects/postgresql/asyncpg.py の
    AsyncAdapt_asyncpg_connection._handle_exception）は、元の asyncpg 例外を ``raise … from error`` で
    __cause__ に付け、その sqlstate を orig の pgcode / sqlstate に写す。制約名は元の例外の
    constraint_name（asyncpg がサーバの 'n' フィールドを入れる）。一意制約違反は sqlstate 23505。
    SQLite: sqlstate が無いため、エラー文言（sqlite3 の例外は SQL・パラメータを含まない）で判別する。
    例外の文字列全体（SQLAlchemy の例外は SQL とパラメータ＝口コミ本文を含む）はログに出さないこと。
    """
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    constraint = getattr(getattr(orig, "__cause__", None), "constraint_name", None)
    if sqlstate is not None:
        is_duplicate = (
            sqlstate == _PG_UNIQUE_VIOLATION and constraint == _DUPLICATE_REVIEW_CONSTRAINT
        )
    else:
        is_duplicate = _SQLITE_DUPLICATE_REVIEW_MESSAGE in str(orig)
    return is_duplicate, sqlstate, constraint


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

    # rating（旧形式の★）は撤去済みでモデルにマップしていない（0044 適用前の DB では NULL が入る）。
    review = Review(
        transaction_id=txn.id,
        reviewer_type=reviewer_type,
        verdict=body.verdict,
        comment=body.comment,
    )
    session.add(review)
    # flush・集計・commit のどこで起きた IntegrityError も下の except で捕まえ、一意制約
    # uq_reviews_transaction_reviewer の違反だけを 409 にする。ロックを取らない書き手（デプロイ切替中の
    # 旧コード等）と重なった後発は INSERT＝flush の時点でこの制約に当たる（従来は try が commit だけを
    # 囲み 500 だった）。
    try:
        await session.flush()
        # ユーザー → 業者評価なら operators の集計列（good_count / improve_count / review_count /
        # latest_review_comment）を再計算する（正本は services/review_stats.py。
        # 対象 operators 行を排他ロックしてから集計するため同時投稿でもずれない）。
        if reviewer_type == "user":
            await recalc_operator_review_stats(session, txn.bid.operator_id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # rollback 後は ORM 属性が失効するため、リクエスト値とローカル変数だけを記録する。例外の
        # 文字列は SQL のパラメータ（口コミ本文）を含むため出さず、型名・sqlstate・制約名に留める。
        is_duplicate, sqlstate, constraint = _classify_integrity_error(exc)
        if is_duplicate:
            # uq_reviews_transaction_reviewer（同一取引・同一投稿者は1件）。アプリ層の重複チェックを
            # すり抜けた二重送信は 500 ではなく 409 にする（security review L-3）。
            logger.warning(
                "review_create_conflict transaction=%s reviewer_type=%s error=%s",
                body.transaction_id,
                reviewer_type,
                type(exc.orig).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="既にレビュー投稿済みです。"
            ) from None
        # それ以外（NOT NULL・CHECK 違反等。例: 段B のコードが 0041 のスキーマで動いた）は障害なので
        # 409 に偽装せず 500 にし、5xx 監視（alert_middleware の 5xx 集計）に載せる（0042 review M-1）。
        # 例外を送出し直さないのは、未処理例外のアラート本文が str(exc)（SQL とパラメータ）を含むため。
        logger.error(
            "review_create_integrity_error transaction=%s reviewer_type=%s error=%s"
            " sqlstate=%s constraint=%s",
            body.transaction_id,
            reviewer_type,
            type(exc.orig).__name__,
            sqlstate,
            constraint,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="評価の保存に失敗しました。時間をおいて再度お試しください。",
        ) from None
    await session.refresh(review)
    return ReviewOut.model_validate(review)
