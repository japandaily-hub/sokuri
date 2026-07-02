"""users / operators に line_user_id を追加し、LINEログイン専用ユーザーを許容する。

Revision ID: 0011_line_user_id
Revises: 0010_operator_applications_client_ip
Create Date: 2026-07-02

背景（LINEログイン統合・MVP方針）:
LINE の Messaging API Profile（GET /v2/profile）から取得できる userId を
users / operators に保存し、以後のログイン紐付け・LINE Push通知の宛先に使う。
今回は id_token / JWKS 検証は行わない簡略実装（将来強化事項）。

変更内容:
1. users.line_user_id VARCHAR(64) NULL, UNIQUE, INDEX を追加
2. operators.line_user_id VARCHAR(64) NULL, UNIQUE, INDEX を追加
3. users.password_hash を NOT NULL → NULL 許容に変更
   （LINE専用アカウント = パスワードを持たないユーザーを許容するため）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_line_user_id"
down_revision: str | None = "0010_operator_applications_client_ip"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. users.line_user_id ────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("line_user_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_users_line_user_id", "users", ["line_user_id"], unique=True)

    # ── 2. operators.line_user_id ────────────────────────────────────
    op.add_column(
        "operators",
        sa.Column("line_user_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_operators_line_user_id", "operators", ["line_user_id"], unique=True
    )

    # ── 3. users.password_hash: NOT NULL → NULL 許容 ─────────────────
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(512),
        nullable=True,
    )


def downgrade() -> None:
    # 注意: LINE専用ユーザー（password_hash IS NULL）が既に存在する場合、
    # 以下の nullable=False への戻しは NOT NULL 制約違反で失敗しうる。
    # downgrade 実行前に該当ユーザーへ password_hash を補填するか、
    # 当該ユーザーの扱いを運用判断で決めてから実行すること。
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(512),
        nullable=False,
    )

    op.drop_index("ix_operators_line_user_id", "operators")
    op.drop_column("operators", "line_user_id")

    op.drop_index("ix_users_line_user_id", "users")
    op.drop_column("users", "line_user_id")
