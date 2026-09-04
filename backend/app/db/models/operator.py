"""Operator model."""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Operator(Base, TimestampMixin):
    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    license_number: Mapped[Optional[str]] = mapped_column(String(128))
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rating: Mapped[Optional[float]] = mapped_column(Float)
    # 顧客→業者レビューの集計（reviews.py で投稿時に再計算する非正規化列）。
    # rating と同じ扱いで、入札一覧・業者一覧の表示用。
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latest_review_comment: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    cancel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    invite_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    vendor_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(512))
    agreed_terms_version: Mapped[Optional[str]] = mapped_column(String(32))
    agreed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # LINE Login の userId（LINE Push通知の宛先にも使用）。未連携は NULL。
    line_user_id: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )

    # ── 古物商許可証画像（審査書類。認証必須の専用エンドポイントでのみ配信） ──
    # BLOB本体は deferred=True とし、admin一覧等の既存の select(Operator) /
    # session.get(Operator, ...) では一切ロードされないようにする
    # （全業者関連クエリでBLOBが毎回ロードされるとメモリ枯渇DoSの原因になるため）。
    # 明示的に取得する場合は sqlalchemy.orm.undefer() でオプトインするか、
    # Core の select(Operator.license_image_data, ...) で直接列を指定すること。
    license_image_data: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, deferred=True, nullable=True
    )
    license_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    license_image_uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def has_license_image(self) -> bool:
        """許可証画像の登録有無（BLOB本体を読まず uploaded_at のみで判定する）。"""
        return self.license_image_uploaded_at is not None

    bids: Mapped[List["Bid"]] = relationship(
        "Bid",
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reduction_requests: Mapped[List["ReductionRequest"]] = relationship(
        "ReductionRequest",
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
