"""operators に deleted_at を追加（業者の退会＝論理削除・匿名化）

Revision ID: 0030_operator_deleted_at
Revises: 0029_case_idempotency_unique
Create Date: 2026-09-05

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは24文字）。

背景（r8 異常系監査 M6）:
- 業者は自分でアカウントを閉じる手段が無く（DELETE 相当のAPIが存在しない）、
  一方で privacy ページは「退会された場合…遅滞なく削除します」と表示していた。
- 依頼者（``users.deleted_at``）と同型の論理削除にする。物理削除はしない
  ＝ 完了済み取引・レビュー・キャンセル記録を依頼者側の記録として保持するため。
- 退会済み業者は ``deps.get_current_operator`` で旧トークンを即時失効させ、
  公開一覧（GET /vendors）・公開プロフィール（GET /vendors/{id}）・
  業者ログインからも除外する。索引は「退会済みを除外する」全参照経路が
  WHERE 句で使うため付与する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_operator_deleted_at"
down_revision: str | None = "0029_case_idempotency_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_operators_deleted_at"), "operators", ["deleted_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_operators_deleted_at"), table_name="operators")
    op.drop_column("operators", "deleted_at")
