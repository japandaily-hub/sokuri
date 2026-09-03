"""bid_withdrawals のFKをCASCADE→RESTRICTへ変更 + スナップショット列追加 + bid_id一意制約

Revision ID: 0020_bid_withdrawal_fk_restrict
Revises: 0019_bid_withdrawal_audit
Create Date: 2026-09-03

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは31文字）。

背景（security review 2周目 Medium指摘対応）:
0019で新設した bid_withdrawals の bid_id/case_id/operator_id は
ON DELETE CASCADE で定義されていたため、親行（bids/cases/operators）が
削除されると監査証跡ごと消えてしまい、不正調査・カスタマーサポート対応の
記録としての目的を果たせなくなる欠陥があった。RESTRICTへ変更し、親行の
削除自体を証跡が存在する限りDBレベルで拒否するようにする。

あわせて、RESTRICT化のみでは親行の主キーが残っている前提でしか事実関係を
辿れないため（例: 将来的な運用変更でRESTRICTを緩めた場合の保険）、取り下げ
時点の値を非正規化スナップショットとして company_name / amount 列に保持する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_bid_withdrawal_fk_restrict"
down_revision: str | None = "0019_bid_withdrawal_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "bid_withdrawals"
_FK_SPECS = (
    ("fk_bid_withdrawals_bid_id_bids", "bid_id", "bids"),
    ("fk_bid_withdrawals_case_id_cases", "case_id", "cases"),
    ("fk_bid_withdrawals_operator_id_operators", "operator_id", "operators"),
)


def upgrade() -> None:
    for fk_name, local_col, remote_table in _FK_SPECS:
        op.drop_constraint(fk_name, _TABLE, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            _TABLE,
            remote_table,
            [local_col],
            ["id"],
            ondelete="RESTRICT",
        )

    op.add_column(
        _TABLE,
        sa.Column("company_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        _TABLE,
        sa.Column("amount", sa.BigInteger(), nullable=False, server_default="0"),
    )
    # server_default は既存行（本番投入前のためデータは無い想定）を埋めるための
    # 一時措置。以降の新規INSERTはアプリ側で必ず実値を渡すため、恒久的な既定値
    # として残す意味は無く撤去する（0004等の既存マイグレーションと同じ作法）。
    op.alter_column(_TABLE, "company_name", server_default=None)
    op.alter_column(_TABLE, "amount", server_default=None)

    # 「1入札につき取り下げは1回」（withdrawn は終端状態）をDB側でも保証する。
    # 0019 の通常インデックスは一意制約が作る暗黙インデックスと重複するため撤去。
    op.drop_index("ix_bid_withdrawals_bid_id", table_name=_TABLE)
    op.create_unique_constraint("uq_bid_withdrawals_bid_id", _TABLE, ["bid_id"])


def downgrade() -> None:
    op.drop_constraint("uq_bid_withdrawals_bid_id", _TABLE, type_="unique")
    op.create_index("ix_bid_withdrawals_bid_id", _TABLE, ["bid_id"])
    op.drop_column(_TABLE, "amount")
    op.drop_column(_TABLE, "company_name")

    for fk_name, local_col, remote_table in _FK_SPECS:
        op.drop_constraint(fk_name, _TABLE, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            _TABLE,
            remote_table,
            [local_col],
            ["id"],
            ondelete="CASCADE",
        )
