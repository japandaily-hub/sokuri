"""status 系カラムの server_default 二重引用を是正する。

Revision ID: 0012_fix_status_defaults
Revises: 0011_line_user_id
Create Date: 2026-07-17

背景:
SQLAlchemy の ``server_default`` に文字列を渡すと SQL リテラルとして引用符付与・
エスケープされる（``server_default="limited"`` → ``DEFAULT 'limited'``）。
0004 は ``server_default="'draft'"`` のように**引用符込み**で渡していたため、
実 DDL が ``DEFAULT '''draft'''`` となり、既定値は「引用符を含む7文字の文字列
``'draft'``」になっていた（cases/bids/transactions/reduction_requests の status
4箇所）。ORM は常に明示値を送るため実害は未発現だが、default 依存の INSERT が
入った瞬間にアプリのステータス判定と一致しない壊れ値が書かれる休眠バグ。

0004 の定義自体も同時に修正済み（新規 DB は最初から正しい既定値になる）。
本リビジョンは既存 DB の是正用で、正しい既定値の DB に対しても同値 SET のため
安全（冪等）。防御的に、壊れ既定値で書かれた行が万一存在した場合のクリーニング
UPDATE も行う（ORM 経由のデータには影響しない）。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0012_fix_status_defaults"
down_revision: str | None = "0011_line_user_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (テーブル, 正しい既定値) の対応。壊れ値は「引用符を含む文字列」なので
# SQL リテラルでは '''draft''' のように二重エスケープで表現される。
_TARGETS: list[tuple[str, str]] = [
    ("cases", "draft"),
    ("bids", "pending"),
    ("transactions", "pending"),
    ("reduction_requests", "pending"),
]


def upgrade() -> None:
    for table, default in _TARGETS:
        op.execute(
            text(f"ALTER TABLE {table} ALTER COLUMN status SET DEFAULT '{default}'")
        )
        # 壊れ既定値（'{default}' という引用符込み文字列）で保存された行の是正。
        # 通常は 0 行（ORM は明示値を送るため）。
        op.execute(
            text(
                f"UPDATE {table} SET status = '{default}' "
                f"WHERE status = '''{default}'''"
            )
        )


def downgrade() -> None:
    # 旧挙動（壊れた既定値）への復元は無意味かつ有害なため行わない。
    # スキーマ互換性に影響しないため no-op とする。
    pass
