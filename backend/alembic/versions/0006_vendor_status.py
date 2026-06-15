"""operators に vendor_status を追加・invite_code を nullable 化・部分ユニークインデックスへ移行。

Revision ID: 0006_vendor_status
Revises: 0005_invites_lot_name
Create Date: 2026-06-15

変更内容:
1. vendor_status VARCHAR(20) NOT NULL DEFAULT 'limited' 追加
2. 既存の verified_at IS NOT NULL 業者を 'active' にバックフィル
3. invite_code NOT NULL → NULL 許容
4. uq_operators_invite_code を削除し部分ユニークインデックスへ置換
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "0006_vendor_status"
down_revision: str | None = "0005_invites_lot_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. vendor_status カラム追加 ─────────────────────────────────
    op.add_column(
        "operators",
        sa.Column(
            "vendor_status",
            sa.String(20),
            nullable=False,
            server_default="limited",
        ),
    )
    op.create_index("ix_operators_vendor_status", "operators", ["vendor_status"])

    # ── 2. バックフィル: verified_at IS NOT NULL → active ───────────
    op.execute(
        text(
            "UPDATE operators SET vendor_status = 'active' WHERE verified_at IS NOT NULL"
        )
    )

    # ── 3. invite_code: NOT NULL → NULL 許容 ────────────────────────
    op.alter_column(
        "operators",
        "invite_code",
        existing_type=sa.String(64),
        nullable=True,
    )

    # ── 4. UNIQUE制約を部分ユニークインデックスへ置換 ─────────────────
    # 既存の unique 制約を削除（制約名が異なる環境用に両方試みる）
    try:
        op.drop_constraint("uq_operators_invite_code", "operators", type_="unique")
    except Exception:
        pass

    # 既存インデックス（ix_operators_invite_code）が存在する場合は削除
    try:
        op.drop_index("ix_operators_invite_code", "operators")
    except Exception:
        pass

    # NULL を除く invite_code のみを一意にする部分ユニークインデックス
    op.create_index(
        "uix_operators_invite_code_notnull",
        "operators",
        ["invite_code"],
        unique=True,
        postgresql_where=text("invite_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uix_operators_invite_code_notnull", "operators")
    op.create_index("ix_operators_invite_code", "operators", ["invite_code"])
    op.create_unique_constraint("uq_operators_invite_code", "operators", ["invite_code"])
    op.alter_column(
        "operators",
        "invite_code",
        existing_type=sa.String(64),
        nullable=False,
    )
    op.drop_index("ix_operators_vendor_status", "operators")
    op.drop_column("operators", "vendor_status")
