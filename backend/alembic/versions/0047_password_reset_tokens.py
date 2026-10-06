"""パスワード再設定トークンの表（password_reset_tokens）を新設する。

Revision ID: 0047_password_reset_tokens
Revises: 0046_messages_kind_length
Create Date: 2026-10-06

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは26文字）。

背景:
- 依頼者（users）・業者（operators）ともパスワード再設定が未実装で、/password-reset は
  「準備中」を出して問い合わせへ誘導していた（業者は窓口対応で通常3営業日）。メールで
  送った1回限りのリンクから本人が再設定できるようにする（services/password_reset.py）。
- 平文のトークンは保存せず、SHA-256 の16進（64文字）だけを ``token_hash`` に持つ（DB の
  読み取りだけでは再設定リンクを作れない）。有効期限は30分・1回限り（``used_at``）。
- ``account_type`` は "user" / "operator" の2値（CHECK 制約）。2表を指すため外部キーは
  張らない（アカウントは論理削除のみ）。
- 既存表には触れない新規表の作成のみで、既存の読み書きをロックで待たせることは無いが、
  作成時のカタログ更新のロック待ちが長引かないよう、他のリビジョンと同じく PostgreSQL では
  lock_timeout を短くする（3s。取れなければ失敗させ start.sh のリトライに任せる）。
- downgrade は表を削除する（未使用の再設定リンクはすべて無効になる。判定するコード側も
  同時に戻るため整合する）。
- 反映はマイグレーション先行の2段（このリビジョンだけを先に反映して /readyz で head を
  確認してから、表を読むコードを反映する）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047_password_reset_tokens"
down_revision: str | None = "0046_messages_kind_length"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "password_reset_tokens"


def _shorten_lock_timeout_on_postgresql() -> None:
    """PostgreSQL のみ: DDL の前に lock_timeout を短くする（docstring 参照）。"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))


def upgrade() -> None:
    _shorten_lock_timeout_on_postgresql()
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "account_type IN ('user', 'operator')",
            name=op.f("ck_password_reset_tokens_account_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_reset_tokens_token_hash")),
    )
    op.create_index(
        "ix_password_reset_tokens_account",
        _TABLE,
        ["account_type", "account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_account", table_name=_TABLE)
    op.drop_table(_TABLE)
