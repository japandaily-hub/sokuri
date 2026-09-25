"""停止に伴うセッション失効の境界（users / operators の sessions_revoked_at）を追加

Revision ID: 0039_sessions_revoked_at
Revises: 0038_clear_deleted_op_line_ids
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは24文字）。

背景:
- 運営がアカウント（依頼者・業者）を停止すると停止中は 403 になるが、停止を解除すると、
  停止前に発行されたアクセストークン（有効期限 7 日）が再び使えるようになっていた。
  停止時刻を ``sessions_revoked_at`` に記録し（実際の解除時は解除時刻へ進める。NULL には
  戻さない）、iat がそれ以前の
  トークンを deps.py の失効ゲートで 401 にする（停止解除後は再ログインを求める）。
- 列は NULL 可・既定値なし（NULL＝一度も停止されていない＝失効境界なし）。PG11+ では
  既定値なしの ADD COLUMN はテーブル書き換えを伴わないメタデータ操作のみ。参照は
  主キーで読んだ行の値を見るだけのため索引は作らない。
- 適用時点で停止中のアカウントには、適用時刻を境界として設定する（設定しないと、
  デプロイ前から停止中のアカウントを解除したときに停止前のトークンが復活し、本修正の
  対象から漏れる）。停止中はログイン・LINE 連携とも 403 で新しいトークンが発行されない
  ため、適用時刻を境界にしても失効するのは停止前（または停止と競合したログイン）の
  トークンだけ。依頼者の suspended_at ではなく適用時刻を使うのは、業者側に停止時刻の
  列が無いことと、停止と競合したログインのトークンまで確実に含めるため。時刻は
  0035 と同じくアプリ側の現在時刻（UTC）を使う（比較相手の iat もアプリ側の時刻のため、
  DB サーバーとの時刻ずれを持ち込まない）。
- 既に停止→解除済みのアカウントに残る停止前のトークンは、停止履歴が残っていないため
  遡って失効できない（発行から最長 7 日で期限切れ）。急ぐ場合は運営が該当アカウントを
  一度停止→解除し直せば、その時点で失効する。
- downgrade は列を削除する（失効境界も失われるが、判定するゲート側のコードも同時に
  戻るため整合する）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0039_sessions_revoked_at"
down_revision: str | None = "0038_clear_deleted_op_line_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0039_sessions_revoked_at")

_ACCOUNT_TABLES: tuple[str, ...] = ("users", "operators")


def upgrade() -> None:
    # ADD COLUMN は対象テーブルに ACCESS EXCLUSIVE ロックを取る（0036 と同じ懸念）。
    # 本版の保持時間は「既定値なしの列追加」と「停止中の行（僅少）だけの UPDATE」のみで
    # 極めて短く、長引きうるのはロックを**待つ**時間だけなので 0036 と同じ 10s とする。
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))

    for table_name in _ACCOUNT_TABLES:
        op.add_column(
            table_name,
            sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True),
        )

    now = datetime.now(timezone.utc)
    backfilled = {
        table_name: _backfill_currently_suspended(bind, table_name, now)
        for table_name in _ACCOUNT_TABLES
    }
    # 監査用に件数を常に残す（0 件でも「確認した」事実を残す。0038 と同じロガー方式）。
    logger.info(
        "0039: 適用時点で停止中のアカウントにセッション失効の境界を設定しました"
        "（依頼者 %s 件・業者 %s 件。停止解除後は再ログインが必要になります）。",
        backfilled["users"],
        backfilled["operators"],
    )


def _backfill_currently_suspended(bind: sa.engine.Connection, table_name: str, now: datetime) -> int:
    """適用時点で停止中（is_suspended=true）かつ境界未設定の行に ``now`` を設定し、件数を返す。"""
    accounts = sa.table(
        table_name,
        sa.column("is_suspended", sa.Boolean()),
        sa.column("sessions_revoked_at", sa.DateTime(timezone=True)),
    )
    result = bind.execute(
        accounts.update()
        .where(
            accounts.c.is_suspended.is_(True),
            accounts.c.sessions_revoked_at.is_(None),
        )
        .values(sessions_revoked_at=now)
    )
    return result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0


def downgrade() -> None:
    for table_name in reversed(_ACCOUNT_TABLES):
        op.drop_column(table_name, "sessions_revoked_at")
