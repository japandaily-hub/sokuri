"""users に is_suspended / suspended_at / suspended_reason を追加（依頼者アカウントの利用停止）

Revision ID: 0025_user_suspend
Revises: 0024_operator_review_stats
Create Date: 2026-09-04

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは18文字）。

背景: 運営導線監査（r3-verify-operator.md ADD-2）で確定した「依頼者アカウントの
利用停止手段が API・UI・DB のいずれにも存在しない」を解消する。業者側の
``Operator.is_suspended``（0016 相当）と同形のカラムを users にも追加し、
理由（``suspended_reason``）と停止時刻（``suspended_at``）も併せて記録する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_user_suspend"
down_revision: str | None = "0024_operator_review_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("suspended_reason", sa.String(length=200), nullable=True),
    )
    op.create_index(op.f("ix_users_is_suspended"), "users", ["is_suspended"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_is_suspended"), table_name="users")
    op.drop_column("users", "suspended_reason")
    op.drop_column("users", "suspended_at")
    op.drop_column("users", "is_suspended")
