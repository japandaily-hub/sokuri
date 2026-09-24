"""退会・強制削除済み業者に再設定された LINE 連携（line_user_id）を消す（データ是正）

Revision ID: 0038_clear_deleted_op_line_ids
Revises: 0037_contact_messages_user_id
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは30文字）。

背景（security review 指摘・MEDIUM）:
- ``POST /auth/line/exchange``（Bearer付き連携経路）の業者分岐が ``deleted_at`` を
  見ておらず、退会・強制削除済み業者の旧トークンで、匿名化済みの業者行へ
  ``line_user_id`` を再設定できた（削除で password_hash=None になるため再認証も
  飛ばされていた）。穴は deps.assert_operator_not_revoked の適用で塞いだが、
  既に再設定された行が本番に残っている可能性がある。
- 匿名化（operator_profile._delete_and_anonymize_operator）が消す LINE 関連の列は
  ``line_user_id`` のみで、line_exchange が書き込む列も ``line_user_id`` のみ。
  論理削除済みの行でこの列が非 NULL になる正規の経路は無いため、該当行を NULL に
  戻す（冪等。該当なしなら何も変わらない）。line_user_id は UNIQUE のため、
  残っていると本人の LINE を新しいアカウントへ連携できない副作用もある。
- downgrade は no-op（消した値は「本来存在してはならない値」であり、復元する
  意味も手段も無い）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_clear_deleted_op_line_ids"
down_revision: str | None = "0037_contact_messages_user_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0038_clear_deleted_op_line_ids")


def upgrade() -> None:
    # 対象は論理削除済みの業者行のみ（行ロックは該当行に限られ、件数も僅少の想定）。
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))

    # 悪用の有無の証跡（読み取りのみ）: 削除後に旧トークンで投稿された業者レビューの件数。
    # 穴（deps.get_current_actor が deleted_at を見ていなかった）が使われた場合にだけ
    # 1 以上になる。0 件でも「確認した」事実を残すため常にログへ出す（0028 と同じロガー方式）。
    post_deletion_reviews = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM reviews r"
            " JOIN transactions t ON t.id = r.transaction_id"
            " JOIN bids b ON b.id = t.bid_id"
            " JOIN operators o ON o.id = b.operator_id"
            " WHERE r.reviewer_type = 'operator'"
            " AND o.deleted_at IS NOT NULL AND r.created_at > o.deleted_at"
        )
    ).scalar_one()

    result = bind.execute(
        sa.text(
            "UPDATE operators SET line_user_id = NULL "
            "WHERE deleted_at IS NOT NULL AND line_user_id IS NOT NULL"
        )
    )
    cleared = result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0
    logger.info(
        "0038: 削除済み業者に残っていた LINE 連携を %s 件消去しました。"
        "削除後に投稿された業者レビューは %s 件でした（1 件以上なら旧トークン悪用の疑い。"
        "docs/ops/incidents.md へ記録すること）。",
        cleared,
        post_deletion_reviews,
    )


def downgrade() -> None:
    # データ是正のため戻さない（上記 docstring 参照）。
    pass
