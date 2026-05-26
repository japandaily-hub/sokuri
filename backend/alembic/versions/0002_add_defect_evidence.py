"""add defect_evidences table

Revision ID: 0002_add_defect_evidence
Revises: 0001_initial_schema
Create Date: 2026-05-25

DefectEvidence モデル（Phase 4）に対応するテーブルを追加する。
assessment_id は assessments.id に CASCADE DELETE で参照する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_defect_evidence"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_now = sa.text("now()")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "defect_evidences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("image_object_key", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_defect_evidences"),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments.id"],
            ondelete="CASCADE",
            name="fk_defect_evidences_assessment_id_assessments",
        ),
    )
    op.create_index(
        "ix_defect_evidences_assessment_id",
        "defect_evidences",
        ["assessment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_defect_evidences_assessment_id", table_name="defect_evidences")
    op.drop_table("defect_evidences")
