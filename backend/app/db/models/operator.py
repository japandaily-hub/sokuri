"""Operator model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:  # 型注釈の前方参照（"Bid" / "ReductionRequest"）の解決用。実行時は循環 import を避けて読まない。
    from app.db.models.bid import Bid
    from app.db.models.transaction import ReductionRequest


class Operator(Base, TimestampMixin):
    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    license_number: Mapped[Optional[str]] = mapped_column(String(128))
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # ★平均（旧形式の rating）は撤去済み: alembic 0042 でアプリの読み書きを止め、モデルのマップも
    # 外した（DB 列の削除は alembic 0044_drop_rating_columns）。マップしないので INSERT・SELECT に
    # 現れず、列がある DB（0044 適用前）でも無い DB（適用後）でも同じコードで動く。
    # 顧客→業者レビューの件数（reviews.py・admin.py が投稿・非表示の時に再計算する非正規化列）。
    # 入札一覧・業者一覧の表示用。
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 評価の内訳（よかった／伸びしろ。alembic 0040）。review_count と同じ母集団
    # （顧客→業者・非表示を除く）で、常に review_count = good_count + improve_count。
    # 再計算の正本は services/review_stats.py。GET /vendors の並び順のキーでもある。
    good_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    improve_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
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
    # 退会（論理削除・匿名化）日時。User.deleted_at と同じ意味・同じゲート
    # （deps.assert_operator_not_revoked が業者を解決する全経路で旧トークンを
    # 即時失効させる）。物理削除はしない
    # ＝ 完了済み取引・レビュー・キャンセル記録を依頼者側の記録として保持するため。
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # 停止に伴うセッション失効の境界（User.sessions_revoked_at と同じ意味・alembic 0039）。
    # 運営が停止した時刻を入れ、iat がこの時刻以前のトークンを
    # deps.assert_operator_not_revoked が業者を解決する全経路で 401 にする。停止中は
    # assert_operator_not_suspended の 403 が優先される。実際の解除時は解除時刻へ進め、NULL には
    # 戻さない（戻すと停止前のトークンが解除後に復活するため）。NULL＝一度も停止されていない。
    sessions_revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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
