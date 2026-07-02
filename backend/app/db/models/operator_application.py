"""OperatorApplication model — /business 業者事前申込フォームの保存先。

全業者は管理者承認必須（招待コードありでも即active化はしない）。本テーブルは
承認前の申込内容（会社情報・古物商許可番号・振込先口座等）を保持し、admin の
承認/却下オペレーションの起点となる。

振込先口座（bank_account_enc）は平文を保存しない。``app.core.crypto.encrypt_json``
で暗号化した JSON 文字列を格納する。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OperatorApplication(Base, TimestampMixin):
    __tablename__ = "operator_applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # "received" / "approved" / "rejected"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received", index=True)

    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    representative_name: Mapped[str] = mapped_column(String(255), nullable=False)
    registered_address: Mapped[str] = mapped_column(String(512), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # unique制約なし: 同一担当者が複数申込を行うケース（訂正・再申込）を許容するため。
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    license_number: Mapped[str] = mapped_column(String(128), nullable=False)
    business_type: Mapped[Optional[str]] = mapped_column(String(16))
    service_area: Mapped[Optional[str]] = mapped_column(String(32))
    categories: Mapped[Optional[str]] = mapped_column(String(255))
    message: Mapped[Optional[str]] = mapped_column(Text)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(20))
    # 暗号化済み JSON 文字列（app.core.crypto.encrypt_json の出力）。平文は保存しない。
    bank_account_enc: Mapped[Optional[str]] = mapped_column(Text)

    agreed_terms_version: Mapped[Optional[str]] = mapped_column(String(32))
    agreed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[Optional[str]] = mapped_column(String(500))

    # 承認後に発行された Operator への参照（承認フローで Invite 発行のみ行い、
    # Operator 自体は業者本人の /operator/signup 完了時に作成されるため、
    # 承認直後は None のままになり得る）。
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="SET NULL"), nullable=True
    )

    # 送信元IPアドレス（IPv6も許容し余裕を持たせた長さ）。レート制限・不正申込の追跡に使用。
    # X-Forwarded-For が無い直接接続環境では None にはならないが、プロキシ構成が
    # 不明な場合に備え nullable にしておく（欠損してもアプリを壊さない）。
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
