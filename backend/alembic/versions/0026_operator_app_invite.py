"""operator_applications に invite_code を追加（承認発行コード→本登録業者の逆引き用）

Revision ID: 0026_operator_app_invite
Revises: 0025_user_suspend
Create Date: 2026-09-04

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは25文字）。

背景: r5-ops.md M-4「OperatorApplication.operator_id が全経路で書き込まれず常に
null」の是正。承認（approve）時に発行した招待コードを ``invite_code`` に控えておき、
業者本人が /operator/signup をその招待コードで完了した時点で該当申込を逆引きし、
operator_id を書き込めるようにする。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_operator_app_invite"
down_revision: str | None = "0025_user_suspend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operator_applications",
        sa.Column("invite_code", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_operator_applications_invite_code"),
        "operator_applications",
        ["invite_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_operator_applications_invite_code"), table_name="operator_applications"
    )
    op.drop_column("operator_applications", "invite_code")
