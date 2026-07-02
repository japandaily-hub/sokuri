"""messages / operator_profiles テーブル新設・transactions に既読ポインタ等追加。

Revision ID: 0009_messages_schedule_and_operator_profiles
Revises: 0008_operator_applications_and_pending_status
Create Date: 2026-07-02

変更内容:
1. messages テーブル作成（成約チャット。+ 複合index transaction_id, created_at）。
2. transactions に user_last_read_at / operator_last_read_at / visit_time_slot 追加。
3. operator_profiles テーブル作成（業者プロフィール編集可能項目）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_messages_schedule_and_operator_profiles"
down_revision: str | None = "0008_operator_applications_and_pending_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. messages テーブル作成 ─────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="text"),
        sa.Column("meta", sa.JSON(), nullable=True),
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
            ["transaction_id"],
            ["transactions.id"],
            name="fk_messages_transaction_id_transactions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_transaction_id", "messages", ["transaction_id"])
    op.create_index(
        "ix_messages_transaction_id_created_at", "messages", ["transaction_id", "created_at"]
    )

    # ── 2. transactions へのカラム追加 ─────────────────────────────────
    op.add_column(
        "transactions", sa.Column("user_last_read_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "transactions",
        sa.Column("operator_last_read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("transactions", sa.Column("visit_time_slot", sa.String(32), nullable=True))

    # ── 3. operator_profiles テーブル作成 ────────────────────────────
    op.create_table(
        "operator_profiles",
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("areas", sa.JSON(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=True),
        sa.Column("strong_categories", sa.JSON(), nullable=True),
        sa.Column("staff_count", sa.Integer(), nullable=True),
        sa.Column("business_hours", sa.String(255), nullable=True),
        sa.Column("intro_message", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_stats", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_reviews", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_message", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("accept_unsellable", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            ["operator_id"],
            ["operators.id"],
            name="fk_operator_profiles_operator_id_operators",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("operator_id", name="pk_operator_profiles"),
    )


def downgrade() -> None:
    op.drop_table("operator_profiles")
    op.drop_column("transactions", "visit_time_slot")
    op.drop_column("transactions", "operator_last_read_at")
    op.drop_column("transactions", "user_last_read_at")
    op.drop_index("ix_messages_transaction_id_created_at", "messages")
    op.drop_index("ix_messages_transaction_id", "messages")
    op.drop_table("messages")
