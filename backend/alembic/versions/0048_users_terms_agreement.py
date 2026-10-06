"""依頼者（users）の利用規約への同意の版数と日時を記録する列を追加する。

Revision ID: 0048_users_terms_agreement
Revises: 0047_password_reset_tokens
Create Date: 2026-10-06

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは26文字）。

背景（3周目の法務監査・中）:
- 依頼者の利用規約・プライバシーポリシーへの同意は画面のチェックボックスだけで判定され、
  サーバーには何も残っていなかった。LINE 交換の入口（/auth/line/exchange）を直接呼べば
  チェックを通らずに新規アカウントを作れた。業者（operators）は ``agreed_terms_version``・
  ``agreed_at`` を保存済みで、依頼者も同じ名前の列で同意の証跡を持つ。
- 列はどちらも NULL 可で追加する。既存ユーザーは NULL のまま（＝この改修より前の登録で、
  サーバー側の同意記録が無い）とし、再同意は求めない（backfill はしない。過去の同意の
  版数・日時をサーバーは知らないため、推測の値で埋めると証跡として誤りになる）。
- server_default を持たない NULL 可の ADD COLUMN は PostgreSQL ではメタデータの変更だけで
  表の書き換えは無いが、users の ACCESS EXCLUSIVE ロックを取るため、待ちが長引かないよう
  lock_timeout を短くする（3s。取れなければ失敗させ start.sh のリトライに任せる）。
- downgrade は2列を削除する（記録済みの同意の証跡も消えるため、戻すのは列を読むコードを
  先に戻した後に限る）。
- 反映はマイグレーション先行の2段（このリビジョンだけを先に反映して /readyz で head を
  確認してから、列を読み書きするコードを反映する）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_users_terms_agreement"
down_revision: str | None = "0047_password_reset_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _shorten_lock_timeout_on_postgresql() -> None:
    """PostgreSQL のみ: DDL の前に lock_timeout を短くする（docstring 参照）。"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))


def upgrade() -> None:
    _shorten_lock_timeout_on_postgresql()
    op.add_column(
        "users",
        sa.Column("agreed_terms_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    _shorten_lock_timeout_on_postgresql()
    op.drop_column("users", "agreed_at")
    op.drop_column("users", "agreed_terms_version")
