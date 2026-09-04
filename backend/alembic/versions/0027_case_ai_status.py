"""cases に AI 解析状態（ai_status / ai_failed_reason）と冪等キーを追加

Revision ID: 0027_case_ai_status
Revises: 0026_operator_app_invite
Create Date: 2026-09-04

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは20文字）。

背景: r6-backend.md H-1 / r6-verify-backend.md ADD-1。案件作成リクエスト内で最大約200秒
かかる AI 解析を直列実行していたため、(1) プロキシタイムアウト後もサーバ側は案件を作り
続け依頼者の再送信で二重案件になる、(2) その間 DB コネクションをトランザクションごと
占有して API 全体が詰まる、の2つが同時に起きていた。解析を BackgroundTasks へ出すには
「解析がまだ終わっていない」を表現する状態列が要る。

- ``ai_status``: "pending" / "done" / "failed"。既存行は解析完了済みのため "done" で埋める。
  r7 M-5: 「server_default="done" で列を足してから既定値を "pending" へ張り替える」形に
  変更し、全行 UPDATE を廃止した（PG11+ の add_column は既存行を書き換えないのに、直後の
  無条件 UPDATE が全行を dead tuple 化して実質テーブル倍増＋全行分の WAL を発生させ、
  cases が育った将来のデプロイでロック保持と再試行時間を伸ばすため）。
- ``ai_failed_reason``: 失敗理由（運営の切り分け用・任意）。
- ``idempotency_key``: クライアント発行 UUID。直近10分・同一ユーザーの再送信検出にのみ
  使うため一意制約は張らず、検索用の索引のみ張る。

ロック影響: いずれも nullable もしくは server_default 付きの列追加（PG11+ は既存行の
書き換え無し）＋既定値の張り替え（カタログのみ）＋索引2本。現在の行数規模では
ACCESS EXCLUSIVE は一瞬で済む。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_case_ai_status"
down_revision: str | None = "0026_operator_app_invite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 既存案件は作成時に同期解析済み（結果が ai_summary に入っている）ため、既存行の
    # 値になる server_default は "done" で列を足し、その後に新規行向けの "pending" へ
    # 張り替える（r7 M-5: 全行 UPDATE を避けるため。PG11+ の add_column は既存行を
    # 書き換えず、alter_column の既定値変更はカタログ更新のみでテーブルを触らない）。
    op.add_column(
        "cases",
        sa.Column(
            "ai_status",
            sa.String(length=16),
            nullable=False,
            server_default="done",
        ),
    )
    op.alter_column(
        "cases",
        "ai_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default="pending",
    )
    op.add_column("cases", sa.Column("ai_failed_reason", sa.String(length=255), nullable=True))
    op.add_column("cases", sa.Column("idempotency_key", sa.String(length=64), nullable=True))

    op.create_index(op.f("ix_cases_ai_status"), "cases", ["ai_status"], unique=False)
    op.create_index(
        op.f("ix_cases_idempotency_key"), "cases", ["idempotency_key"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cases_idempotency_key"), table_name="cases")
    op.drop_index(op.f("ix_cases_ai_status"), table_name="cases")
    op.drop_column("cases", "idempotency_key")
    op.drop_column("cases", "ai_failed_reason")
    op.drop_column("cases", "ai_status")
