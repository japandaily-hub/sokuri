"""お知らせメールの受け取り設定（users）を追加

Revision ID: 0036_email_notify_opt_in
Revises: 0035_bids_pending_reminder
Create Date: 2026-09-18

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは24文字）。

背景:
- 新規登録フォームの任意チェック「入札情報・サービスに関するメール通知を受け取る」
  の値が、これまで users 側に受け皿の列が無く、どこにも保存されず捨てられていた
  不具合の修正。
- ``email_notify_opt_in`` は「入札受信 / 入札額更新 / 入札なしリマインド /
  入札未決定リマインド」の4種のメールのみを対象にした受信可否フラグ
  （services/notify_dispatch.py 側で判定。LINE Push・取引上必須の連絡
  （出品受付・成約・訪問日程・減額・キャンセル・口座変更・停止/解除等）には
  一切影響しない）。
- 既存ユーザーの挙動を変えないため NOT NULL・server_default true で追加する
  （0033/0035 のような「NULL のまま追加して1周目に一斉送信」型の事故とは異なり、
  本フラグは定期ジョブの一斉起動条件ではなく個々の送信可否の分岐にすぎないため
  backfill は不要——true のデフォルトそのものが「従来どおり受信」という
  正しい初期値になる）。
- ``email_notify_updated_at`` は本人が明示的に選択・変更した時刻のみを記録する
  監査目的の列（未選択は NULL のまま）。NOT NULL 制約は課さない。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_email_notify_opt_in"
down_revision: str | None = "0035_bids_pending_reminder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD COLUMN は users に ACCESS EXCLUSIVE ロックを取る（0035 と同じ懸念）。
    # 本バージョンは backfill の UPDATE を伴わない（server_default で全既存行が
    # 即座に true を持つ）ため、ロック**保持**時間そのものは「列2本の追加」のみ
    # （PG11+ では DEFAULT 付き ADD COLUMN はテーブル書き換えを伴わないメタデータ
    # 操作のみ）で極めて短い。0033/0035（大きな UPDATE を同一トランザクションで
    # 抱える版）とはロック保持リスクの性質が異なり、本版で長引きうるのは
    # 「ロックを**待つ**時間」（他の短時間トランザクションがたまたま users 行を
    # 掴んでいる）だけなので、待機時間には多少の余裕を持たせる
    # （security review H-1: 3s は他版からの機械的な複製で、実際の所要時間に対して
    # 不必要に短く、通常の負荷変動で不要な失敗（オフピーク再実行の手間）を招く
    # リスクの方が大きいと判断し 10s に緩和）。
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '10s'"))

    op.add_column(
        "users",
        sa.Column(
            "email_notify_opt_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_notify_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "email_notify_updated_at")
    op.drop_column("users", "email_notify_opt_in")
