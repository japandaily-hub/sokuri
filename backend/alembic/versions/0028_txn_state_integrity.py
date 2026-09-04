"""成約まわりの状態整合をDB制約で担保する（キャンセル一意 / 減額pending一意 / bid_id索引）

Revision ID: 0028_txn_state_integrity
Revises: 0027_case_ai_status
Create Date: 2026-09-04

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは23文字）。

背景（r6 監査）:
- M-2: `cancellations` に `transaction_id` の一意制約が無く、キャンセルの二重送信で
  記録が2行できて業者の `cancel_count` が2倍になる。
- M-4: `reduction_requests` の「未回答は1件だけ」がアプリ層の in-memory 判定だけで
  担保されており、同時2リクエストで pending が2行残ると業者が恒久的に409で
  締め出される。
- M-6 (Low): `transactions.bid_id` に索引が無く、業者の取引一覧と FK の RESTRICT
  検査が全走査になる（現規模では未顕在。将来の予防措置として同梱）。

適用上の注意（r6-review H3 で是正済み）:
- 旧版は一意制約を張る前に重複行が在れば RuntimeError で **適用自体を中断** して
  いた。alembic env.py は transaction_per_migration=True のため 0028 だけがロール
  バックし、0027 は適用済みのまま「制約が無いのに uvicorn は起動する」degraded な
  状態が発生し得た（transactions.py / reductions.py は IntegrityError→409 変換を
  前提に書かれており、制約が無いと二重キャンセル・二重 pending 減額を防げない）。
- 本版は重複を検知したら **止めずに自動是正** してから制約を張る（黙ってデータを
  壊さない範囲での自動運用）。
  - `cancellations`: transaction_id ごとに最古（created_at 昇順、同時刻は id 昇順）
    の1行だけを残し、残りを削除する。削除は監査証跡だが、キャンセル自体は他の
    キャンセル行として案件・取引に残るため実害は無い。
  - `reduction_requests`（status='pending'）: transaction_id ごとに最古の1行だけを
    pending のまま残し、残りを rejected へ更新する（重複申請のため自動却下。
    decide_reduction の status ガードにより pending のまま残ると業者が恒久的に
    409 で締め出されるため、rejected にして正常系へ戻す）。申請内容そのもの
    （reason 等）は監査目的で書き換えない。
  - いずれも削除・更新件数を alembic ログへ出力する（運営が事後に確認できるよう
    証跡を残す。r6-review H3）。
- downgrade はそのまま（バックフィル・自動是正は復元しない＝片道の是正）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_txn_state_integrity"
down_revision: str | None = "0027_case_ai_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0028_txn_state_integrity")


def _dedupe_cancellations() -> None:
    """cancellations.transaction_id の重複を、最古の1行だけ残して削除する（r6-review H3）。

    SQLite 3.25+ / PostgreSQL いずれもウィンドウ関数を解するため同一SQLで動く
    （0028 の部分一意索引が既に sqlite_where を使っており同方針）。
    """
    result = op.get_bind().execute(
        sa.text(
            "DELETE FROM cancellations WHERE transaction_id IS NOT NULL AND id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY transaction_id ORDER BY created_at ASC, id ASC"
            "    ) AS rn"
            "    FROM cancellations WHERE transaction_id IS NOT NULL"
            "  ) ranked WHERE rn = 1"
            ")"
        )
    )
    deleted = result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0
    if deleted:
        logger.info(
            "0028: cancellations.transaction_id の重複行を %s 件削除しました"
            "（transaction_id ごとに最古の1行のみ残存）。",
            deleted,
        )


def _reject_duplicate_pending_reductions() -> None:
    """reduction_requests(status='pending') の transaction_id 重複を最古以外 rejected にする。

    最古（created_at 昇順、同時刻は id 昇順）の1件だけを pending のまま残し、他は
    「重複申請のため自動却下」として rejected へ更新する（r6-review H3）。
    """
    result = op.get_bind().execute(
        sa.text(
            "UPDATE reduction_requests SET status = 'rejected' WHERE status = 'pending'"
            " AND id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY transaction_id ORDER BY created_at ASC, id ASC"
            "    ) AS rn"
            "    FROM reduction_requests WHERE status = 'pending'"
            "  ) ranked WHERE rn = 1"
            ")"
        )
    )
    updated = result.rowcount if result.rowcount is not None and result.rowcount > 0 else 0
    if updated:
        logger.info(
            "0028: reduction_requests の pending 重複を %s 件 rejected へ自動却下しました"
            "（理由: 重複申請のため自動却下。transaction_id ごとに最古の1件のみ pending 存続）。",
            updated,
        )


def upgrade() -> None:
    # ── 減額申請: 終端取引に取り残された pending を rejected へ是正する ──
    # （decide_reduction の status ガード追加により回答不能になるため）
    op.execute(
        sa.text(
            "UPDATE reduction_requests SET status = 'rejected'"
            " WHERE status = 'pending'"
            " AND transaction_id IN ("
            "   SELECT id FROM transactions WHERE status IN ('completed', 'cancelled')"
            " )"
        )
    )

    # ── 重複の自動是正（r6-review H3: RuntimeError で止めない） ──
    _dedupe_cancellations()
    _reject_duplicate_pending_reductions()

    # ── M-2: キャンセル記録は成約あたり1行（transaction_id が NULL の案件取り下げは対象外） ──
    # batch_alter_table 経由にする（r6-review H3 附帯修正）: SQLite は既存テーブルへの
    # ALTER TABLE ADD CONSTRAINT を一切サポートせず、素の op.create_unique_constraint は
    # NotImplementedError で即死する。batch モードは SQLite でのみコピー＆リネーム戦略へ
    # 切り替わり、PostgreSQL では通常の ALTER TABLE のまま実行される（無害）ため両対応。
    with op.batch_alter_table("cancellations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_cancellations_transaction_id", ["transaction_id"]
        )

    # ── M-4: 未回答の減額申請は成約あたり1件（部分一意索引） ──
    op.create_index(
        "uq_reduction_requests_pending",
        "reduction_requests",
        ["transaction_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )

    # ── M-6: 業者の取引一覧・FK RESTRICT 検査の索引 ──
    op.create_index(
        op.f("ix_transactions_bid_id"), "transactions", ["bid_id"], unique=False
    )


def downgrade() -> None:
    # pending → rejected のバックフィル・重複の自動是正は復元しない（元の状態を
    # 記録していないため）。
    op.drop_index(op.f("ix_transactions_bid_id"), table_name="transactions")
    op.drop_index("uq_reduction_requests_pending", table_name="reduction_requests")
    with op.batch_alter_table("cancellations") as batch_op:
        batch_op.drop_constraint("uq_cancellations_transaction_id", type_="unique")
