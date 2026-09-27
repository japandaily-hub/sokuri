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
      "schedule_proposal"  業者からの日程候補提示（sender_type="operator"）。meta v2:
                           {"v": 2, "seq": 取引内の提示の通し番号（最大値＝最新の提示）,
                           "candidates": [{"date": "YYYY-MM-DD", "start": "HH:MM"|null,
                           "end": "HH:MM"|null, "label": サーバーが作る表示}]}。
                           旧形式（v1）は meta.slots（業者の自由記述の一覧）だけを持ち、
                           表示にだけ使う（日程構造化 DESIGN §3）
      "schedule_confirmed" 日程確定（システムメッセージ）。meta v2: {"v": 2,
                           "source": "proposal"|"calendar", "proposal_id"・
                           "candidate_index"（source="proposal" のときだけ）,
                           "visit_date", "visit_time_slot", "label",
                           "confirmed_by": "user"|"admin"}。旧形式は meta.visit_date・
                           meta.visit_time_slot だけ
      "complete_request"   業者からの完了確定の依頼（sender_type="operator"）
      "completed"          完了確定（システムメッセージ。meta.final_amount・
                           meta.completed_by="user"|"admin"）
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
    # "text" | "schedule_proposal" | "schedule_confirmed" | "complete_request" |
    # "completed" | "system"
    # 32文字: 0046 で 16 → 32 に拡幅（schedule_proposal=17字・schedule_confirmed=18字が
    # 旧列長を超えており、PostgreSQL では INSERT が失敗しうる潜在不具合だった）。
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # relations
    transaction: Mapped["Transaction"] = relationship()

    __table_args__ = (
        Index("ix_messages_transaction_id_created_at", "transaction_id", "created_at"),
    )
