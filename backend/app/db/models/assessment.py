"""Assessment / AssessmentRecommendation モデル — 査定結果と送客先推奨。

設計判断（ハンドオフ §3 ステマ規制・Phase 1 CONSTRAINT）:
- :class:`Assessment` は *中立な相場* のみを保持する。広告要素を一切含まない。
- 送客の広告性（有料枠フラグ・送客 URL）は :class:`AssessmentRecommendation`
  に分離する。1 査定が複数チャネルを推奨し得る（§1-1 低単価生活品の例）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.models.enums import AssessmentStatus, RoutingMethod

if TYPE_CHECKING:
    from app.db.models.channel import Channel
    from app.db.models.defect import DefectEvidence
    from app.db.models.item import Item
    from app.db.models.routing import RoutingRule


class Assessment(Base, TimestampMixin):
    """品目 1 件に対する査定。相場推定（中立）とルーティング監査情報を保持する。"""

    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint(
            "estimated_price_min IS NULL OR estimated_price_min >= 0",
            name="estimated_price_min_non_negative",
        ),
        CheckConstraint(
            "estimated_price_min IS NULL OR estimated_price_max IS NULL "
            "OR estimated_price_min <= estimated_price_max",
            name="estimated_price_min_le_max",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AssessmentStatus] = mapped_column(
        pg_enum(AssessmentStatus), nullable=False, default=AssessmentStatus.PENDING
    )

    # --- 中立な相場情報（広告要素と分離） ---
    estimated_price_min: Mapped[int | None] = mapped_column(BigInteger)
    estimated_price_max: Mapped[int | None] = mapped_column(BigInteger)
    price_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="JPY")
    price_basis: Mapped[dict | None] = mapped_column(JSONB)

    # --- ルーティング監査情報（§6-2 ハイブリッド方式の出自記録） ---
    routing_method: Mapped[RoutingMethod | None] = mapped_column(pg_enum(RoutingMethod))
    llm_model: Mapped[str | None] = mapped_column(String(64))
    raw_vision_payload: Mapped[dict | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    item: Mapped["Item"] = relationship(back_populates="assessments")
    recommendations: Mapped[list["AssessmentRecommendation"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AssessmentRecommendation.rank",
    )
    defect_evidences: Mapped[list["DefectEvidence"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AssessmentRecommendation(Base, TimestampMixin):
    """査定が生成した送客先チャネルの推奨（1 査定に対し 1..N 件）。"""

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "rank"),
        CheckConstraint("rank >= 1", name="rank_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_routing_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("routing_rules.id", ondelete="SET NULL")
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reason: Mapped[str | None] = mapped_column(Text)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outbound_url: Mapped[str | None] = mapped_column(String(2048))

    assessment: Mapped["Assessment"] = relationship(back_populates="recommendations")
    channel: Mapped["Channel"] = relationship()
    source_routing_rule: Mapped["RoutingRule | None"] = relationship()
