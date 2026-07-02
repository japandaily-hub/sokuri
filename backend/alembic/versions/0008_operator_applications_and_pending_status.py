"""operator_applications テーブル新設・vendor_status='limited' を 'pending' へ降格。

Revision ID: 0008_operator_applications_and_pending_status
Revises: 0007_operator_terms_agreement
Create Date: 2026-07-02

変更内容:
1. operator_applications テーブル作成（/business 業者事前申込フォームの保存先）。
2. データマイグレーション: 既存 operators.vendor_status='limited' を 'pending' に降格
   （全業者を管理者承認必須にする方針転換に伴う安全側の移行。自動昇格はしない）。

downgrade について:
- operator_applications テーブルの DROP のみ行う。
- vendor_status のデータ復元（pending → limited への巻き戻し）は行わない。
  'pending' に降格した時点でどのレコードが元々 'limited' だったかの情報は
  失われるため非可逆。'limited' という値自体はスキーマ上引き続き許容されるため、
  ロールバック時にアプリケーションが不整合を起こすことはない。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "0008_operator_applications_and_pending_status"
down_revision: str | None = "0007_operator_terms_agreement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. operator_applications テーブル作成 ──────────────────────
    op.create_table(
        "operator_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("representative_name", sa.String(255), nullable=False),
        sa.Column("registered_address", sa.String(512), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_phone", sa.String(32), nullable=False),
        sa.Column("license_number", sa.String(128), nullable=False),
        sa.Column("business_type", sa.String(16), nullable=True),
        sa.Column("service_area", sa.String(32), nullable=True),
        sa.Column("categories", sa.String(255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("invoice_number", sa.String(20), nullable=True),
        sa.Column("bank_account_enc", sa.Text(), nullable=True),
        sa.Column("agreed_terms_version", sa.String(32), nullable=True),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.String(500), nullable=True),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name="fk_operator_applications_reviewed_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operators.id"],
            name="fk_operator_applications_operator_id_operators",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operator_applications"),
    )
    op.create_index(
        "ix_operator_applications_status", "operator_applications", ["status"]
    )

    # ── 2. データマイグレーション: limited → pending（安全側・非可逆） ─────
    op.execute(
        text("UPDATE operators SET vendor_status = 'pending' WHERE vendor_status = 'limited'")
    )


def downgrade() -> None:
    # NOTE: vendor_status のデータ復元（pending → limited）は行わない（コメント参照）。
    op.drop_index("ix_operator_applications_status", "operator_applications")
    op.drop_table("operator_applications")
