"""DefectEvidence モデル — 瑕疵エビデンス写真の永続化。

Phase 4 で実装。/assessments/{id}/defects エンドポイントが保存する。
1 査定に対し複数の瑕疵エビデンスを登録できる（例: 傷・割れ・動作不良の各写真）。

設計判断: Assessment との関係を CASCADE DELETE とし、査定削除時に
エビデンスも連鎖削除する。オブジェクトストレージへの実アップロードは
Phase 5 以降の非同期タスクに委譲するため、本テーブルは *キー* のみを保持する。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.assessment import Assessment


class DefectEvidence(Base, TimestampMixin):
    """瑕疵エビデンス写真の 1 件。

    assessment_id → Assessment の CASCADE DELETE を保証する。
    image_object_key はオブジェクトストレージのキー（内部参照用）。
    TODO(Phase 5): 実オブジェクトストレージ（S3/GCS）への非同期アップロードを実装する。
    """

    __tablename__ = "defect_evidences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # オブジェクトストレージのキー（例: "defects/{assessment_id}/{defect_id}.jpg"）
    image_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 瑕疵の補足説明（任意。例: "左側面に 2cm 程度の傷"）。
    description: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped["Assessment"] = relationship(
        back_populates="defect_evidences",
        foreign_keys=[assessment_id],
    )
