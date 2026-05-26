"""ドメインの列挙型（カテゴリ分類体系・状態・チャネル種別など）。

ハンドオフ §1-1 のカテゴリ表を基準に定義する。すべて ``str`` を継承し、DB には
``value`` を保存する（:func:`app.db.base.pg_enum` 参照）。
"""

from __future__ import annotations

import enum


class CategoryTier(str, enum.Enum):
    """売却ルーティングの基軸となる粗カテゴリ（ハンドオフ §1-1）。

    細分類（品目名）は :class:`~app.db.models.item.Item` の文字列カラムで保持し、
    ルーティング判定は本 Tier を主キーに行う。
    """

    HIGH_VALUE_STANDARD = "high_value_standard"  # 高単価標準品: ガジェット/ブランド/貴金属
    LOW_VALUE_DAILY = "low_value_daily"          # 低単価生活品: 生活雑貨/家電/家具
    VEHICLE = "vehicle"                          # 車
    REAL_ESTATE = "real_estate"                  # 不動産


class ItemCondition(str, enum.Enum):
    """品目のコンディション。順序比較は :data:`CONDITION_RANK` を用いる。"""

    NEW = "new"
    LIKE_NEW = "like_new"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNKNOWN = "unknown"


# コンディションの順序（ルーティングルールの下限/上限比較に使用）。
# UNKNOWN は順序を持たないため -1（範囲マッチから除外する番兵値）。
CONDITION_RANK: dict[ItemCondition, int] = {
    ItemCondition.POOR: 0,
    ItemCondition.FAIR: 1,
    ItemCondition.GOOD: 2,
    ItemCondition.LIKE_NEW: 3,
    ItemCondition.NEW: 4,
    ItemCondition.UNKNOWN: -1,
}


class ChannelType(str, enum.Enum):
    """送客先チャネルの種別（ハンドオフ §1-1 / §2）。"""

    BUYER_ASP = "buyer_asp"                          # 買取業者 ASP 送客
    FLEA_MARKET = "flea_market"                      # フリマ送客（収益化不可・§2）
    BULK_BUYER = "bulk_buyer"                        # まとめ買取送客
    CAR_APPRAISAL = "car_appraisal"                  # 車一括査定送客
    REAL_ESTATE_APPRAISAL = "real_estate_appraisal"  # 不動産一括査定送客
    OWNED_AUCTION = "owned_auction"                  # Layer 2 自社オークション（将来）


class AssessmentStatus(str, enum.Enum):
    """査定処理の状態。"""

    PENDING = "pending"      # vision 解析・相場推定が未完
    COMPLETED = "completed"  # 相場・推奨チャネル確定
    FAILED = "failed"        # 解析失敗（failure_reason に詳細）


class RoutingMethod(str, enum.Enum):
    """ルーティング判定の出自（監査用・ハンドオフ §6-2）。"""

    RULE = "rule"      # 決定論的ルールのみで解決
    LLM = "llm"        # LLM フォールバックで解決
    HYBRID = "hybrid"  # ルール + LLM 併用


class AffiliateNetwork(str, enum.Enum):
    """アフィリエイト ASP（ハンドオフ §2）。"""

    A8_NET = "a8_net"
    AFB = "afb"
    ACCESSTRADE = "accesstrade"
    RENTRACKS = "rentracks"
    DIRECT = "direct"  # ASP を介さない直接提携


class RewardType(str, enum.Enum):
    """アフィリエイト報酬の課金形態。"""

    CPA = "cpa"            # 成果報酬（査定申込・成約）
    CPL = "cpl"            # リード報酬
    REVSHARE = "revshare"  # 売上シェア
