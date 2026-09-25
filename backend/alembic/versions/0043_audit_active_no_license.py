"""許可証画像が未提出のまま active な業者の件数を記録する（データ監査・読み取りのみ）

Revision ID: 0043_audit_active_no_license
Revises: 0042_review_verdict_contract
Create Date: 2026-09-25

alembic revision id は過去の alembic_version 全断障害の再発防止のため32文字以内を
厳守する（本リビジョンは28文字）。

背景（2026-09-25 ユーザー決定「招待コードで登録した業者も古物商許可証の提出を必須にする」）:
- 従来は招待コード付きの業者登録（POST /auth/operator/signup）が即 ``vendor_status='active'``
  （入札可）になり、許可証画像の提出も運営承認も経ていなかった。以後は招待コードの有無に
  関わらず pending で登録し、許可証提出＋運営承認（PATCH /admin/operators/{id}/verify）で
  active になる。
- 既に active の業者はユーザー決定により変更しない（入札中・成約中の取引を止めないため）。
  代わりに「active なのに許可証画像（license_image_uploaded_at）が無い・未削除の業者」の件数を
  INFO で残し、運営が個別に提出を依頼する判断材料にする（0038 と同じロガー方式）。
  0 件でも「確認した」事実を残すため常に出力する。
- DDL・値の変更は一切行わない（SELECT のみ）。downgrade は no-op。
- app のコードは import しない（列名・状態値は値を複製している）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_audit_active_no_license"
down_revision: str | None = "0042_review_verdict_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.versions.0043_audit_active_no_license")


def upgrade() -> None:
    # 読み取りのみ（行ロックを取らない）。operators は小規模で vendor_status に索引あり。
    bind = op.get_bind()
    active_without_license = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM operators"
            " WHERE vendor_status = 'active'"
            " AND license_image_uploaded_at IS NULL"
            " AND deleted_at IS NULL"
        )
    ).scalar_one()
    logger.info(
        "0043: 許可証画像が未提出のまま active な業者（未削除・停止中を含む）は %s 件でした"
        "（値は変更していません。1 件以上なら運営から許可証の提出を依頼すること）。",
        active_without_license,
    )


def downgrade() -> None:
    # 読み取りのみのリビジョンのため戻す操作は無い。
    pass
