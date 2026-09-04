"""Case行の排他ロック（TOCTOU対策）を提供する共有ユーティリティ。

bids.py（select_bid）と cases.py（cancel_case）はいずれも同一案件・同一入札の
並行更新（落札処理中に出品取り下げられる／出品取り下げ処理中に落札される、等）
を伴う。処理冒頭でCase行を明示ロックし、片方の処理が完了するまでもう片方を
待機させることで、この競合を防ぐ（設計指示に基づく実装）。両エンドポイントから
共有利用するため独立モジュールに切り出す（元は bids.py 内の private 関数
``_lock_case_row`` だったが、業者の入札取り下げ機能の撤去に伴い cases.py の
cancel_case からも同一のロック規約に参加する必要が生じたため移設した）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.case import Case
from app.db.models.transaction import Transaction


async def lock_case_row(session: AsyncSession, case_id: uuid.UUID) -> None:
    """親Case行をロックする（TOCTOU対策）。

    select（落札）と cancel_case（出品取り下げ）はいずれも同一案件・同一入札の
    並行更新を伴う。ロック取得のみが目的のため取得列は主キーのみに絞る。
    """
    await session.execute(select(Case.id).where(Case.id == case_id).with_for_update())


async def lock_transaction_rows(
    session: AsyncSession, txn_id: uuid.UUID
) -> uuid.UUID | None:
    """成約の状態遷移用に **Case → Transaction の順**で行ロックを取る（r6-backend M-1）。

    complete / cancel / confirm_schedule / 運営の強制終了（admin）は read→check→write が
    非原子で、「完了」と「キャンセル」の同時実行が後勝ちで互いに矛盾した状態
    （transactions.status="completed" なのに cancellations 行が在る等）を残しうる。

    ロック順序は既存規約（bids.select_bid・cases.cancel_case が Case を先に掴む）に
    必ず合わせること。Transaction を先に掴むとデッドロックを新規に作る。

    成約が存在しない場合は None を返す（404 への変換は呼び出し元の責務。エンドポイントごとに
    detail 文言が異なるため本関数では HTTPException を投げない）。
    元は transactions.py の private ``_lock_txn_rows`` だったが、admin の強制終了
    （r8-M5）からも同一のロック規約に参加する必要が生じたため移設した
    （``lock_case_row`` を bids.py から移設したときと同じ理由・同じ場所）。
    """
    case_id = await session.scalar(
        select(Transaction.case_id).where(Transaction.id == txn_id)
    )
    if case_id is None:
        return None
    await lock_case_row(session, case_id)
    # ロック取得のみが目的のため取得列は主キーのみに絞る（lock_case_row と同じ作法）。
    await session.execute(
        select(Transaction.id).where(Transaction.id == txn_id).with_for_update()
    )
    return case_id
