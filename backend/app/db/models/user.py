"""User モデル — カタヅケ利用者（role=\'admin\' で管理者）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String
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

    # ── プロフィール（マイページ /users/me/profile で編集） ─────────────
    # name は「表示用キャッシュ」として残し、プロフィール更新時に
    # f"{family_name} {given_name}" で同期更新する（既存参照箇所との互換維持）。
    family_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    given_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    family_name_kana: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    given_name_kana: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    residence_area: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # 論理削除マーカー（退会済みアカウントの旧JWTを deps.py で即時失効させるゲートに使用）。
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # パスワード変更時刻（JWT失効ゲート用。iat がこれより古いトークンを deps.py で拒否する）。
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
