"""Invite モデル — 管理者が発行する業者招待コード。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Invite(Base, TimestampMixin):
    """業者登録用の招待コード。1 コード 1 業者（used_at で消込）。"""

    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))  # 宛先想定（任意）
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="SET NULL"), nullable=True
    )
