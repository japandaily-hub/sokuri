"""ORM モデルパッケージ。

Alembic の autogenerate および ``Base.metadata`` の完全性のため、本パッケージの
import 時に全モデルモジュールを読み込む。
"""

from __future__ import annotations

from app.db.base import Base

# NOTE: Album / AlbumItem / AlbumStatus は Phase 2 機能（一括査定アルバム永続化）。
# Railway alembic デプロイで pg_enum(AlbumStatus) 関連の問題が解消するまで
# モデル import を一時停止。Phase 2 復旧時に下の commented-out import を有効化。
# from app.db.models.album import Album, AlbumItem
from app.db.models.assessment import Assessment, AssessmentRecommendation
from app.db.models.channel import AffiliateMeta, Channel
from app.db.models.defect import DefectEvidence
from app.db.models.enums import (
    AffiliateNetwork,
    AssessmentStatus,
    CategoryTier,
    ChannelType,
    ItemCondition,
    RewardType,
    RoutingMethod,
)
# from app.db.models.enums import AlbumStatus  # Phase 2 で復活
from app.db.models.item import Item
from app.db.models.routing import RoutingRule

__all__ = [
    "Base",
    "Item",
    "Assessment",
    "AssessmentRecommendation",
    "Channel",
    "AffiliateMeta",
    "DefectEvidence",
    "RoutingRule",
    "CategoryTier",
    "ItemCondition",
    "ChannelType",
    "AssessmentStatus",
    "RoutingMethod",
    "AffiliateNetwork",
    "RewardType",
]
