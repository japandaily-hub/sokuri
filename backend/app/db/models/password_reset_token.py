"""PasswordResetToken モデル — メールによるパスワード再設定の1回限りトークン（alembic 0047）。

平文のトークンは保存しない。``token_hash`` に SHA-256 の16進表現（64文字）だけを持ち、
確定時は受け取った平文を同じ方法でハッシュ化して照合する（``services/password_reset.py``）。

- ``account_type`` は "user"（users）/ "operator"（operators）。依頼者・業者の2表を指すため
  外部キーは張らない（アカウントは論理削除のみで物理削除されないため、宙に浮く行は生じない）。
- ``used_at`` は「使用済み」または「新しい要求・確定によって無効化された」時刻。NULL の行だけが
  有効候補で、さらに ``expires_at`` が未来のものだけが使える。
- 同一アカウントの行は要求のたびに使用済み・期限切れを削除し、未使用の旧トークンを無効化する
  ため、1アカウントあたり高々2行（無効化済み1行＋最新1行）に保たれる。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: account_type の許容値（alembic 0047 の CHECK 制約と一致させる）。
PASSWORD_RESET_ACCOUNT_TYPES: tuple[str, ...] = ("user", "operator")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint("account_type IN ('user', 'operator')", name="account_type"),
        # 新しい要求時の旧トークン無効化・確定時の他トークン無効化（いずれもアカウント単位の
        # UPDATE / DELETE）で使う。token_hash はユニーク制約の索引で引く。
        Index("ix_password_reset_tokens_account", "account_type", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
