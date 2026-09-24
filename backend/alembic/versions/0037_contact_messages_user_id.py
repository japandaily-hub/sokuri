"""contact_messages に user_id（送信者アカウント）を追加

Revision ID: 0037_contact_messages_user_id
Revises: 0036_email_notify_opt_in
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは29文字）。

背景（security review 指摘・MEDIUM）:
- 依頼者の退会処理（users._delete_and_anonymize_user）は、公開フォーム由来の
  問い合わせを「メールアドレス一致」だけで匿名化していた。signup はメールの
  所有確認をしないため、第三者が他人のアドレスで登録→即退会するだけで、
  その人が送った苦情・削除請求などの記録を運営の受信台帳から消せた。
- ログイン中の依頼者が送信した場合のみ送信者アカウントを記録し、退会時の
  匿名化はこの列が一致する行に限定する。既存行は NULL のまま（紐付けの根拠が
  無いため遡って推定しない。本人からの削除請求は運営が本人確認のうえ
  ``DELETE /admin/contacts/{id}`` で対応する）。
- 依頼者アカウントは論理削除のみで物理削除しないが、FK は他の users 参照
  （0031・0032）と同じく ON DELETE SET NULL にそろえる。
- 索引は退会時の ``WHERE user_id = :id`` の照合用。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_contact_messages_user_id"
down_revision: str | None = "0036_email_notify_opt_in"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL 可・DEFAULT なしの ADD COLUMN はテーブル書き換えを伴わないメタデータ操作のみ。
    # 長引きうるのはロック待ちだけなので 0036 と同じく待機時間に上限を設ける。
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))

    # batch_alter_table 経由にする（0031 と同じ理由）: SQLite は既存テーブルへの
    # ALTER TABLE ADD CONSTRAINT をサポートしないため。PostgreSQL では通常の ALTER TABLE。
    with op.batch_alter_table("contact_messages") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_contact_messages_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        op.f("ix_contact_messages_user_id"),
        "contact_messages",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_contact_messages_user_id"), table_name="contact_messages")
    with op.batch_alter_table("contact_messages") as batch_op:
        batch_op.drop_constraint("fk_contact_messages_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
