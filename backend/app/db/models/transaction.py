"""Transaction / ReductionRequest / Review / Cancellation モデル。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.bid import Bid
    from app.db.models.case import Case
    from app.db.models.operator import Operator


class Transaction(Base, TimestampMixin):
    """落札後の成約情報。1 案件につき最大 1 レコード。

    ``status`` の遷移:
      pending → visiting → completed
                        └→ cancelled
    """

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    bid_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bids.id", ondelete="RESTRICT"), nullable=False
    )
    initial_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)   # 落札額
    final_amount: Mapped[int | None] = mapped_column(BigInteger)              # 減額後確定額
    fee_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # プラットフォーム手数料
    visit_date: Mapped[date | None] = mapped_column(Date)
    visit_time_slot: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    # チャットの既読ポインタ（当事者双方）。相手が送った未読メッセージ数の算出に用いる。
    user_last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # relations
    case: Mapped[Case] = relationship(back_populates="transaction")
    bid: Mapped[Bid] = relationship(back_populates="transaction")
    reduction_requests: Mapped[list[ReductionRequest]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    cancellations: Mapped[list[Cancellation]] = relationship(
        back_populates="transaction",
    )


class ReductionRequest(Base, TimestampMixin):
    """業者による減額申請。

    現地訪問後に実際の荷物量が見積もりと乖離した場合に申請する。
    reason は必須（契約上の根拠として記録する）。

    ``status`` の遷移: pending → approved | rejected
    """

    __tablename__ = "reduction_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    original_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    # relations
    transaction: Mapped[Transaction] = relationship(back_populates="reduction_requests")
    operator: Mapped[Operator] = relationship(back_populates="reduction_requests")


class Review(Base, TimestampMixin):
    """成約後の双方向評価。reviewer_type ごとに 1 件のみ（ユニーク制約）。"""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'user' | 'operator'
    rating: Mapped[int] = mapped_column(Integer, nullable=False)             # 1–5
    comment: Mapped[str | None] = mapped_column(Text)

    # relations
    transaction: Mapped[Transaction] = relationship(back_populates="reviews")


class Cancellation(Base, TimestampMixin):
    """キャンセル記録。case_id / transaction_id は NULL 許容（削除後の履歴保全）。"""

    __tablename__ = "cancellations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cancelled_by: Mapped[str] = mapped_column(String(32), nullable=False)  # 'user'|'operator'|'admin'
    reason: Mapped[str | None] = mapped_column(Text)

    # relations
    case: Mapped[Case | None] = relationship(back_populates="cancellations")
    transaction: Mapped[Transaction | None] = relationship(back_populates="cancellations")
