"""invites に lot_name カラムを追加（バルクコード管理用）。

Revision ID: 0005_invites_lot_name
Revises: 0005_auth_tables
Create Date: 2026-06-15

NOTE: 正典repo(C:\sokuri)では auth_tables の revision ID が "0005_auth_tables" のため
      down_revision をそれに合わせる（OneDrive作業コピー側の採番 "0004_auth_tables" との差異を吸収）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_invites_lot_name"
down_revision: str | None = "0005_auth_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invites",
        sa.Column("lot_name", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invites", "lot_name")
