"""RoutingRule モデル — カテゴリ→チャネル判定ルール。本プロダクトの心臓（§1-2）。

ルールは決定論的に評価され、判定根拠を監査可能にする（ハンドオフ §3 ステマ規制）。
1 件の品目/査定に対し複数ルールがマッチし得る（例: 低単価生活品 → フリマ送客
＋ まとめ買取送客）。各ルールは 1 チャネルへの推奨を ``recommendation_rank``
付きで生成する。
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.models.channel import Channel
from app.db.models.enums import CategoryTier, ItemCondition


class RoutingRule(Base, TimestampMixin):
    """「マッチ条件 → 推奨チャネル」を宣言的に表現するルーティングテーブルの 1 行。

    マッチ条件カラムは NULL をワイルドカード（無条件一致）として扱う。
    ハイブリッド方式（§6-2）では本ルールが権威的判定であり、未マッチ時のみ
    LLM フォールバックへ委譲する。
    """

    __tablename__ = "routing_rules"
    __table_args__ = (
        CheckConstraint(
            "match_price_min IS NULL OR match_price_min >= 0",
            name="match_price_min_non_negative",
        ),
        CheckConstraint(
            "match_price_min IS NULL OR match_price_max IS NULL "
            "OR match_price_min <= match_price_max",
            name="match_price_min_le_max",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # 評価順序（小さいほど先に評価。同 Tier で複数ルールが並ぶ際の優先度）。
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # --- マッチ条件（NULL = ワイルドカード） ---
    match_category_tier: Mapped[CategoryTier | None] = mapped_column(
        pg_enum(CategoryTier), index=True
    )
    # コンディション下限/上限。順序比較は enums.CONDITION_RANK を使用。
    match_min_condition: Mapped[ItemCondition | None] = mapped_column(pg_enum(ItemCondition))
    match_max_condition: Mapped[ItemCondition | None] = mapped_column(pg_enum(ItemCondition))
    # 推定相場による絞り込み（JPY 整数）。
    match_price_min: Mapped[int | None] = mapped_column(BigInteger)
    match_price_max: Mapped[int | None] = mapped_column(BigInteger)
    # 拡張用の属性述語（attributes に対する追加条件）。
    match_attributes: Mapped[dict | None] = mapped_column(JSONB)

    # --- 出力 ---
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 本ルールが生成する推奨の順位（1 = 最優先）。
    recommendation_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 中立な推奨理由のテンプレート（プレースホルダ展開可）。
    reason_template: Mapped[str | None] = mapped_column(Text)

    channel: Mapped[Channel] = relationship()
