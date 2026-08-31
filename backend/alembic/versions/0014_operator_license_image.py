"""operators に古物商許可証画像（審査書類）の保存カラムを追加する。

Revision ID: 0014_operator_license_image
Revises: 0013_user_profile_fields
Create Date: 2026-08-31

背景（業者許可証画像アップロード機能）:
古物商許可証等の審査書類画像を、既存の presign/ファイルシステム方式（case_photos.py の
/upload/presign・/files/{key}、無認証capability URL）とは独立させ、認証必須の
専用エンドポイント（/operator/license-image）でDBのBYTEAに直接保存・配信する。

変更内容（全て nullable=True で追加。default/backfill/index不要）:
1. operators.license_image_data          BYTEA
   （ORM側は deferred=True。既存の select(Operator) / list_operators 等の
   全業者関連クエリで毎回ロードされないようにするための性能・メモリ対策。
   マイグレーション自体はカラム追加のみで、deferred はモデル層の関心のため
   ここでは通常の add_column で足りる。）
2. operators.license_image_content_type  VARCHAR(32)
3. operators.license_image_uploaded_at   TIMESTAMPTZ
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_operator_license_image"
down_revision: str | None = "0013_user_profile_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators", sa.Column("license_image_data", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "operators",
        sa.Column("license_image_content_type", sa.String(32), nullable=True),
    )
    op.add_column(
        "operators",
        sa.Column("license_image_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operators", "license_image_uploaded_at")
    op.drop_column("operators", "license_image_content_type")
    op.drop_column("operators", "license_image_data")
