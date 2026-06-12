"""katadzuke schema — cases / operators / bids / transactions and related tables

Revision ID: 0004_katadzuke_schema
Revises: 0003_add_albums
Create Date: 2026-06-12

既存テーブル（items / assessments / channels / routing_rules / defect_evidences）は
変更しない。カタヅケ案件フローに必要な 8 テーブルを新規追加する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_katadzuke_schema"
down_revision: str | None = "0003_add_albums"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_now = sa.text("now()")


def _ts() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
    )


def upgrade() -> None:
    # ── 1. operators（業者）────────────────────────────────────────────
    op.create_table(
        "operators",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("license_number", sa.String(128), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("cancel_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("invite_code", sa.String(64), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_operators"),
        sa.UniqueConstraint("contact_email", name="uq_operators_contact_email"),
        sa.UniqueConstraint("invite_code", name="uq_operators_invite_code"),
    )
    op.create_index("ix_operators_invite_code", "operators", ["invite_code"])
    op.create_index("ix_operators_is_suspended", "operators", ["is_suspended"])

    # ── 2. cases（案件）────────────────────────────────────────────────
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),   # WEEK2 で認証追加後に非 NULL 化
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="'draft'"),
        sa.Column("prefecture", sa.String(32), nullable=False),
        sa.Column("city", sa.String(64), nullable=False),
        sa.Column("address_detail", sa.Text(), nullable=True),
        sa.Column("housing_type", sa.String(32), nullable=True),
        sa.Column("floor_plan", sa.String(32), nullable=True),
        sa.Column("floor_number", sa.Integer(), nullable=True),
        sa.Column("has_elevator", sa.Boolean(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_cases"),
        sa.CheckConstraint(
            "status IN ('draft','open','bidding','closed','cancelled')",
            name="ck_cases_status",
        ),
    )
    op.create_index("ix_cases_user_id", "cases", ["user_id"])
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_prefecture", "cases", ["prefecture"])

    # ── 3. case_photos（案件写真）──────────────────────────────────────
    op.create_table(
        "case_photos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_case_photos"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"],
            ondelete="CASCADE",
            name="fk_case_photos_case_id_cases",
        ),
    )
    op.create_index("ix_case_photos_case_id", "case_photos", ["case_id"])

    # ── 4. bids（入札）────────────────────────────────────────────────
    op.create_table(
        "bids",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_bids"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"],
            ondelete="CASCADE",
            name="fk_bids_case_id_cases",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["operators.id"],
            ondelete="CASCADE",
            name="fk_bids_operator_id_operators",
        ),
        sa.CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
        sa.CheckConstraint(
            "status IN ('pending','selected','rejected')",
            name="ck_bids_status",
        ),
        sa.UniqueConstraint("case_id", "operator_id", name="uq_bids_case_operator"),
    )
    op.create_index("ix_bids_case_id", "bids", ["case_id"])
    op.create_index("ix_bids_operator_id", "bids", ["operator_id"])
    op.create_index("ix_bids_status", "bids", ["status"])

    # ── 5. transactions（成約）────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("bid_id", sa.Uuid(), nullable=False),
        sa.Column("initial_amount", sa.BigInteger(), nullable=False),
        sa.Column("final_amount", sa.BigInteger(), nullable=True),
        sa.Column("fee_amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("visit_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"],
            ondelete="RESTRICT",
            name="fk_transactions_case_id_cases",
        ),
        sa.ForeignKeyConstraint(
            ["bid_id"], ["bids.id"],
            ondelete="RESTRICT",
            name="fk_transactions_bid_id_bids",
        ),
        sa.UniqueConstraint("case_id", name="uq_transactions_case_id"),  # 1案件=1成約
        sa.CheckConstraint("initial_amount > 0", name="ck_transactions_initial_amount_positive"),
        sa.CheckConstraint("fee_amount >= 0", name="ck_transactions_fee_amount_non_negative"),
        sa.CheckConstraint(
            "status IN ('pending','visiting','completed','cancelled')",
            name="ck_transactions_status",
        ),
    )
    op.create_index("ix_transactions_case_id", "transactions", ["case_id"])
    op.create_index("ix_transactions_status", "transactions", ["status"])

    # ── 6. reduction_requests（減額申請）──────────────────────────────
    op.create_table(
        "reduction_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("original_amount", sa.BigInteger(), nullable=False),
        sa.Column("requested_amount", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_reduction_requests"),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"],
            ondelete="CASCADE",
            name="fk_reduction_requests_transaction_id_transactions",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["operators.id"],
            ondelete="CASCADE",
            name="fk_reduction_requests_operator_id_operators",
        ),
        sa.CheckConstraint(
            "requested_amount > 0 AND requested_amount < original_amount",
            name="ck_reduction_requests_amount",
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_reduction_requests_status",
        ),
    )
    op.create_index(
        "ix_reduction_requests_transaction_id", "reduction_requests", ["transaction_id"]
    )

    # ── 7. reviews（評価）────────────────────────────────────────────
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_type", sa.String(32), nullable=False),  # 'user' | 'operator'
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"],
            ondelete="CASCADE",
            name="fk_reviews_transaction_id_transactions",
        ),
        sa.UniqueConstraint(
            "transaction_id", "reviewer_type", name="uq_reviews_transaction_reviewer"
        ),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating"),
        sa.CheckConstraint(
            "reviewer_type IN ('user','operator')",
            name="ck_reviews_reviewer_type",
        ),
    )
    op.create_index("ix_reviews_transaction_id", "reviews", ["transaction_id"])

    # ── 8. cancellations（キャンセル）────────────────────────────────
    op.create_table(
        "cancellations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("cancelled_by", sa.String(32), nullable=False),  # 'user'|'operator'|'admin'
        sa.Column("reason", sa.Text(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_cancellations"),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"],
            ondelete="SET NULL",
            name="fk_cancellations_case_id_cases",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"],
            ondelete="SET NULL",
            name="fk_cancellations_transaction_id_transactions",
        ),
        sa.CheckConstraint(
            "cancelled_by IN ('user','operator','admin')",
            name="ck_cancellations_cancelled_by",
        ),
    )
    op.create_index("ix_cancellations_case_id", "cancellations", ["case_id"])
    op.create_index("ix_cancellations_transaction_id", "cancellations", ["transaction_id"])


def downgrade() -> None:
    op.drop_table("cancellations")
    op.drop_table("reviews")
    op.drop_table("reduction_requests")
    op.drop_table("transactions")
    op.drop_table("bids")
    op.drop_table("case_photos")
    op.drop_table("cases")
    op.drop_table("operators")
