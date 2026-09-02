"""商品(CaseItem)情報のユーザー編集項目を追加 — user_condition / user_description

Revision ID: 0016_case_item_user_edits
Revises: 0015_case_items
Create Date: 2026-09-02

背景:
ユーザーが商品(CaseItem)のコンディション・説明を自ら編集できるようにするため、
AI推定値（ai_condition / ai_summary）とは別カラムでユーザー編集値を保持する。
AI推定結果を上書き消去しないための分離（案件詳細でAI推定/ユーザー編集の両方を
参照可能にする設計判断）。

設計判断:
- user_condition は 0015 の ai_condition と同様、ItemCondition を ORM 型として
  再利用しつつ DDL は VARCHAR(32)（native_enum=False）に固定する。
- server_default は設定しない（新規カラムはユーザーが未編集の間は NULL のまま）。
- alembic revision id は過去の alembic_version 全断障害の再発防止のため
  32文字以内を厳守する（本リビジョンは25文字）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_case_item_user_edits"
down_revision: str | None = "0015_case_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "case_items", sa.Column("user_condition", sa.String(32), nullable=True)
    )
    op.add_column(
        "case_items", sa.Column("user_description", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("case_items", "user_description")
    op.drop_column("case_items", "user_condition")
