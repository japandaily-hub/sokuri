"""入札の引き上げ履歴テーブルと revision_count を追加

Revision ID: 0034_bid_amount_history
Revises: 0033_reminder_marks
Create Date: 2026-09-07

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは25文字）。

背景:
- 「複数回入札できるように」＝価格競争を起こしたいという要望に対し、
  1案件1業者1入札の一意制約（uq_bids_case_operator）自体は据え置いたまま、
  自社の入札額を現在額より高い金額へ何度でも引き上げられる
  ``PATCH /cases/{case_id}/bids/me`` を新設する（封印入札のまま・下げは不可）。
- 「いつ・いくらからいくらへ引き上げたか」は既存の bids 行の updated_at
  だけでは追跡できない（bid_withdrawals と同じ理由）ため、追記専用の
  監査テーブル bid_amount_history を新設する。
- bids.revision_count は「何回引き上げたか」を都度 COUNT で数えず O(1) で
  返すための非正規化カウンタ（一覧表示・N+1回避）。
- 既存本番データへの影響が無いよう、両カラムとも NULL 許容にはせず
  server_default を与えて NOT NULL のまま埋め戻す（既存行は revision_count=0
  として扱って矛盾しない）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_bid_amount_history"
down_revision: str | None = "0033_reminder_marks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bids",
        sa.Column(
            "revision_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.create_table(
        "bid_amount_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        # ON DELETE CASCADE: 監査証跡だが、bid_withdrawals（RESTRICT）と異なり
        # 引き上げ履歴は親の bids 行が生きている前提の付随情報であり、
        # 不正調査の唯一の記録という位置づけではないため、bid削除（＝cascadeの
        # 発生源である case/operator 削除）に追随して消えてよい（設計指示）。
        sa.Column("bid_id", sa.Uuid(), nullable=False),
        sa.Column("old_amount", sa.BigInteger(), nullable=False),
        sa.Column("new_amount", sa.BigInteger(), nullable=False),
        sa.Column("old_message", sa.Text(), nullable=True),
        sa.Column("new_message", sa.Text(), nullable=True),
        # server_default が無いと（旧版の本カラム定義）、ORM側で値を明示しない
        # INSERT では DB が NOT NULL 制約違反（NotNullViolation）を返す。
        # ORM（Bid AmountHistory.changed_at）は server_default=func.now() を
        # メタデータに持つのみで、実テーブルの DDL に反映されない限り本番では
        # 効かない（create_all を使うテストのみで通っていた検出漏れ。
        # security review Critical指摘対応）。sa.text("now()") は PostgreSQL
        # 専用構文で SQLite では失敗するため、両dialectで解釈される
        # sa.func.now() を使う（PostgreSQLでは now()、SQLiteでは
        # CURRENT_TIMESTAMP にコンパイルされる）。
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["bid_id"], ["bids.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bid_amount_history_bid_id", "bid_amount_history", ["bid_id"], unique=False
    )


def downgrade() -> None:
    # bid_amount_history は引き上げの監査証跡（不正調査・カスタマーサポート対応の
    # 唯一の記録）である。ロールバックすると全履歴が失われるため、実行前に
    # 必ずテーブルをダンプ（例: pg_dump --table=bid_amount_history）しておくこと。
    op.drop_index("ix_bid_amount_history_bid_id", table_name="bid_amount_history")
    op.drop_table("bid_amount_history")
    op.drop_column("bids", "revision_count")
