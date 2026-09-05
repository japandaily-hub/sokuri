"""ContactMessage モデル — 公開フォーム（POST /contact）からの問い合わせ本文。

r10 O-M6 対応。従来 ``/contact`` は ADMIN_EMAILS へメールを投げるだけで、DB には
一切残していなかった。そのため
1. ADMIN_EMAILS 未設定・Brevo 障害・迷惑メール振り分けのいずれか一つで、
   問い合わせが**痕跡ゼロで消える**（依頼者には 202 が返るため誰も気づけない）
2. 停止（is_suspended）中のアカウントは ``SUSPENDED_ACCOUNT_DETAIL`` により
   「お問い合わせ窓口までご連絡ください」と案内されるが、その受け皿が
   運営の個人メールボックスしか無く、対応漏れ・二重対応を検知できない
という2つの実害があった。メール送信は既存のまま維持し（速報性）、DB は
**取りこぼしのない台帳**として併走させる。

設計方針:
- 認証不要のエンドポイントが唯一の書き込み元。行の増加は contact.py の
  レート制限（IP軸・アカウント軸）とプロセス内キャップで律速される。
- ``handled_at`` / ``handled_by_admin_id`` は運営の対応状況の追跡用。
  未対応 = ``handled_at IS NULL``（部分索引ではなく通常索引 + 述語で足りる規模）。
- 運営アカウントが削除されても対応履歴は残すため ON DELETE SET NULL
  （0031 の ``cancelled_by_admin_id`` と同方針）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ContactMessage(Base, TimestampMixin):
    """公開フォームからの問い合わせ1件（受信台帳）。"""

    __tablename__ = "contact_messages"
    __table_args__ = (
        # 運営の既定動線は「未対応を新着順に処理する」。絞込（handled_at）と
        # 並び（created_at desc）を 1 本で賄う複合索引にし、一覧の全走査を避ける
        # （handled=true 側の絞込にも同じ索引が使える）。
        Index("ix_contact_messages_handled_at_created_at", "handled_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 自己申告の値（認証されていない）。ContactCreateRequest 側で長さ・制御文字を
    # 検証済みのものだけがここに到達する。
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # ContactCategory（Literal 8値）の値をそのまま保存する。CHECK 制約は付けない:
    # 分類の追加は運用上ありえ、制約違反で問い合わせ自体を取りこぼす方が損失が
    # 大きい（値の妥当性は Pydantic 側で担保済み）。
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # 対応済みの記録。未対応は NULL（既定値）。
    handled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    handled_by_admin_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
