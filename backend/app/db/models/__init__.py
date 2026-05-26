"""ORM モデルパッケージ。

Alembic の autogenerate および ``Base.metadata`` の完全性のため、本パッケージの
import 時に全モデルモジュールを読み込む。
"""

from __future__ import annotations

from app.db.base import Base
from app.db.models.album import Album, AlbumItem
from app.db.models.assessment import Assessment, AssessmentRecommendation
from app.db.models.channel import AffiliateMeta, Channel
from app.db.models.defect import DefectEvidence
from app.db.models.enums import (
    AffiliateNetwork,
    AlbumStatus,
    AssessmentStatus,
    CategoryTier,
    ChannelType,
    ItemCondition,
    RewardType,
    RoutingMethod,
)
from app.db.models.item import Item
from app.db.models.routing import RoutingRule

__all__ = [
    "Base",
    "Item",
    "Assessment",
    "AssessmentRecommendation",
    "Album",
    "AlbumItem",
    "Channel",
    "AffiliateMeta",
    "DefectEvidence",
    "RoutingRule",
    "CategoryTier",
    "ItemCondition",
    "ChannelType",
    "AssessmentStatus",
    "AlbumStatus",
    "RoutingMethod",
    "AffiliateNetwork",
    "RewardType",
]
