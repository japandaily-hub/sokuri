"""Message モデル — 成約チャット（ユーザー・業者・システム間のやり取り）。

住所非開示ポリシーとの関係:
- 承認待ち（vendor_status != "active"）業者が落札した成約でもチャット自体は開く
  （住所詳細のみ非開示。会話は許可という確定方針）。本モデル・エンドポイントは
  この方針を前提に、権限チェックのみ当事者性で行い vendor_status では制限しない。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.transaction import Transaction


class Message(Base, TimestampMixin):
    """成約チャットの1メッセージ。

    ``kind`` の種別:
      "text"               ユーザー・業者の通常発言
      "schedule_proposal"  業者からの日程候補提示（meta.slots に候補一覧）
      "schedule_confirmed" ユーザーによる日程確定（システムメッセージ）
      "system"             その他システム通知
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # "user" | "operator" | "system"
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # "text" | "schedule_proposal" | "schedule_confirmed" | "system"
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # relations
    transaction: Mapped["Transaction"] = relationship()

    __table_args__ = (
        Index("ix_messages_transaction_id_created_at", "transaction_id", "created_at"),
    )
