"""case_photos.storage_key に UNIQUE制約を追加 — クロステナントでの写真破壊防止

Revision ID: 0017_case_photo_key_unique
Revises: 0016_case_item_user_edits
Create Date: 2026-09-02

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは26文字。ファイル名・revision値ともに元案の
"0017_case_photo_storage_key_unique"(34文字)から短縮した）。

背景（security review 指摘対応・H-1）:
``GET /files/{storage_key}`` は無認証のため、案件一覧を閲覧できる業者アカウントが
他人の案件の storage_key を収集できる。UNIQUE制約が無い状態では、収集した
storage_key を ``POST /cases/{自分のcase}/items/{自分のitem}/photos`` に送ると
「実ファイルが存在する」検証を通過して自分の商品の写真として登録できてしまい、
その後 ``DELETE /cases/{自分のcase}/photos/{その photo_id}`` で被害者の実ファイルを
物理削除できてしまう（ローカルディスク保存でバックアップ無し＝復旧不能）。

1つの実ファイル（storage_key）は常に高々1つの CasePhoto 行にのみ紐づく、という
不変条件をDB制約として強制することで、他人の storage_key を自分の商品に
「追加」しようとする経路そのものを拒否する（app/api/v1/endpoints/case_items.py の
``add_case_item_photo`` はこの制約違反を IntegrityError として捕捉し 409 を返す）。

前提: 本番データに storage_key の重複は存在しない（presign は毎回新規の
UUID hex を発行する設計のため、正規フローでは重複が発生し得ない）。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_case_photo_key_unique"
down_revision: str | None = "0016_case_item_user_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_case_photos_storage_key", "case_photos", ["storage_key"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_case_photos_storage_key", "case_photos", type_="unique"
    )
