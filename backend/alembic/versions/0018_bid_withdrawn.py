"""bids.status に 'withdrawn' を追加 — 入札取り下げ機能

Revision ID: 0018_bid_withdrawn
Revises: 0017_case_photo_key_unique
Create Date: 2026-09-03

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは19文字）。

背景:
業者が自身の入札（pending状態）を取り下げられるようにするため、``ck_bids_status``
CHECK制約に 'withdrawn' を追加する。取り下げは終端状態（再入札不可・再選択不可）。

downgrade では、旧CHECK制約（'withdrawn' を許容しない）へ戻す前に、既存の
'withdrawn' 行を 'rejected' へ変換する。変換せずに制約だけ戻すと、既存の
'withdrawn' 行がCHECK制約違反の状態のままDBに残ってしまう（他の更新の
きっかけで初めて違反が顕在化する時限爆弾になるため、ここで先に正規化する）。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_bid_withdrawn"
down_revision: str | None = "0017_case_photo_key_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_bids_status", "bids", type_="check")
    op.create_check_constraint(
        "ck_bids_status",
        "bids",
        "status IN ('pending','selected','rejected','withdrawn')",
    )


def downgrade() -> None:
    op.execute("UPDATE bids SET status='rejected' WHERE status='withdrawn'")
    op.drop_constraint("ck_bids_status", "bids", type_="check")
    op.create_check_constraint(
        "ck_bids_status",
        "bids",
        "status IN ('pending','selected','rejected')",
    )
