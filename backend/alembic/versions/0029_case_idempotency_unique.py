"""cases.(user_id, idempotency_key) に一意制約を追加する（M2, r6-verify-fix）

Revision ID: 0029_case_idempotency_unique
Revises: 0028_txn_state_integrity
Create Date: 2026-09-05

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは28文字）。

背景（r6-verify-fix 監査 M2）:
- 案件作成の冪等キー重複判定（``_find_idempotent_case_id``）はアプリ層の
  SELECT→INSERT に過ぎず、非原子であるため同時2リクエスト（二度押し・プロキシ
  再送信）で同一 ``idempotency_key`` の案件が2件作成されうる（r6 H-1 が防ごう
  とした事象そのものが、DB制約なしでは完全には防げていなかった）。
- 0028 と同じ流儀（重複を検知したら止めずに自動是正してから制約を張る）を踏襲する。
  ただし対象は業務データの本体である ``cases`` 行そのものであり、0028 の
  ``cancellations`` のように重複行を DELETE すると案件データを失ってしまう。
  そのため本マイグレーションは重複行を削除せず、最古の1行だけ ``idempotency_key``
  を残し、それ以外は NULL 化する（NULL は標準SQLの一意制約セマンティクス上
  対象外となるため、案件データを一切失わずに制約を張れる）。NULL化される古い
  重複キーは既にアプリ層の10分窓を超えて参照されないため実害はない。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_case_idempotency_unique"
down_revision: str | None = "0028_txn_state_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0029_case_idempotency_unique")


def _dedupe_case_idempotency_keys() -> None:
    """cases.(user_id, idempotency_key) の重複を、最古の1行だけ残し他はNULL化する。

    cancellations（0028）と異なり行自体は案件の実データのため削除しない。
    SQLite 3.25+ / PostgreSQL いずれもウィンドウ関数を解する（0028 と同方針）。
    """
    result = op.get_bind().execute(
        sa.text(
            "UPDATE cases SET idempotency_key = NULL WHERE idempotency_key IS NOT NULL"
            " AND id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY user_id, idempotency_key ORDER BY created_at ASC, id ASC"
            "    ) AS rn"
            "    FROM cases WHERE idempotency_key IS NOT NULL"
            "  ) ranked WHERE rn = 1"
            ")"
        )
    )
    updated = result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0
    if updated:
        logger.info(
            "0029: cases.(user_id, idempotency_key) の重複行を %s 件 NULL 化しました"
            "（ユーザー・キーごとに最古の1行のみ idempotency_key を保持。案件行自体は削除していません）。",
            updated,
        )


def upgrade() -> None:
    _dedupe_case_idempotency_keys()

    # batch_alter_table 経由にする（0028 と同じ理由）: SQLite は既存テーブルへの
    # ALTER TABLE ADD CONSTRAINT を一切サポートせず、素の op.create_unique_constraint は
    # NotImplementedError で即死する。batch モードは SQLite でのみコピー＆リネーム戦略へ
    # 切り替わり、PostgreSQL では通常の ALTER TABLE のまま実行される（無害）ため両対応。
    with op.batch_alter_table("cases") as batch_op:
        batch_op.create_unique_constraint(
            "uq_cases_user_id_idempotency_key", ["user_id", "idempotency_key"]
        )


def downgrade() -> None:
    # NULL化による自動是正は復元しない（元の値を記録していないため。0028と同方針）。
    with op.batch_alter_table("cases") as batch_op:
        batch_op.drop_constraint("uq_cases_user_id_idempotency_key", type_="unique")
