"""contact_messages テーブルを新設（公開フォームの問い合わせを DB に残す）

Revision ID: 0032_contact_messages
Revises: 0031_cancellation_admin
Create Date: 2026-09-05

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは21文字）。

背景（r10 O-M6）:
- ``POST /contact`` は ADMIN_EMAILS へメールを投げるのみで DB 保存が無く、
  ADMIN_EMAILS 未設定・Brevo 障害・迷惑メール振り分けのいずれか一つで問い合わせが
  痕跡ゼロで消えていた（依頼者には 202 が返るため誰も気づけない）。
- 停止中アカウントの解除依頼（``SUSPENDED_ACCOUNT_DETAIL`` の案内先）の受け皿でも
  あるため、対応状況（handled_at / handled_by_admin_id）を追跡できる台帳にする。
- ``handled_by_admin_id`` は運営アカウント削除後も記録を残すため ON DELETE SET NULL
  （0031 の cancelled_by_admin_id と同方針）。
- 索引は「未対応を新着順」という運営の既定動線に合わせた複合1本のみ
  （handled_at, created_at）＋ 同一送信者の名寄せ用に email。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_contact_messages"
down_revision: str | None = "0031_cancellation_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by_admin_id", sa.Uuid(), nullable=True),
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
            ["handled_by_admin_id"],
            ["users.id"],
            name=op.f("fk_contact_messages_handled_by_admin_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_messages")),
    )
    op.create_index(
        op.f("ix_contact_messages_email"), "contact_messages", ["email"], unique=False
    )
    op.create_index(
        "ix_contact_messages_handled_at_created_at",
        "contact_messages",
        ["handled_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_contact_messages_handled_at_created_at", table_name="contact_messages")
    op.drop_index(op.f("ix_contact_messages_email"), table_name="contact_messages")
    op.drop_table("contact_messages")
