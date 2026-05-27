"""add albums and album_items tables

Revision ID: 0003_add_albums
Revises: 0002_add_defect_evidence
Create Date: 2026-05-26

「まとめてソクウリ」一括査定アルバム機能（ADR-002 Phase 2）。
albums: 複数 assessment の束、ユーザー連絡先（業者非開示）を保持。
album_items: album → assessment の中間テーブル（順序保持）。

実装メモ:
- 過去デプロイ失敗で部分残存している場合に備え、DROP IF EXISTS で前掃除。
- ENUM 型 albumstatus と各テーブル / インデックスは **全て raw SQL** で
  作成する。`sa.Enum(...) + create_type=False` を `op.create_table` 内で
  使うと alembic 内部で再度 CREATE TYPE が発行されエラーになる挙動が
  asyncpg + alembic 1.x の組み合わせで再現したため、迂回している。
- Phase 1 ではユーザーデータが投入されていないため CASCADE 削除は安全。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_add_albums"
down_revision: str | None = "0002_add_defect_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 1. 残存物の完全掃除 ----
    op.execute("DROP TABLE IF EXISTS album_items CASCADE")
    op.execute("DROP TABLE IF EXISTS albums CASCADE")
    op.execute("DROP TYPE IF EXISTS albumstatus")

    # ---- 2. ENUM 型 ----
    op.execute(
        "CREATE TYPE albumstatus AS ENUM "
        "('draft', 'submitted', 'bidding', 'matched', 'closed', 'cancelled')"
    )

    # ---- 3. albums テーブル（raw SQL で alembic enum バグを回避） ----
    op.execute(
        """
        CREATE TABLE albums (
            id UUID PRIMARY KEY,
            lead_email VARCHAR(320),
            status albumstatus NOT NULL DEFAULT 'draft',
            total_estimated_jpy BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT total_estimated_jpy_non_negative
                CHECK (total_estimated_jpy >= 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_albums_status ON albums (status)")

    # ---- 4. album_items テーブル ----
    op.execute(
        """
        CREATE TABLE album_items (
            id UUID PRIMARY KEY,
            album_id UUID NOT NULL,
            assessment_id UUID NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_album_items_album_id_albums
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
            CONSTRAINT fk_album_items_assessment_id_assessments
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE RESTRICT,
            CONSTRAINT position_non_negative CHECK (position >= 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_album_items_album_id ON album_items (album_id)")
    op.execute(
        "CREATE INDEX ix_album_items_assessment_id ON album_items (assessment_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_album_items_assessment_id")
    op.execute("DROP INDEX IF EXISTS ix_album_items_album_id")
    op.execute("DROP TABLE IF EXISTS album_items")
    op.execute("DROP INDEX IF EXISTS ix_albums_status")
    op.execute("DROP TABLE IF EXISTS albums")
    op.execute("DROP TYPE IF EXISTS albumstatus")
