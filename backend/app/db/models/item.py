"""Item モデル — ユーザーが撮影した売却対象の品目。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.models.enums import CategoryTier, ItemCondition

if TYPE_CHECKING:
    from app.db.models.assessment import Assessment


class Item(Base, TimestampMixin):
    """ユーザーが撮影し AI が一次判定した品目。

    ``category_tier`` がルーティング判定の主キーとなる（ハンドオフ §1-2）。
    車・不動産など Tier 固有の属性（年式・走行距離・面積など）はスキーマを
    肥大させないため ``attributes`` (JSONB) に格納する。
    """

    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # ルーティングの基軸となる粗カテゴリ（AI 判定）。
    category_tier: Mapped[CategoryTier] = mapped_column(
        pg_enum(CategoryTier), nullable=False, index=True
    )
    # AI が判定した品目名（例: "iPhone 13 Pro 128GB"）。
    detected_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # AI が判定した細分類ラベル（例: "スマートフォン"）。任意。
    detected_category_label: Mapped[str | None] = mapped_column(String(128))
    # コンディション。未判定時は UNKNOWN。
    condition: Mapped[ItemCondition] = mapped_column(
        pg_enum(ItemCondition), nullable=False, default=ItemCondition.UNKNOWN
    )
    # コンディション判定の信頼度（0.0–1.0）。
    condition_confidence: Mapped[float | None] = mapped_column(Float)
    # アップロード画像のオブジェクトストレージキー。
    image_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # Tier 固有の可変属性（brand / model / year / mileage / area など）。
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # 1 品目に対し複数回の査定を許容する（再査定・相場変動の追跡）。
    assessments: Mapped[list[Assessment]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
