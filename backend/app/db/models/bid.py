"""Bid モデル — 業者による入札。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.case import Case
    from app.db.models.operator import Operator
    from app.db.models.transaction import Transaction


# bids.status の許容値（alembic 0004 / 0018 のCHECK制約と一致させる）。
# 新規に書くコードは文字列リテラルではなくこれらの定数を使うこと。
BID_STATUS_PENDING = "pending"
BID_STATUS_SELECTED = "selected"
BID_STATUS_REJECTED = "rejected"
BID_STATUS_WITHDRAWN = "withdrawn"


class Bid(Base, TimestampMixin):
    """業者が案件に対して行う入札。

    ``status`` の遷移:
      pending → selected（ユーザーが選択）
             → rejected（他社が選択または案件クローズ）
             → withdrawn（業者本人が取り下げ）

    selected / rejected / withdrawn はいずれも終端状態（以降の遷移は無い）。

    1 案件につき 1 業者 1 入札のみ（uq_bids_case_operator 制約）。取り下げ
    （withdrawn）後の再入札も同じ理由で拒否される（意図的な仕様。設計確定済み）。
    """

    __tablename__ = "bids"
    __table_args__ = (
        # DB側（alembic 0004）に既に存在する制約をORMメタデータ側にも反映する。
        # これが無いと Base.metadata.create_all（テスト環境のスキーマ生成）では
        # この制約が作られず、本番（alembic経由）とテスト環境でスキーマが乖離し、
        # 重複入札のDB制約違反（IntegrityError）経路がテストで検証不能になる
        # （security review 指摘対応。真の重複入札防止保証はこの制約）。
        UniqueConstraint("case_id", "operator_id", name="uq_bids_case_operator"),
        # DB側（alembic 0018）に既に存在するCHECK制約をORMメタデータ側にも反映する。
        # これが無いと本番DBのCHECK制約とORMのメタデータが乖離し、
        # Base.metadata.create_all（テスト環境）ではこの制約が作られず、
        # 不正な status 値（例: "bogus"）のINSERTがテストで検知できなくなる。
        CheckConstraint(
            "status IN ('pending','selected','rejected','withdrawn')",
            name="ck_bids_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 円
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=BID_STATUS_PENDING, index=True
    )

    # relations
    case: Mapped[Case] = relationship(back_populates="bids")
    operator: Mapped[Operator] = relationship(back_populates="bids")
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="bid",
        uselist=False,
    )


class BidWithdrawal(Base, TimestampMixin):
    """入札取り下げの監査証跡（1回の取り下げ操作につき1レコード。追記専用）。

    bids.status を 'withdrawn' に更新するだけでは「いつ・誰が取り下げたか」の
    記録が bids 行自体の updated_at 以外に残らないため、将来の不正調査・
    カスタマーサポート対応のために新設する（security review 指摘対応）。
    回数制限や閾値アラート等の業務ロジックはこのテーブルの追加スコープに
    含めない（数値基準を推測で決めることになるため。設計指示に基づく。
    永続化のみを行う）。
    """

    __tablename__ = "bid_withdrawals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # bid_id/case_id/operator_id はいずれも ON DELETE RESTRICT（CASCADEではない）。
    # 監査証跡は不正調査・カスタマーサポート対応の唯一の記録であり、親行
    # （bids/cases/operators）が削除されても証跡だけは残す必要があるため、
    # CASCADEで一緒に消えてしまう構成は誤りだった（security review 2周目
    # Medium指摘対応）。
    # withdrawn は終端状態のため「1入札につき取り下げは1回」。アプリ層の条件付き
    # UPDATE に加え、DB側でも一意制約で多重挿入を拒否する（QA review 指摘対応・
    # 多層防御。alembic 0020 の uq_bid_withdrawals_bid_id と一致させる）。
    bid_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bids.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # 上記のRESTRICT化に加え、万一将来親行の削除が許容される運用に変わった
    # 場合でも取り下げの事実関係を再構成できるよう、取り下げ時点の値を
    # 非正規化スナップショットとして保持する（security review 2周目 Medium
    # 指摘対応。多層防御）。
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 円（取り下げ時点の入札額）
