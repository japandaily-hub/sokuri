"""users にマイページ拡張PII（生年月日・職業・住所・振込先口座・本人確認ステータス）を追加する。

Revision ID: 0022_users_pii_columns
Revises: 0021_bid_withdrawal_append_only
Create Date: 2026-09-04

背景（依頼者マイページ拡張 API）:
古物営業法上の本人確認義務・振込先口座登録に対応するため、users にPII列を追加する。
振込先口座は既存の operator_applications.bank_account_enc と同じ方式
（app.core.crypto.encrypt_json による暗号化JSON文字列）で保存し、平文はDBに残さない。

変更内容:
1. users.birth_date              DATE                 nullable
2. users.occupation               VARCHAR(64)          nullable
3. users.postal_code              VARCHAR(7)           nullable（数字7桁のみ保存）
4. users.prefecture               VARCHAR(8)           nullable
5. users.city                     VARCHAR(64)          nullable
6. users.address_line1            VARCHAR(255)         nullable
7. users.address_line2            VARCHAR(255)         nullable
8. users.bank_account_enc         TEXT                 nullable（暗号化済みJSON）
9. users.bank_account_updated_at  TIMESTAMPTZ          nullable
10. users.identity_status         VARCHAR(20) NOT NULL DEFAULT 'unverified'
    + CHECK制約 ck_users_identity_status（unverified/pending/approved/rejected）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_users_pii_columns"
down_revision: str | None = "0021_bid_withdrawal_append_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("occupation", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("postal_code", sa.String(7), nullable=True))
    op.add_column("users", sa.Column("prefecture", sa.String(8), nullable=True))
    op.add_column("users", sa.Column("city", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("address_line1", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("address_line2", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("bank_account_enc", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("bank_account_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "identity_status",
            sa.String(20),
            nullable=False,
            server_default="unverified",
        ),
    )
    op.create_check_constraint(
        "ck_users_identity_status",
        "users",
        "identity_status IN ('unverified','pending','approved','rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_identity_status", "users", type_="check")
    op.drop_column("users", "identity_status")
    op.drop_column("users", "bank_account_updated_at")
    op.drop_column("users", "bank_account_enc")
    op.drop_column("users", "address_line2")
    op.drop_column("users", "address_line1")
    op.drop_column("users", "city")
    op.drop_column("users", "prefecture")
    op.drop_column("users", "postal_code")
    op.drop_column("users", "occupation")
    op.drop_column("users", "birth_date")
