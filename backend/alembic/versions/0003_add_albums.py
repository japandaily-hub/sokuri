"""no-op placeholder (Phase 2 albums migration deferred)

Revision ID: 0003_add_albums
Revises: 0002_add_defect_evidence
Create Date: 2026-05-26

このリビジョンは現在 **no-op**（何も実行しない）。

経緯:
- 当初 albums / album_items テーブル + albumstatus ENUM を作る予定だった
- 過去の失敗デプロイで部分残存した ENUM/テーブルにより、何度作り直しても
  ``DuplicateObjectError: type "albumstatus" already exists`` で healthcheck failure
- AI 解析機能（Gemini 2.5 Flash 切替）の本番反映を優先するため、
  Phase 2 マイグレーションは保留し、本リビジョンは空にする

復旧手順（Phase 2 再開時）:
1. 手動で DB に接続し ``DROP TYPE IF EXISTS albumstatus CASCADE`` を実行
2. ``DROP TABLE IF EXISTS album_items, albums CASCADE`` を実行
3. 新リビジョン 0004_create_albums.py を作成し raw SQL でテーブル作成
4. app/api/v1/router.py の albums_router import/include をアンコメント
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0003_add_albums"
down_revision: str | None = "0002_add_defect_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op. Phase 2 albums migration is deferred."""
    pass


def downgrade() -> None:
    """No-op."""
    pass
