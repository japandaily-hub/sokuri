"""業者の口コミ集計（operators.good_count / improve_count / review_count /
latest_review_comment）の再計算。★平均（operators.rating）は alembic 0042 で撤去済みのため
更新しない。

reviews.py（投稿時）と admin.py（運営の非表示／再表示時）の両方から呼ぶ単一の正本。
集計対象は「顧客→業者（reviewer_type="user"）かつ非表示でない」レビューのみ
（alembic 0040 の全業者再計算・0041 / 0042 の補正も同じ母集団）。不変条件 review_count = good_count + improve_count。
呼び出し側は対象 operators 行を ``with_for_update`` でロック済みであること
（同一業者への同時投稿で lost update が起きないようにする。security review M-4）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bid import Bid
from app.db.models.operator import Operator
from app.db.models.transaction import Review, Transaction

LATEST_COMMENT_MAX_LEN = 200


async def recalc_operator_review_stats(session: AsyncSession, operator_id: uuid.UUID) -> Operator | None:
    """対象業者の行を排他ロックし、公開対象レビューから集計値を再計算して書き戻す。

    commit は呼び出し側が行う。業者が存在しなければ None。
    """
    operator = await session.get(Operator, operator_id, with_for_update=True)
    if operator is None:
        return None

    base = (
        select(Review)
        .join(Transaction, Review.transaction_id == Transaction.id)
        .join(Bid, Transaction.bid_id == Bid.id)
        .where(
            Bid.operator_id == operator_id,
            Review.reviewer_type == "user",
            Review.hidden_at.is_(None),
        )
    )
    # 件数を1回のクエリで取る。maintain_column_froms=True で元の FROM（reviews）を保ったまま
    # 列だけ差し替える（base の JOIN・WHERE がそのまま効き、reviews が再結合されて
    # 非表示・業者→顧客レビューまで混ざることはない）。verdict は alembic 0042 で NOT NULL。
    good_count, improve_count = (
        await session.execute(
            base.with_only_columns(
                func.count().filter(Review.verdict == "good"),
                func.count().filter(Review.verdict == "improve"),
                maintain_column_froms=True,
            )
        )
    ).one()
    latest_comment = await session.scalar(
        base.with_only_columns(Review.comment)
        .where(Review.comment.is_not(None), func.trim(Review.comment) != "")
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(1)
    )

    operator.good_count = int(good_count or 0)
    operator.improve_count = int(improve_count or 0)
    # verdict は good / improve のどちらかに必ず決まるため、合計が公開中の件数そのもの。
    operator.review_count = operator.good_count + operator.improve_count
    # DB 側の trim は半角スペースのみのため、Python 側で改行・タブも含めて整えて空なら None。
    operator.latest_review_comment = (
        (latest_comment.strip()[:LATEST_COMMENT_MAX_LEN] or None) if latest_comment else None
    )
    return operator
