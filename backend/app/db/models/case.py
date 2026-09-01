"""Case / CaseItem / CasePhoto モデル — カタヅケ案件とその商品・写真。

案件写真の商品ごとのアルバム化（撮影・AI解析・表示の整理）:
- 入札・成約（Bid/Transaction）の単位は引き続き「1案件」。CaseItem は表示・AI解析上の
  グルーピング単位であり、取引の単位ではない。
- CasePhoto.case_item_id は NULL 許容（未分類写真として case 直下に残せる）。
  レガシー案件（本機能導入前に作成された案件）は case_item_id=NULL のまま残り、
  items=[] として扱われる（backfill しない）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.models.enums import ItemCondition

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
    items: Mapped[list["CaseItem"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseItem.sort_order",
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


class CaseItem(Base, TimestampMixin):
    """案件配下の商品（アルバム単位）。撮影・AI解析・表示をこの単位で整理する。

    入札・成約の単位ではない（あくまで Case に対する表示・解析のグルーピング）。
    """

    __tablename__ = "case_items"
    __table_args__ = (
        Index("ix_case_items_case_id_sort_order", "case_id", "sort_order"),
        # 複合FK (case_photos.case_item_id, case_photos.case_id) の参照先として
        # (id, case_id) の複合ユニーク制約が必要（他案件の item_id を指す写真を
        # DB制約レベルで拒否するため）。
        UniqueConstraint("id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_detected_name: Mapped[str | None] = mapped_column(String(64))
    # ItemCondition を ORM 型として再利用するが、DDL は native_enum=False
    # （pg_enum が生成する VARCHAR(32)）に固定する。Album 系の pg_enum で
    # Railway デプロイ障害が起きた記録があるため、ネイティブ ENUM 型は作らない。
    ai_condition: Mapped[ItemCondition | None] = mapped_column(pg_enum(ItemCondition))
    ai_summary: Mapped[str | None] = mapped_column(Text)

    case: Mapped[Case] = relationship(back_populates="items")
    # foreign_keys を case_item_id のみに限定する: case_photos.case_id は
    # 既存の Case.photos / CasePhoto.case 関係が単独FK(case_id→cases.id)で
    # 既に管理している列であり、同じ列を本関係（複合FK経由）でも同期対象に
    # すると SQLAlchemy が "conflicting relationship" 警告/不整合を起こす。
    # DB制約（複合FK）自体は case_photos.__table_args__ 側でそのまま有効。
    photos: Mapped[list["CasePhoto"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CasePhoto.sort_order",
        foreign_keys="CasePhoto.case_item_id",
    )


class CasePhoto(Base, TimestampMixin):
    """案件に紐づく写真。sort_order の昇順で表示する。

    ``case_item_id`` は商品グループへの任意の紐づけ（NULL = 未分類写真）。
    複合FK (case_item_id, case_id) → case_items(id, case_id) により、
    他案件の CaseItem を指すことは DB 制約レベルで拒否される。
    """

    __tablename__ = "case_photos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_item_id", "case_id"],
            ["case_items.id", "case_items.case_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_case_photos_case_item_id",
            "case_item_id",
            postgresql_where=text("case_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    case: Mapped[Case] = relationship(back_populates="photos")
    item: Mapped["CaseItem | None"] = relationship(
        back_populates="photos", foreign_keys=[case_item_id]
    )
