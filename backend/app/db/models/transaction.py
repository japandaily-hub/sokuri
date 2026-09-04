"""Transaction / ReductionRequest / Review / Cancellation モデル。"""

from __future__ import annotations

import uuid
from datetime import datetime
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
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
        # 業者の取引一覧（join Bid → Bid.operator_id 絞込）と FK の RESTRICT 検査が
        # 索引不在で全走査になるため索引を張る（r6-backend M-6 / alembic 0028）。
        Uuid, ForeignKey("bids.id", ondelete="RESTRICT"), nullable=False, index=True
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
    __table_args__ = (
        # 「未回答は取引あたり1件」をDBでも担保する（r6-backend M-4 / alembic 0028）。
        # アプリ層の in-memory 判定だけでは同時2リクエストで pending が2行でき、
        # 以後その判定により業者が恒久的に409で締め出される。
        # PostgreSQL / SQLite いずれも部分一意索引を解し、テストでも同じ制約が効く。
        Index(
            "uq_reduction_requests_pending",
            "transaction_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

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
    # 運営による論理削除（公開・集計から除外。物理削除はせず証跡を残す）。
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # relations
    transaction: Mapped[Transaction] = relationship(back_populates="reviews")


class Cancellation(Base, TimestampMixin):
    """キャンセル記録。case_id / transaction_id は NULL 許容（削除後の履歴保全）。"""

    __tablename__ = "cancellations"
    __table_args__ = (
        # 二重送信で同一成約のキャンセル記録が2行できると、業者の cancel_count が
        # 実際の2倍になり無実の業者に停止判断のペナルティが積み上がる（r6-backend M-2）。
        # transaction_id は NULL 許容（案件単位の取り下げ）だが、PostgreSQL/SQLite とも
        # NULL 同士は重複扱いしないため案件取り下げの記録は従来どおり複数行入る。
        # 制約: 将来「運営による代理キャンセル」で同一成約に2行目を積む運用が要る場合、
        # cancelled_by を含む複合一意へ緩める必要がある（現仕様では発生しない）。
        UniqueConstraint("transaction_id", name="uq_cancellations_transaction_id"),
    )

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
