"""messages.kind を VARCHAR(16) から VARCHAR(32) へ拡幅する。

Revision ID: 0046_messages_kind_length
Revises: 0045_review_hidden_by_admin
Create Date: 2026-09-26

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは25文字）。

背景:
- messages.kind は 0009（0009_messages_schedule_and_operator_profiles.py:35）で
  ``sa.String(16)`` のまま以後拡幅されていない。SQLAlchemy 2.0.50 + asyncpg は
  INSERT で ``$6::VARCHAR``（長さなし）を送るため、PostgreSQL 16 公式ドキュメント
  §8.3「列長を超える文字列の格納はエラー」により、kind="schedule_proposal"（17文字）・
  "schedule_confirmed"（18文字）は本番 PostgreSQL では INSERT が失敗する。本番ログ
  （直近7日）に該当エラーは0件だが、日程系の呼び出し自体が0件＝未発火の潜在不具合
  だったため、実発火する前にここで拡幅する。
- 今回新設する kind="complete_request"（16文字）・"completed"（9文字）も含め、
  今後の kind 追加に余裕を持たせるため 32 文字へ拡げる。
- downgrade は no-op（VARCHAR(16) へ縮めると、既に17文字以上の値
  （schedule_proposal・schedule_confirmed）を持つ既存行の
  ALTER が PostgreSQL では失敗し、方言によっては無警告の切り詰めになりうる。
  値を戻す必要が生じた実績も無い）。
- SQLite は ALTER COLUMN の TYPE 変更を直接サポートしないため batch_alter_table
  （表の作り直し）を使う（0042_review_verdict_contract と同じ作法）。
- PostgreSQL では ALTER COLUMN が ACCESS EXCLUSIVE ロックを要する。messages への
  読み書きが集中している時間帯に長時間ロック待ちすると後続の通常リクエストまで
  待たせるため、取得までを lock_timeout=3s で打ち切る（0042_review_verdict_contract.py:95
  と同じ理由・同じ書き方。取れなければ失敗させ start.sh のリトライに任せる）。
  ALTER 単発のみで後続の DML が無いため、10s へ戻す操作は不要（SET LOCAL は
  トランザクション終了で自動的に元へ戻る）。SQLite では発行しない。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_messages_kind_length"
down_revision: str | None = "0045_review_hidden_by_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _shorten_lock_timeout_on_postgresql() -> None:
    """PostgreSQL のみ: ALTER の前に lock_timeout を短くする（docstring 参照）。"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))


def upgrade() -> None:
    _shorten_lock_timeout_on_postgresql()
    with op.batch_alter_table("messages") as batch_op:
        batch_op.alter_column(
            "kind",
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
            existing_server_default="text",
        )


def downgrade() -> None:
    # VARCHAR(16) へ戻すと、拡幅後に保存された17文字以上の値
    # （schedule_proposal・schedule_confirmed）を持つ既存行で
    # ALTER が失敗する（PostgreSQL）か、無警告で切り詰められる（方言依存）ため、
    # 安全に戻す手段が無い。no-op とする。
    pass
