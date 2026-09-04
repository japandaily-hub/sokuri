"""User モデル — カタヅケ利用者（role=\'admin\' で管理者）。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# users.identity_status の許容値（alembic 0022 のCHECK制約と一致させる）。
IDENTITY_STATUS_UNVERIFIED = "unverified"
IDENTITY_STATUS_PENDING = "pending"
IDENTITY_STATUS_APPROVED = "approved"
IDENTITY_STATUS_REJECTED = "rejected"


class User(Base, TimestampMixin):
    """email + password 認証のユーザーアカウント。

    LINEログイン専用ユーザー（password_hash=None）も許容する（line_user_id 参照）。
    """

    __tablename__ = "users"
    __table_args__ = (
        # DB側（alembic 0022）に既に存在するCHECK制約をORMメタデータ側にも反映する。
        # これが無いと Base.metadata.create_all（テスト環境のスキーマ生成）では
        # この制約が作られず、不正な identity_status 値のINSERTがテストで
        # 検知できなくなる（bid.py の ck_bids_status と同じ考え方）。
        CheckConstraint(
            "identity_status IN ('unverified','pending','approved','rejected')",
            name="ck_users_identity_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # LINE専用アカウントはパスワードを持たないため nullable。
    password_hash: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    # LINE Login の userId（LINE Push通知の宛先にも使用）。未連携は NULL。
    line_user_id: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )

    # ── プロフィール（マイページ /users/me/profile で編集） ─────────────
    # name は「表示用キャッシュ」として残し、プロフィール更新時に
    # f"{family_name} {given_name}" で同期更新する（既存参照箇所との互換維持）。
    family_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    given_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    family_name_kana: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    given_name_kana: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    residence_area: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # ── マイページ拡張PII（本人確認・振込先口座・住所） ──────────────
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    occupation: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 郵便番号は数字7桁のみを保存する（ハイフンは受信時に除去。schemas 側で正規化）。
    postal_code: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    prefecture: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    address_line1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 振込先口座（暗号化済みJSON文字列。app.core.crypto.encrypt_json の出力。平文は保存しない）。
    bank_account_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 口座情報の最終更新時刻。users.updated_at は他のプロフィール更新でも
    # 動くため、口座専用の更新時刻を別カラムで持つ（表示の意味論を正しく保つ）。
    bank_account_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 本人確認ステータス（user_identity_documents の最新提出結果を反映する非正規化キャッシュ）。
    identity_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IDENTITY_STATUS_UNVERIFIED
    )

    # 論理削除マーカー（退会済みアカウントの旧JWTを deps.py で即時失効させるゲートに使用）。
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # パスワード変更時刻（JWT失効ゲート用。iat がこれより古いトークンを deps.py で拒否する）。
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
