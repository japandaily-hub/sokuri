"""Case / CasePhoto モデル — カタヅケ案件とその写真。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.bid import Bid
    from app.db.models.transaction import Cancellation, Transaction


class Case(Base, TimestampMixin):
    """ユーザーが作成した片付け案件。

    ``status`` の遷移:
      draft → open → bidding → closed
                             └→ cancelled
    """

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # WEEK 2 で認証追加後に nullable=False + ForeignKey に変更する
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)

    # 利用目的 ("片付け整理" / "遺品整理" / "引っ越し" / "その他")
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)

    # 住所情報
    prefecture: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    address_detail: Mapped[str | None] = mapped_column(Text)

    # 住居情報
    housing_type: Mapped[str | None] = mapped_column(String(32))   # "一戸建て" / "マンション"
    floor_plan: Mapped[str | None] = mapped_column(String(32))     # "1K" / "3LDK" etc
    floor_number: Mapped[int | None] = mapped_column(Integer)
    has_elevator: Mapped[bool | None] = mapped_column(Boolean)

    # Gemini Vision が生成した案件サマリー
    ai_summary: Mapped[str | None] = mapped_column(Text)

    # relations
    photos: Mapped[list[CasePhoto]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CasePhoto.sort_order",
    )
    bids: Mapped[list[Bid]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="case",
        uselist=False,
    )
    cancellations: Mapped[list[Cancellation]] = relationship(
        back_populates="case",
    )


class CasePhoto(Base, TimestampMixin):
    """案件に紐づく写真。sort_order の昇順で表示する。"""

    __tablename__ = "case_photos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    case: Mapped[Case] = relationship(back_populates="photos")
