"""bid_withdrawals を追記専用化 — UPDATE/DELETE を DB トリガーで拒否

Revision ID: 0021_bid_withdrawal_append_only
Revises: 0020_bid_withdrawal_fk_restrict
Create Date: 2026-09-03

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは31文字）。

背景（security review Medium M-2 対応）:
監査証跡 bid_withdrawals は追記専用であるべきだが、Render 管理 PostgreSQL では
アプリが DB オーナーロール（render.yaml: user=sokuri）で接続するため、
ロール権限の REVOKE ではオーナー自身の UPDATE/DELETE を防げない（再 GRANT 可能）。
そこで BEFORE UPDATE OR DELETE トリガーで例外を送出し、アプリのバグ・SQL
インジェクション・誤オペのいずれでも改変・削除が通らないようにする。
アプリ側（endpoints/bids.py）は INSERT しか発行しないため業務影響は無い。

意図的なメンテナンス（GDPR 削除要求等）が必要になった場合は、DB 管理者が
`ALTER TABLE bid_withdrawals DISABLE TRIGGER trg_bid_withdrawals_append_only`
を明示的に実行してから作業し、完了後 ENABLE に戻す運用とする。

テストスイートは SQLite のため本トリガーは検証対象外。本番反映後は
/readyz の alembic_version が本リビジョンになることで適用を確認する。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_bid_withdrawal_append_only"
down_revision: str | None = "0020_bid_withdrawal_fk_restrict"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNC = "bid_withdrawals_reject_mutation"
_TRIGGER = "trg_bid_withdrawals_append_only"
_TABLE = "bid_withdrawals"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNC}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '{_TABLE} is append-only (audit log): % rejected', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_FUNC}();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNC}()")
