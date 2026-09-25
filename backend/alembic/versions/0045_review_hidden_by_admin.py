"""reviews に hidden_by_admin_id を追加（口コミを今削除している運営を記録）

Revision ID: 0045_review_hidden_by_admin
Revises: 0044_drop_rating_columns
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは27文字）。

背景（2026-09-25 ユーザー指示「運営が口コミの削除ができるようにもしておいて」。
設計の正本: .agent-state/review-verdict/DESIGN-admin.md）:
- 運営の口コミ管理（GET /admin/reviews・PATCH /admin/reviews/{id}/hide）で、口コミを削除（論理削除＝
  hidden_at）した運営アカウントを残す。運営が複数人になった時点で「誰が消したか」を追えるようにする
  （0031 の cancellations.cancelled_by_admin_id と同じ動機）。
- 値は「今削除している人」だけ（元に戻すと NULL。誰がいつ消して戻したかの履歴は操作ログ
  admin_review_hide に残る）。既存行は NULL のまま。
- 運営アカウントが削除されても口コミの行は残すため ON DELETE SET NULL。API は運営向けの一覧にだけ出し、
  当事者・公開向けの応答には含めない（運営個人を開示しない）。索引は「特定の運営の操作を引く」
  監査クエリと、users の削除時の SET NULL の検索用。
- 作り方は 0031 と同じ（SQLite は既存テーブルへの ADD CONSTRAINT が無いため batch 経由。PostgreSQL では
  通常の ALTER TABLE のまま）。PostgreSQL では lock_timeout 3s（表ロックを長く待って読み取りを止めない。
  取れなければ失敗させ start.sh のリトライに任せる）。
- 反映は3段の段2（0044 と同じ push・マイグレーションのみ）。列をマップするコード（段3）は本リビジョンの
  本番適用を確認してから出す（逆順だと reviews の SELECT が列の不在で 500 になる）。
- app のコードは import しない。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_review_hidden_by_admin"
down_revision: str | None = "0044_drop_rating_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_reviews_hidden_by_admin_id_users"


def _set_lock_timeout() -> None:
    """PostgreSQL のみ: 表ロックの待ちを 3s で打ち切る（SQLite には無い構文のため発行しない）。"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))


def upgrade() -> None:
    _set_lock_timeout()
    # batch_alter_table 経由にする理由は 0031 と同じ（SQLite は ALTER TABLE ADD CONSTRAINT を持たない）。
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.add_column(sa.Column("hidden_by_admin_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            _FK_NAME,
            "users",
            ["hidden_by_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        op.f("ix_reviews_hidden_by_admin_id"),
        "reviews",
        ["hidden_by_admin_id"],
        unique=False,
    )


def downgrade() -> None:
    _set_lock_timeout()
    op.drop_index(op.f("ix_reviews_hidden_by_admin_id"), table_name="reviews")
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.drop_column("hidden_by_admin_id")
