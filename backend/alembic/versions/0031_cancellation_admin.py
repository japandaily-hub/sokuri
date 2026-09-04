"""cancellations に cancelled_by_admin_id を追加（運営の強制終了の実行者を記録）

Revision ID: 0031_cancellation_admin
Revises: 0030_operator_deleted_at
Create Date: 2026-09-05

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは23文字）。

背景（r8-review M-1）:
- ``PATCH /admin/transactions/{id}/cancel`` は不可逆かつ当事者双方へ通知が飛ぶ
  操作だが、実行者はアプリログ（logger.info）にしか残らずローテーションで消える。
  運営が複数人になった時点で「誰が終わらせたか」を追跡できない。
- ``cancelled_by='admin'`` のときのみ非NULL。既存行は NULL のまま。
- 運営アカウントが削除されても記録自体は残すため ON DELETE SET NULL
  （既存の case_id / transaction_id と同方針）。
- API 応答には含めない（当事者に運営個人を開示しない）。索引は「特定の運営の
  操作履歴を引く」監査クエリのために付与する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_cancellation_admin"
down_revision: str | None = "0030_operator_deleted_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table 経由にする（0028・0029 と同じ理由）: SQLite は既存テーブルへの
    # ALTER TABLE ADD CONSTRAINT を一切サポートせず、素の op.create_foreign_key は
    # NotImplementedError で即死する。batch モードは SQLite でのみコピー＆リネーム
    # 戦略へ切り替わり、PostgreSQL では通常の ALTER TABLE のまま実行される。
    with op.batch_alter_table("cancellations") as batch_op:
        batch_op.add_column(
            sa.Column("cancelled_by_admin_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_cancellations_cancelled_by_admin_id_users",
            "users",
            ["cancelled_by_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        op.f("ix_cancellations_cancelled_by_admin_id"),
        "cancellations",
        ["cancelled_by_admin_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cancellations_cancelled_by_admin_id"), table_name="cancellations"
    )
    with op.batch_alter_table("cancellations") as batch_op:
        batch_op.drop_constraint(
            "fk_cancellations_cancelled_by_admin_id_users", type_="foreignkey"
        )
        batch_op.drop_column("cancelled_by_admin_id")
