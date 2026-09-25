"""Transaction / ReductionRequest / Review / Cancellation モデル。"""

from __future__ import annotations

import uuid
from datetime import datetime
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ColumnElement,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    case,
    func,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.naming import conv

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.bid import Bid
    from app.db.models.case import Case
    from app.db.models.operator import Operator


class Transaction(Base, TimestampMixin):
    """落札後の成約情報。1 案件につき最大 1 レコード。

    ``status`` の遷移:
      pending → visiting → completed
                        └→ cancelled
    """

    __tablename__ = "transactions"
    __table_args__ = (
        # 訪問日超過リマインドの抽出用（alembic 0033）。ReductionRequest の
        # uq_reduction_requests_pending と同じ部分索引パターンで、走査対象を
        # 「未リマインド」の行だけに限定する。
        Index(
            "ix_transactions_overdue_reminder",
            "status",
            "visit_date",
            postgresql_where=text("overdue_reminded_at IS NULL"),
            sqlite_where=text("overdue_reminded_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    bid_id: Mapped[uuid.UUID] = mapped_column(
        # 業者の取引一覧（join Bid → Bid.operator_id 絞込）と FK の RESTRICT 検査が
        # 索引不在で全走査になるため索引を張る（r6-backend M-6 / alembic 0028）。
        Uuid, ForeignKey("bids.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    initial_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)   # 落札額
    final_amount: Mapped[int | None] = mapped_column(BigInteger)              # 減額後確定額
    fee_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # プラットフォーム手数料
    visit_date: Mapped[date | None] = mapped_column(Date)
    visit_time_slot: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    # チャットの既読ポインタ（当事者双方）。相手が送った未読メッセージ数の算出に用いる。
    user_last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 訪問日超過リマインド（services/reminders.py）の送信済みマーカー。NULL = 未送信。
    # 「送ったか」をこの列でしか判定しないことで、定期ループが何度回っても
    # 当事者へ通知が二重に飛ばない（alembic 0033 / r12 決定3）。
    overdue_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # relations
    case: Mapped[Case] = relationship(back_populates="transaction")
    bid: Mapped[Bid] = relationship(back_populates="transaction")
    reduction_requests: Mapped[list[ReductionRequest]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    cancellations: Mapped[list[Cancellation]] = relationship(
        back_populates="transaction",
    )


class ReductionRequest(Base, TimestampMixin):
    """業者による減額申請。

    現地訪問後に実際の荷物量が見積もりと乖離した場合に申請する。
    reason は必須（契約上の根拠として記録する）。

    ``status`` の遷移: pending → approved | rejected
    """

    __tablename__ = "reduction_requests"
    __table_args__ = (
        # 「未回答は取引あたり1件」をDBでも担保する（r6-backend M-4 / alembic 0028）。
        # アプリ層の in-memory 判定だけでは同時2リクエストで pending が2行でき、
        # 以後その判定により業者が恒久的に409で締め出される。
        # PostgreSQL / SQLite いずれも部分一意索引を解し、テストでも同じ制約が効く。
        Index(
            "uq_reduction_requests_pending",
            "transaction_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    original_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    # relations
    transaction: Mapped[Transaction] = relationship(back_populates="reduction_requests")
    operator: Mapped[Operator] = relationship(back_populates="reduction_requests")


# ── 評価（よかった／伸びしろ）と旧形式の★の対応表（唯一の正本） ──
# 2026-09-25 に★1〜5 から「よかった（good）／伸びしろ（improve）」の2択へ移行した
# （alembic 0040・expand 段階）。rating 列は NOT NULL のまま残し、応答から消すのは 0042（contract）。
# ★この値以上を「よかった」とみなす。alembic 0040 の既存行の変換・0041 の補完も同じ閾値
# （マイグレーションは app を import しないため値を複製している）。
LEGACY_GOOD_MIN_RATING = 4
# 新形式（verdict）で投稿された評価に書く互換の★（旧 /review の「5 最高でした」「2 もう少し…」）。
# P2〜P3 の間に残る旧 web の★平均表示と、ロールバック時の旧コードのためだけに使う。
COMPAT_RATING_BY_VERDICT: dict[str, int] = {"good": 5, "improve": 2}


def verdict_from_rating(rating: int) -> str:
    """旧形式の★から評価を導く（★4・5 → "good"／★1〜3 → "improve"）。"""
    return "good" if rating >= LEGACY_GOOD_MIN_RATING else "improve"


class Review(Base, TimestampMixin):
    """成約後の双方向評価。reviewer_type ごとに 1 件のみ（ユニーク制約）。

    評価の正本は ``verdict``（"good"＝よかった／"improve"＝伸びしろ）。列は NULL 可で、
    NULL の行（0040 適用後・新コード切替前に旧コードが書いた行）は rating から導く
    （ハイブリッドプロパティ。Python 側でも SQL 側でも同じ規則）。
    """

    __tablename__ = "reviews"
    __table_args__ = (
        # 本番の制約と同じ名前・条件をモデルにも宣言する（テストの create_all でも効かせ、
        # 二重投稿の IntegrityError → 409 経路を SQLite でも検証できるようにする）。
        # 名前は conv() で確定名として渡す: 命名規約 "ck_%(table_name)s_%(constraint_name)s" は
        # 明示名にも前置される。0004 は create_table に "ck_reviews_rating" を渡したが alembic 経由で
        # 命名規約が掛かり、実名は "ck_reviews_ck_reviews_rating"（0004 のオフライン DDL で確認）。
        # 0040 の CHECK は op.f() で "ck_reviews_verdict" に確定させた。実名との一致は
        # tests/test_review_model_constraints.py で固定している。
        UniqueConstraint(
            "transaction_id", "reviewer_type", name=conv("uq_reviews_transaction_reviewer")
        ),
        CheckConstraint(
            "rating >= 1 AND rating <= 5", name=conv("ck_reviews_ck_reviews_rating")
        ),
        # NULL は通す（expand 期間の旧コードの INSERT 用。NOT NULL 化は 0042）。
        CheckConstraint("verdict IN ('good','improve')", name=conv("ck_reviews_verdict")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'user' | 'operator'
    # 1–5。旧形式の★、または verdict の互換値（COMPAT_RATING_BY_VERDICT）。0042 で撤去予定。
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    # 評価の列そのもの。読み書きは下の verdict ハイブリッド経由で行う（直接参照しない）。
    _verdict: Mapped[str | None] = mapped_column("verdict", String(16), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text)
    # 運営による論理削除（公開・集計から除外。物理削除はせず証跡を残す）。
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # relations
    transaction: Mapped[Transaction] = relationship(back_populates="reviews")

    @hybrid_property
    def verdict(self) -> str:
        """評価（"good" / "improve"）。列が NULL の行は rating から導く。

        ReviewOut / PublicReviewOut は from_attributes でこの値を読む（呼び出し側の変更不要）。
        """
        return self._verdict or verdict_from_rating(self.rating)

    @verdict.inplace.setter
    def _verdict_setter(self, value: str) -> None:
        self._verdict = value

    @verdict.inplace.expression
    @classmethod
    def _verdict_expression(cls) -> ColumnElement[str]:
        # 集計（services/review_stats.py の count FILTER）用。Python 側と同じ規則を SQL で表す。
        return func.coalesce(
            cls._verdict,
            case((cls.rating >= LEGACY_GOOD_MIN_RATING, "good"), else_="improve"),
        )


class Cancellation(Base, TimestampMixin):
    """キャンセル記録。case_id / transaction_id は NULL 許容（削除後の履歴保全）。"""

    __tablename__ = "cancellations"
    __table_args__ = (
        # 二重送信で同一成約のキャンセル記録が2行できると、業者の cancel_count が
        # 実際の2倍になり無実の業者に停止判断のペナルティが積み上がる（r6-backend M-2）。
        # transaction_id は NULL 許容（案件単位の取り下げ）だが、PostgreSQL/SQLite とも
        # NULL 同士は重複扱いしないため案件取り下げの記録は従来どおり複数行入る。
        # 制約: 将来「運営による代理キャンセル」で同一成約に2行目を積む運用が要る場合、
        # cancelled_by を含む複合一意へ緩める必要がある（現仕様では発生しない）。
        UniqueConstraint("transaction_id", name="uq_cancellations_transaction_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cancelled_by: Mapped[str] = mapped_column(String(32), nullable=False)  # 'user'|'operator'|'admin'
    # 強制終了を実行した運営アカウント（cancelled_by='admin' のときのみ非NULL）。
    # 不可逆かつ当事者双方へ通知が飛ぶ操作の実行者がアプリログのローテーションで
    # 消えると、運営が複数人になった時点で追跡不能になる（r8-review M-1）。
    # API 応答には含めない（当事者に運営個人を開示しない）。運営アカウント自体が
    # 削除された場合は SET NULL で行を残す（既存の case_id/transaction_id と同方針）。
    cancelled_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)

    # relations
    case: Mapped[Case | None] = relationship(back_populates="cancellations")
    transaction: Mapped[Transaction | None] = relationship(back_populates="cancellations")
