"""bid_withdrawals テーブル追加 — 入札取り下げの監査証跡

Revision ID: 0019_bid_withdrawal_audit
Revises: 0018_bid_withdrawn
Create Date: 2026-09-03

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは25文字）。

背景（security review Medium指摘対応）:
業者による入札取り下げ（POST .../bids/{bid_id}/withdraw）は bids.status を
'withdrawn' に更新するのみで、いつ・誰が取り下げたかの記録が bids 行自体の
updated_at 以外に残らない。将来の不正調査・カスタマーサポート対応のために、
取り下げ1回につき1レコードの追記専用監査ログを新設する。

回数制限・閾値アラート等の業務ロジックはこのテーブルの追加スコープに含めない
（数値基準を推測で決めることになるため。設計指示に基づく）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_bid_withdrawal_audit"
down_revision: str | None = "0018_bid_withdrawn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_now = sa.text("now()")


def _ts() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "bid_withdrawals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bid_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_bid_withdrawals"),
        sa.ForeignKeyConstraint(
            ["bid_id"], ["bids.id"],
            ondelete="CASCADE",
            name="fk_bid_withdrawals_bid_id_bids",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"],
            ondelete="CASCADE",
            name="fk_bid_withdrawals_case_id_cases",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["operators.id"],
            ondelete="CASCADE",
            name="fk_bid_withdrawals_operator_id_operators",
        ),
    )
    op.create_index("ix_bid_withdrawals_bid_id", "bid_withdrawals", ["bid_id"])
    op.create_index("ix_bid_withdrawals_case_id", "bid_withdrawals", ["case_id"])
    op.create_index("ix_bid_withdrawals_operator_id", "bid_withdrawals", ["operator_id"])


def downgrade() -> None:
    op.drop_index("ix_bid_withdrawals_operator_id", table_name="bid_withdrawals")
    op.drop_index("ix_bid_withdrawals_case_id", table_name="bid_withdrawals")
    op.drop_index("ix_bid_withdrawals_bid_id", table_name="bid_withdrawals")
    op.drop_table("bid_withdrawals")
