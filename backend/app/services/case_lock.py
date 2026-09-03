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


async def lock_case_row(session: AsyncSession, case_id: uuid.UUID) -> None:
    """親Case行をロックする（TOCTOU対策）。

    select（落札）と cancel_case（出品取り下げ）はいずれも同一案件・同一入札の
    並行更新を伴う。ロック取得のみが目的のため取得列は主キーのみに絞る。
    """
    await session.execute(select(Case.id).where(Case.id == case_id).with_for_update())
