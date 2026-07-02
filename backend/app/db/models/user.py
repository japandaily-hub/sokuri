"""User モデル — カタヅケ利用者（role=\'admin\' で管理者）。"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """email + password 認証のユーザーアカウント。

    LINEログイン専用ユーザー（password_hash=None）も許容する（line_user_id 参照）。
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # LINE専用アカウントはパスワードを持たないため nullable。
    password_hash: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    # LINE Login の userId（LINE Push通知の宛先にも使用）。未連携は NULL。
    line_user_id: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
