"""案件写真の商品ごとのアルバム化 — case_items 追加 + case_photos.case_item_id 追加

Revision ID: 0015_case_items
Revises: 0014_operator_license_image
Create Date: 2026-09-01

背景（案件写真を商品ごとにアルバム化する機能）:
入札・成約（Bid/Transaction）の単位は引き続き「1案件」のまま変更しない。
撮影・AI解析・表示の整理単位として、案件配下に商品（CaseItem）を新設し、
case_photos から商品への任意の紐づけ（case_item_id）を追加する。

設計判断:
- case_items.ai_condition は ItemCondition を ORM 型として再利用するが、
  DDL は native_enum=False（VARCHAR(32)）に固定する。Album 系の pg_enum で
  Railway alembic デプロイ障害が起きた記録（app/db/models/__init__.py 参照）が
  あるため、ネイティブ ENUM 型は本テーブルでも作らない。
- backfill は行わない。既存の case_photos 行は case_item_id=NULL のまま残り、
  レガシー案件は items=[] として引き続き扱われる。
- alembic revision id は過去の alembic_version 全断障害の再発防止のため
  32文字以内を厳守する（本リビジョンは15文字）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_case_items"
down_revision: str | None = "0014_operator_license_image"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_now = sa.text("now()")


def _ts() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
    )


def upgrade() -> None:
    # ── case_items（商品アルバム）──────────────────────────────────────
    op.create_table(
        "case_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_detected_name", sa.String(64), nullable=True),
        sa.Column("ai_condition", sa.String(32), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_case_items"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"],
            ondelete="CASCADE",
            name="fk_case_items_case_id_cases",
        ),
        sa.UniqueConstraint("id", "case_id", name="uq_case_items_id"),
    )
    op.create_index("ix_case_items_case_id", "case_items", ["case_id"])
    op.create_index(
        "ix_case_items_case_id_sort_order", "case_items", ["case_id", "sort_order"]
    )

    # ── case_photos.case_item_id（商品への任意の紐づけ）──────────────────
    op.add_column(
        "case_photos", sa.Column("case_item_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_case_photos_case_item_id_case_items",
        "case_photos",
        "case_items",
        ["case_item_id", "case_id"],
        ["id", "case_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_case_photos_case_item_id",
        "case_photos",
        ["case_item_id"],
        postgresql_where=sa.text("case_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_case_photos_case_item_id", table_name="case_photos")
    op.drop_constraint(
        "fk_case_photos_case_item_id_case_items", "case_photos", type_="foreignkey"
    )
    op.drop_column("case_photos", "case_item_id")

    op.drop_index("ix_case_items_case_id_sort_order", table_name="case_items")
    op.drop_index("ix_case_items_case_id", table_name="case_items")
    op.drop_table("case_items")
