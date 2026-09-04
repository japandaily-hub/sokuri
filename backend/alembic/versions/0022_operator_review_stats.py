"""operators に review_count / latest_review_comment、reviews に hidden_at / hidden_reason を追加（口コミ常時公開・表示拡充）

Revision ID: 0022_operator_review_stats
Revises: 0021_bid_withdrawal_append_only
Create Date: 2026-09-04

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは26文字）。

背景: 口コミを常時公開する方針（2026-09-04 ユーザー決定）に伴い、入札一覧・業者一覧で
「★平均 (件数)」と最新口コミの抜粋を表示する。operators.rating と同じ非正規化列として
持ち、reviews.py の投稿時に再計算する。既存レビューはここでバックフィルする。
operator_profiles.is_public / show_stats / show_reviews は API から撤去するが、
列は破壊的変更を避けて残置する（参照箇所なし）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_operator_review_stats"
down_revision: str | None = "0021_bid_withdrawal_append_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators",
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "operators",
        sa.Column("latest_review_comment", sa.String(length=200), nullable=True),
    )
    # 運営による口コミの論理削除（security review H-2: 削除・送信防止措置の経路）
    op.add_column(
        "reviews",
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reviews",
        sa.Column("hidden_reason", sa.String(length=200), nullable=True),
    )
    # 既存レビューのバックフィル（顧客→業者のみ）
    op.execute(
        """
        UPDATE operators AS o
        SET review_count = s.cnt
        FROM (
            SELECT b.operator_id, COUNT(*) AS cnt
            FROM reviews r
            JOIN transactions t ON t.id = r.transaction_id
            JOIN bids b ON b.id = t.bid_id
            WHERE r.reviewer_type = 'user'
            GROUP BY b.operator_id
        ) AS s
        WHERE o.id = s.operator_id
        """
    )
    op.execute(
        """
        UPDATE operators AS o
        SET latest_review_comment = LEFT(btrim(s.comment), 200)
        FROM (
            SELECT DISTINCT ON (b.operator_id) b.operator_id, r.comment
            FROM reviews r
            JOIN transactions t ON t.id = r.transaction_id
            JOIN bids b ON b.id = t.bid_id
            WHERE r.reviewer_type = 'user'
              AND r.comment IS NOT NULL AND btrim(r.comment) <> ''
              -- 既存コメントは投稿時に連絡先ガードを通っていないため、URL・メール・
              -- 電話番号らしき文字列を含むものは抜粋にコピーしない（本文は /vendors/{id} で
              -- 従来どおり表示される。運営が hide で個別に非表示化できる）。
              AND r.comment !~* '(https?://|www\.|@|[0-9]{2,4}-?[0-9]{2,4}-?[0-9]{3,4})'
            ORDER BY b.operator_id, r.created_at DESC, r.id DESC
        ) AS s
        WHERE o.id = s.operator_id
        """
    )


def downgrade() -> None:
    op.drop_column("reviews", "hidden_reason")
    op.drop_column("reviews", "hidden_at")
    op.drop_column("operators", "latest_review_comment")
    op.drop_column("operators", "review_count")
