"""OperatorProfile モデル — 業者プロフィール（公開・編集可能項目）。

Operator 本体（審査確定項目: company_name, license_number 等）とは 1:1 で分離する。
審査確定項目は operators 側でのみ更新可能とし、本テーブルは業者自身が編集できる
公開プロフィール項目のみを保持する。
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class OperatorProfile(Base, TimestampMixin):
    __tablename__ = "operator_profiles"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("operators.id", ondelete="CASCADE"),
        primary_key=True,
    )
    areas: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    categories: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    strong_categories: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    staff_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    business_hours: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    intro_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_stats: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_reviews: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_message: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    accept_unsellable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # relations
    operator = relationship("Operator")
