"""本人確認書類の受付廃止に伴い、保存済みの身分証画像を消去する。

Revision ID: 0049_erase_identity_images
Revises: 0048_users_terms_agreement
Create Date: 2026-11-18

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは26文字）。

背景:
- 運転免許証・マイナンバーカード等の画像を預かること自体が、漏えい時の被害を大きくする。
  依頼者の本人確認書類の受付を全面的にやめた（API は 410 Gone・user_identity.py）。
  お引き取りの際の本人確認は、古物営業法に基づき訪問する古物商（業者）が行う。
- 本リビジョンで、user_identity_documents の画像本体（表・裏）を NULL にする。
  提出日時・書類種別・審査結果などの行は運営の操作履歴として残す（画像を含まない）。
- 審査待ち（pending）のまま残っていた提出は、受付終了として rejected にし、理由を残す。
  reviewed_at / reviewed_by は入れない（運営が審査したわけではないため。運営の操作履歴
  ＝ reviewed_at を持つ行にも出ない）。依頼者の users.identity_status が pending の人は
  unverified に戻す（画面にはもう出ないが、非正規化キャッシュを実態に合わせる）。
- PostgreSQL では UPDATE しただけでは旧い行の版（TOAST 上の画像バイト列）が表のファイルに
  残り、autovacuum 後も領域が再利用されるまで物理的には消えない。表は小さく、受付も止めた
  ので、トランザクションの外で VACUUM FULL を実行し表を書き直す（ACCESS EXCLUSIVE を
  短時間取る。読み書きするのは退会処理と運営の操作履歴だけ）。lock_timeout を短くし、
  取れなければ VACUUM だけ諦めて警告を出す（画像の NULL 化は既にコミット済みのため、
  autovacuum 後の再利用で順次消える）。
- バックアップ（Render の PITR・日次スナップショット）に残る画像は、本リビジョンでは
  消せない。保持期間の経過で消える。
- downgrade は何もしない（消した画像は戻せない。状態の書き換えも戻さない）。

反映順: 受付を止めるコード（410）を先に本番へ出し、受付が止まったことを確認してから
本リビジョンを反映する（逆順だと、消去と新コードの起動の間に旧コードが新しい画像を
受け付けうる）。本リビジョンは何度流しても同じ結果になる（冪等）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_erase_identity_images"
down_revision: str | None = "0048_users_terms_agreement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_RETIRED_REJECT_REASON = "本人確認書類の受付終了により、審査を行わずに終了しました。"


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"
    if is_postgresql:
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))

    erased = bind.execute(
        sa.text(
            "UPDATE user_identity_documents "
            "SET front_image_data = NULL, back_image_data = NULL, back_image_content_type = NULL "
            "WHERE front_image_data IS NOT NULL OR back_image_data IS NOT NULL"
        )
    ).rowcount
    closed = bind.execute(
        sa.text(
            "UPDATE user_identity_documents SET status = 'rejected', reject_reason = :reason "
            "WHERE status = 'pending'"
        ),
        {"reason": _RETIRED_REJECT_REASON},
    ).rowcount
    reset_users = bind.execute(
        sa.text("UPDATE users SET identity_status = 'unverified' WHERE identity_status = 'pending'")
    ).rowcount
    logger.info(
        "0049: 本人確認書類の画像を消去しました - erased_rows=%s closed_pending=%s reset_users=%s",
        erased,
        closed,
        reset_users,
    )

    if not is_postgresql:
        return
    # VACUUM はトランザクション内で実行できないため autocommit で流す。ここに来た時点で
    # 上の UPDATE はコミットされる（autocommit_block の仕様）。
    with op.get_context().autocommit_block():
        try:
            op.execute(sa.text("SET lock_timeout = '3s'"))
            op.execute(sa.text("VACUUM FULL user_identity_documents"))
            # 古いスナップショットを持つ他の接続（無停止デプロイ中の旧インスタンス・長い
            # トランザクション等）があると、VACUUM FULL は画像の旧い版を新しいファイルへ
            # そのまま写す（実 PostgreSQL 16 で確認済み）。その場合は成功扱いにしない。
            holders = op.get_bind().execute(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                    "AND (backend_xmin IS NOT NULL OR backend_xid IS NOT NULL)"
                )
            ).scalar()
            if holders:
                logger.warning(
                    "0049: VACUUM FULL の時点で古いスナップショットを持つ接続が %s 件あり、"
                    "画像の旧い版が残った可能性があります。旧インスタンスの停止後に手動で "
                    "VACUUM (FULL, VERBOSE) user_identity_documents を実行し、"
                    "'0 dead row versions cannot be removed yet' を確認してください",
                    holders,
                )
            else:
                logger.info("0049: user_identity_documents を VACUUM FULL で書き直しました")
        except Exception as exc:  # noqa: BLE001 — VACUUM の失敗で起動を止めない（docstring 参照）
            logger.warning(
                "0049: VACUUM FULL に失敗しました（画像の NULL 化はコミット済み）。"
                "後で手動で VACUUM FULL user_identity_documents を実行してください - %s",
                exc,
            )
        finally:
            op.execute(sa.text("RESET lock_timeout"))


def downgrade() -> None:
    # 消去した画像は復元できない。状態の書き換えも戻さない（docstring 参照）。
    pass
