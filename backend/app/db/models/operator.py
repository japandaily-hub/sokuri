"""Operator model."""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Operator(Base, TimestampMixin):
    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    license_number: Mapped[Optional[str]] = mapped_column(String(128))
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rating: Mapped[Optional[float]] = mapped_column(Float)
    cancel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    invite_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    vendor_status: Mapped[str] = mapped_column(String(20), nullable=False, default="limited", index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(512))

    bids: Mapped[List["Bid"]] = relationship(
        "Bid",
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reduction_requests: Mapped[List["ReductionRequest"]] = relationship(
        "ReductionRequest",
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
