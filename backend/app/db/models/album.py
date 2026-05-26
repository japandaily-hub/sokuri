"""Album / AlbumItem モデル — 「まとめてソクウリ」一括査定束（ADR-002 Phase 2）。

設計判断:
- Album は **複数の Assessment を束ねる**。assessment は既存テーブルを再利用し、
  album 経由で「家まるごと」の単位を表現する。
- Phase 2 では業者連携（businesses / bids）は未実装。Wizard of Oz 運用で
  管理者が手動でメール転送する。Phase 3 で bids テーブル + 通知 API 追加。
- ``lead_email`` は業者へ非開示。営業電話ゼロ保証の根拠（ADR-002 該当節）。
- ``total_estimated_jpy`` はフロントの AI 試算合計（業者の最終入札額とは別物）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.models.enums import AlbumStatus

if TYPE_CHECKING:
    from app.db.models.assessment import Assessment


class Album(Base, TimestampMixin):
    """一括査定アルバム — 複数アイテムの束。

    ユーザー個人情報は ``lead_email`` のみ保持。**業者には絶対に渡さない**。
    成約決定後（status=MATCHED）に限り、運営から業者へ連絡先を開示する。
    """

    __tablename__ = "albums"
    __table_args__ = (
        CheckConstraint(
            "total_estimated_jpy >= 0",
            name="total_estimated_jpy_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # ユーザー連絡先（業者非開示）。Phase 3 でユーザーテーブル化したら user_id へ。
    lead_email: Mapped[str | None] = mapped_column(String(320))
    # アルバム状態。Phase 2 では SUBMITTED 止まりで、運用が手動で BIDDING に進める。
    status: Mapped[AlbumStatus] = mapped_column(
        pg_enum(AlbumStatus), nullable=False, default=AlbumStatus.DRAFT, index=True
    )
    # AI 試算の合計（業者入札の最低価格目安として使用される、確定値ではない）。
    total_estimated_jpy: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    items: Mapped[list["AlbumItem"]] = relationship(
        back_populates="album",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AlbumItem.position",
    )


class AlbumItem(Base, TimestampMixin):
    """アルバム内の 1 商品（assessments への参照）。

    ``position`` で並び順を保持（ユーザーが並べ替えた順序を尊重）。
    同一 album_id 内で assessment_id は一意（同じ商品を 2 回入れることは不可）。
    """

    __tablename__ = "album_items"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    album_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    album: Mapped["Album"] = relationship(back_populates="items")
    assessment: Mapped["Assessment"] = relationship()
