"""add albums and album_items tables

Revision ID: 0003_add_albums
Revises: 0002_add_defect_evidence
Create Date: 2026-05-26

「まとめてソクウリ」一括査定アルバム機能（ADR-002 Phase 2）。
albums: 複数 assessment の束、ユーザー連絡先（業者非開示）を保持。
album_items: album → assessment の中間テーブル（順序保持）。

Phase 2 では業者入札（bids / businesses）は未実装。Wizard of Oz 運用。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_albums"
down_revision: str | None = "0002_add_defect_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_now = sa.text("now()")

ALBUM_STATUS_VALUES = ("draft", "submitted", "bidding", "matched", "closed", "cancelled")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
    )


def upgrade() -> None:
    # ENUM 型 albumstatus を idempotent に作成。
    # 過去の失敗デプロイで ENUM だけ残るケースがあるため、
    # SQLAlchemy の checkfirst ではなく PL/pgSQL の例外捕捉で確実に冪等化する。
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE albumstatus AS ENUM "
        "('draft', 'submitted', 'bidding', 'matched', 'closed', 'cancelled'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # albums
    op.create_table(
        "albums",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lead_email", sa.String(length=320), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                *ALBUM_STATUS_VALUES,
                name="albumstatus",
                native_enum=True,
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "total_estimated_jpy",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_albums"),
        sa.CheckConstraint(
            "total_estimated_jpy >= 0",
            name="total_estimated_jpy_non_negative",
        ),
    )
    op.create_index("ix_albums_status", "albums", ["status"])

    # album_items
    op.create_table(
        "album_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("album_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_album_items"),
        sa.ForeignKeyConstraint(
            ["album_id"],
            ["albums.id"],
            ondelete="CASCADE",
            name="fk_album_items_album_id_albums",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments.id"],
            ondelete="RESTRICT",
            name="fk_album_items_assessment_id_assessments",
        ),
        sa.CheckConstraint("position >= 0", name="position_non_negative"),
    )
    op.create_index("ix_album_items_album_id", "album_items", ["album_id"])
    op.create_index("ix_album_items_assessment_id", "album_items", ["assessment_id"])


def downgrade() -> None:
    op.drop_index("ix_album_items_assessment_id", table_name="album_items")
    op.drop_index("ix_album_items_album_id", table_name="album_items")
    op.drop_table("album_items")
    op.drop_index("ix_albums_status", table_name="albums")
    op.drop_table("albums")
    sa.Enum(name="albumstatus").drop(op.get_bind(), checkfirst=True)
