"""Bid モデル — 業者による入札。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.case import Case
    from app.db.models.operator import Operator
    from app.db.models.transaction import Transaction


class Bid(Base, TimestampMixin):
    """業者が案件に対して行う入札。

    ``status`` の遷移:
      pending → selected（ユーザーが選択）
             └→ rejected（他社が選択または案件クローズ）

    1 案件につき 1 業者 1 入札のみ（uq_bids_case_operator 制約）。
    """

    __tablename__ = "bids"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 円
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )

    # relations
    case: Mapped[Case] = relationship(back_populates="bids")
    operator: Mapped[Operator] = relationship(back_populates="bids")
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="bid",
        uselist=False,
    )
