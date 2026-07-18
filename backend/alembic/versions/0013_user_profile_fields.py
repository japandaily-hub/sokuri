"""users にプロフィール項目・論理削除・パスワード変更時刻を追加する。

Revision ID: 0013_user_profile_fields
Revises: 0012_fix_status_defaults
Create Date: 2026-07-17

背景（マイページ プロフィール編集 / パスワード変更 / 退会機能）:
マイページ（/users/me/profile 等）でユーザーが氏名・カナ・電話番号・居住エリアを
編集できるようにするための項目追加。加えて、パスワード変更・退会（論理削除）を
既発行 JWT に即時反映させるための失効ゲート用カラムを追加する
（deps.py の get_current_user / get_current_actor 参照）。

変更内容（全て nullable=True で追加。default/backfill/index不要）:
1. users.family_name         VARCHAR(64)
2. users.given_name          VARCHAR(64)
3. users.family_name_kana    VARCHAR(64)
4. users.given_name_kana     VARCHAR(64)
5. users.phone               VARCHAR(20)
6. users.residence_area      VARCHAR(32)
7. users.deleted_at          TIMESTAMPTZ（論理削除マーカー）
8. users.password_changed_at TIMESTAMPTZ（JWT失効ゲート用）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_profile_fields"
down_revision: str | None = "0012_fix_status_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("family_name", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("given_name", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("family_name_kana", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("given_name_kana", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("residence_area", sa.String(32), nullable=True))
    op.add_column(
        "users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "residence_area")
    op.drop_column("users", "phone")
    op.drop_column("users", "given_name_kana")
    op.drop_column("users", "family_name_kana")
    op.drop_column("users", "given_name")
    op.drop_column("users", "family_name")
