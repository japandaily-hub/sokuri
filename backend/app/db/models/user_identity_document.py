"""UserIdentityDocument モデル — 依頼者の本人確認書類（**受付廃止済み**の過去の記録）。

かつて依頼者が任意で身分証（運転免許証・マイナンバーカード等）の画像を提出し、
admin が承認/却下していた。身分証の画像を預かること自体のリスクを避けるため、
2026-11 に受付を全面的にやめた（API は 410・user_identity.py）。保存済みの画像は
alembic 0049 で消去済みで、今後この表に画像が書き込まれる経路は無い。

表は、提出日時・書類種別・審査結果を運営の操作履歴（admin.py のアクティビティ）として
読むためだけに残す。画像列は退会時の匿名化（users.py）で NULL にする処理が残るのみ。
お引き取りの際の本人確認は、古物営業法第15条に基づき訪問する古物商（業者）が行う。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# doc_type の許容値（alembic 0023 のCHECK制約と一致させる）。
DOC_TYPE_DRIVERS_LICENSE = "drivers_license"
DOC_TYPE_MY_NUMBER_CARD = "my_number_card"
DOC_TYPE_PASSPORT = "passport"
DOC_TYPE_RESIDENCE_CARD = "residence_card"
DOC_TYPE_HEALTH_INSURANCE_CARD = "health_insurance_card"

DOC_TYPES = (
    DOC_TYPE_DRIVERS_LICENSE,
    DOC_TYPE_MY_NUMBER_CARD,
    DOC_TYPE_PASSPORT,
    DOC_TYPE_RESIDENCE_CARD,
    DOC_TYPE_HEALTH_INSURANCE_CARD,
)
# 新規提出で受け付ける書類種別は無い（受付廃止）。DOC_TYPES は DB の CHECK 制約と
# 一致させるため、過去の記録の読み取り用に残す。

# status の許容値（alembic 0023 のCHECK制約と一致させる）。
DOCUMENT_STATUS_PENDING = "pending"
DOCUMENT_STATUS_APPROVED = "approved"
DOCUMENT_STATUS_REJECTED = "rejected"


class UserIdentityDocument(Base, TimestampMixin):
    """依頼者が提出した本人確認書類（1提出につき1レコード。再提出は新規レコード）。"""

    __tablename__ = "user_identity_documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('drivers_license','my_number_card','passport',"
            "'residence_card','health_insurance_card')",
            name="ck_user_identity_documents_doc_type",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_user_identity_documents_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # BLOB本体は deferred=True（select(UserIdentityDocument) 等の通常クエリで
    # 毎回ロードされないようにする。明示取得は Core の列指定 select を使うこと。
    # front_image_data のみ退会時の匿名化で None にするため nullable=True
    # （提出時は必ず値が入るが、匿名化後はDBの正規化制約上 NULL を許容する必要がある）。
    front_image_data: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, deferred=True, nullable=True
    )
    # MIMEタイプ自体は機微情報ではないため、退会後も保持する（NOT NULL のまま）。
    front_image_content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    back_image_data: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, deferred=True, nullable=True
    )
    back_image_content_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DOCUMENT_STATUS_PENDING
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # NOTE: has_back（裏面画像の保存有無）はプロパティとして生やさない。
    # front_image_data/back_image_data は deferred=True のため、ORM インスタンス
    # 経由でのアクセスは AsyncSession 上で MissingGreenlet を誘発しうる
    # （operator_license.py の _load_license_image と同じ理由）。判定が必要な
    # 箇所では必ず Core の列指定 select（例:
    # ``select(UserIdentityDocument.back_image_data.isnot(None))``）を使うこと。
