"""Channel / AffiliateMeta モデル — 送客先チャネルとその収益化メタ情報。

設計判断: 査定の中立性（Assessment）と送客の広告性を *データ構造上で分離* する
ため（ハンドオフ §3 ステマ規制対応・Phase 1 CONSTRAINT）、ASP・報酬・PR 表記は
:class:`Channel` 本体ではなく独立した :class:`AffiliateMeta` に切り出す。
フリマ等の収益化不可チャネル（§2）は ``affiliate_meta`` を持たない（NULL）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.models.enums import AffiliateNetwork, CategoryTier, ChannelType, RewardType

if TYPE_CHECKING:
    pass


class Channel(Base, TimestampMixin):
    """売却の送客先チャネル（買取 ASP / フリマ / 車・不動産一括査定 / 自社オークション）。"""

    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # 安定した一意コード（シード/参照用、例: "mota_car"）。
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_type: Mapped[ChannelType] = mapped_column(
        pg_enum(ChannelType), nullable=False, index=True
    )
    # 主に扱う Tier（情報用）。権威的な Tier→Channel 対応は RoutingRule が持つ。
    primary_category_tier: Mapped[CategoryTier | None] = mapped_column(pg_enum(CategoryTier))
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 同 Tier 内の既定表示順（小さいほど上位）。
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # 収益化メタ情報（収益化不可チャネルは NULL）。1:1。
    affiliate_meta: Mapped[AffiliateMeta | None] = relationship(
        back_populates="channel",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AffiliateMeta(Base, TimestampMixin):
    """チャネルの収益化メタ情報（ASP・報酬・PR 表記フラグ）。

    査定の中立性と分離するため :class:`Channel` から独立させた専用テーブル。
    """

    __tablename__ = "affiliate_meta"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 1 チャネルにつき高々 1 件（unique 制約で 1:1 を保証）。
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    asp_network: Mapped[AffiliateNetwork] = mapped_column(pg_enum(AffiliateNetwork), nullable=False)
    # ASP 側のプログラム識別子。
    program_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 送客リンク生成用 URL テンプレート（Phase 4 で展開）。
    tracking_url_template: Mapped[str] = mapped_column(String(2048), nullable=False)
    reward_type: Mapped[RewardType] = mapped_column(pg_enum(RewardType), nullable=False)
    # 報酬レンジ（JPY、整数。例: 800〜6,600 円）。
    reward_amount_min: Mapped[int | None] = mapped_column(BigInteger)
    reward_amount_max: Mapped[int | None] = mapped_column(BigInteger)
    reward_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="JPY")
    # PR 表記フラグ。アフィリエイト送客は原則 True（ステマ規制 §3）。
    requires_pr_label: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pr_label_text: Mapped[str] = mapped_column(String(32), nullable=False, default="PR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    channel: Mapped[Channel] = relationship(back_populates="affiliate_meta")
