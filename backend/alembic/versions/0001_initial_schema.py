"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUM_LEN = 32
_now = sa.text("now()")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("channel_type", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("primary_category_tier", sa.String(length=_ENUM_LEN), nullable=True),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_channels_channel_type", "channels", ["channel_type"])

    op.create_table(
        "affiliate_meta",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("asp_network", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("program_id", sa.String(length=128), nullable=False),
        sa.Column("tracking_url_template", sa.String(length=2048), nullable=False),
        sa.Column("reward_type", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("reward_amount_min", sa.BigInteger(), nullable=True),
        sa.Column("reward_amount_max", sa.BigInteger(), nullable=True),
        sa.Column("reward_currency", sa.String(length=3), nullable=False),
        sa.Column("requires_pr_label", sa.Boolean(), nullable=False),
        sa.Column("pr_label_text", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("channel_id"),
    )

    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("match_category_tier", sa.String(length=_ENUM_LEN), nullable=True),
        sa.Column("match_min_condition", sa.String(length=_ENUM_LEN), nullable=True),
        sa.Column("match_max_condition", sa.String(length=_ENUM_LEN), nullable=True),
        sa.Column("match_price_min", sa.BigInteger(), nullable=True),
        sa.Column("match_price_max", sa.BigInteger(), nullable=True),
        sa.Column("match_attributes", postgresql.JSONB(), nullable=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_rank", sa.Integer(), nullable=False),
        sa.Column("reason_template", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "match_price_min IS NULL OR match_price_min >= 0",
            name="match_price_min_non_negative",
        ),
        sa.CheckConstraint(
            "match_price_min IS NULL OR match_price_max IS NULL "
            "OR match_price_min <= match_price_max",
            name="match_price_min_le_max",
        ),
    )
    op.create_index("ix_routing_rules_is_active", "routing_rules", ["is_active"])
    op.create_index("ix_routing_rules_match_category_tier", "routing_rules", ["match_category_tier"])
    op.create_index("ix_routing_rules_channel_id", "routing_rules", ["channel_id"])

    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category_tier", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("detected_name", sa.String(length=255), nullable=False),
        sa.Column("detected_category_label", sa.String(length=128), nullable=True),
        sa.Column("condition", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("condition_confidence", sa.Float(), nullable=True),
        sa.Column("image_object_key", sa.String(length=512), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_items_category_tier", "items", ["category_tier"])

    op.create_table(
        "assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("estimated_price_min", sa.BigInteger(), nullable=True),
        sa.Column("estimated_price_max", sa.BigInteger(), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=False),
        sa.Column("price_basis", postgresql.JSONB(), nullable=True),
        sa.Column("routing_method", sa.String(length=_ENUM_LEN), nullable=True),
        sa.Column("llm_model", sa.String(length=64), nullable=True),
        sa.Column("raw_vision_payload", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "estimated_price_min IS NULL OR estimated_price_min >= 0",
            name="estimated_price_min_non_negative",
        ),
        sa.CheckConstraint(
            "estimated_price_min IS NULL OR estimated_price_max IS NULL "
            "OR estimated_price_min <= estimated_price_max",
            name="estimated_price_min_le_max",
        ),
    )
    op.create_index("ix_assessments_item_id", "assessments", ["item_id"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("source_routing_rule_id", sa.Uuid(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_sponsored", sa.Boolean(), nullable=False),
        sa.Column("outbound_url", sa.String(length=2048), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_routing_rule_id"], ["routing_rules.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("assessment_id", "rank"),
        sa.CheckConstraint("rank >= 1", name="rank_positive"),
    )
    op.create_index("ix_recommendations_assessment_id", "recommendations", ["assessment_id"])
    op.create_index("ix_recommendations_channel_id", "recommendations", ["channel_id"])


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_table("assessments")
    op.drop_table("items")
    op.drop_table("routing_rules")
    op.drop_table("affiliate_meta")
    op.drop_table("channels")
