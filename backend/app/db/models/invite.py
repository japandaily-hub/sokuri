"""Invite model."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Invite(Base, TimestampMixin):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="SET NULL"), nullable=True
    )
    lot_name: Mapped[Optional[str]] = mapped_column(String(128))
