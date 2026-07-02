"""operators に利用規約・プライバシーポリシー同意の証跡カラムを追加。

Revision ID: 0007_operator_terms_agreement
Revises: 0006_vendor_status
Create Date: 2026-07-02

変更内容:
1. agreed_terms_version VARCHAR(32) NULL 追加（同意した規約バージョン）
2. agreed_at TIMESTAMP WITH TIME ZONE NULL 追加（同意日時、UTC）

※ 既存行はいずれも NULL のまま（過去の登録は同意証跡なしとして扱う）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_operator_terms_agreement"
down_revision: str | None = "0006_vendor_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators",
        sa.Column("agreed_terms_version", sa.String(32), nullable=True),
    )
    op.add_column(
        "operators",
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operators", "agreed_at")
    op.drop_column("operators", "agreed_terms_version")
