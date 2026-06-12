"""auth tables — users / invites + operators.password_hash

Revision ID: 0005_auth_tables
Revises: 0004_katadzuke_schema
Create Date: 2026-06-12

既存テーブルは削除・変更しない（追加のみ）。
- users: ユーザー認証（email + password、role で admin 判別）
- invites: 管理者発行の業者招待コード
- operators.password_hash: 業者ログイン用（既存行は NULL 許容）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_auth_tables"
down_revision: str | None = "0004_katadzuke_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_now = sa.text("now()")


def _ts() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now, nullable=False),
    )


def upgrade() -> None:
    # ── 1. users（ユーザー）──────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="'user'"),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('user','admin')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ── 2. invites（業者招待コード）──────────────────────────────────
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_invites"),
        sa.UniqueConstraint("code", name="uq_invites_code"),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["operators.id"],
            ondelete="SET NULL",
            name="fk_invites_operator_id_operators",
        ),
    )
    op.create_index("ix_invites_code", "invites", ["code"])

    # ── 3. operators.password_hash 追加 ──────────────────────────────
    op.add_column(
        "operators",
        sa.Column("password_hash", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operators", "password_hash")
    op.drop_table("invites")
    op.drop_table("users")
