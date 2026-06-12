"""Operator モデル — 片付け業者。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.bid import Bid
    from app.db.models.transaction import ReductionRequest


class Operator(Base, TimestampMixin):
    """片付け業者アカウント。"""

    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    license_number: Mapped[str | None] = mapped_column(String(128))
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rating: Mapped[float | None] = mapped_column(Float)
    cancel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    invite_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # 業者ログイン用（0004 で追加。招待登録時に必須化はアプリ層で行う）
    password_hash: Mapped[str | None] = mapped_column(String(512))

    # relations
    bids: Mapped[list[Bid]] = relationship(
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reduction_requests: Mapped[list[ReductionRequest]] = relationship(
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
