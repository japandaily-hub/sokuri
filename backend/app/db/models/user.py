"""User モデル — カタヅケ利用者（role=\'admin\' で管理者）。"""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """email + password 認証のユーザーアカウント。"""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
