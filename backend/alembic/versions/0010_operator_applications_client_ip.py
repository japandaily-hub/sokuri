"""operator_applications に client_ip カラムを追加（レート制限・スパム対策）。

Revision ID: 0010_operator_applications_client_ip
Revises: 0009_messages_schedule_and_operator_profiles
Create Date: 2026-07-02

背景（security review Critical指摘）:
公開・認証不要の POST /operator-applications にレート制限が無く、大量送信による
DB肥大化・暗号化コスト増幅・第三者へのメール爆撃が可能だった。IPアドレス単位で
直近1時間の申込件数を絞り込むために client_ip カラムを追加する。

新規テーブル・新規インフラ（Redis等）は導入せず、既存 operator_applications
テーブルと created_at のみでレート制限を実現する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_operator_applications_client_ip"
down_revision: str | None = "0009_messages_schedule_and_operator_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operator_applications",
        sa.Column("client_ip", sa.String(64), nullable=True),
    )
    # レート制限クエリ（client_ip + created_at 絞り込み）を高速化するための複合インデックス。
    op.create_index(
        "ix_operator_applications_client_ip_created_at",
        "operator_applications",
        ["client_ip", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operator_applications_client_ip_created_at", "operator_applications"
    )
    op.drop_column("operator_applications", "client_ip")
