"""user_identity_documents テーブルを新規作成する（依頼者の本人確認書類・審査書類）。

Revision ID: 0023_user_identity_documents
Revises: 0022_users_pii_columns
Create Date: 2026-09-04

背景（依頼者マイページ拡張 API）:
operators.license_image_data と同じ設計方針（画像本体をDBのBYTEAに直接保存し、
配信は認証必須の専用エンドポイントでのみ行う）を踏襲する。1提出につき1レコード
とし、再提出（rejected後の再申請）は新規レコードで表現する。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_user_identity_documents"
down_revision: str | None = "0022_users_pii_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_identity_documents",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("front_image_data", sa.LargeBinary(), nullable=True),
        sa.Column("front_image_content_type", sa.String(32), nullable=False),
        sa.Column("back_image_data", sa.LargeBinary(), nullable=True),
        sa.Column("back_image_content_type", sa.String(32), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reviewed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "doc_type IN ('drivers_license','my_number_card','passport',"
            "'residence_card','health_insurance_card')",
            name="ck_user_identity_documents_doc_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_user_identity_documents_status",
        ),
    )
    op.create_index(
        "ix_user_identity_documents_user_id", "user_identity_documents", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_identity_documents_user_id", table_name="user_identity_documents")
    op.drop_table("user_identity_documents")
