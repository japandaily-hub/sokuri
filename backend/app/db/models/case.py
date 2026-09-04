"""Case / CaseItem / CasePhoto モデル — カタヅケ案件とその商品・写真。

案件写真の商品ごとのアルバム化（撮影・AI解析・表示の整理）:
- 入札・成約（Bid/Transaction）の単位は引き続き「1案件」。CaseItem は表示・AI解析上の
  グルーピング単位であり、取引の単位ではない。
- CasePhoto.case_item_id は NULL 許容（未分類写真として case 直下に残せる）。
  レガシー案件（本機能導入前に作成された案件）は case_item_id=NULL のまま残り、
  items=[] として扱われる（backfill しない）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum
from app.db.models.enums import ItemCondition

if TYPE_CHECKING:
    from app.db.models.bid import Bid
    from app.db.models.transaction import Cancellation, Transaction


# Case.ai_status の許容値（bid.py の BID_STATUS_* と同じ命名規約）。
#: 解析待ち（案件作成直後。BackgroundTasks が解析を開始する前）
CASE_AI_STATUS_PENDING = "pending"
#: 解析完了（ai_summary / CaseItem.ai_* に結果が入っている）
CASE_AI_STATUS_DONE = "done"
#: 解析失敗（例外・デッドライン超過。ai_summary はフォールバック文のまま）
CASE_AI_STATUS_FAILED = "failed"


class Case(Base, TimestampMixin):
    """ユーザーが作成した片付け案件。

    ``status`` の遷移:
      draft → open → bidding → closed
                    └→ cancelled（open/bidding からユーザーが出品取り下げ。
                                  cases.py の cancel_case 参照）
    """

    __tablename__ = "cases"
    __table_args__ = (
        # 同一ユーザー内で idempotency_key の重複作成を DB 制約で阻止する
        # （r6-verify-fix M2）。in-memory の事前チェック(_find_idempotent_case_id)
        # だけでは同時2リクエスト（二度押し・リトライ）を防げず、案件が2件
        # 作られうる。NULL は標準SQLの一意制約セマンティクスにより対象外
        # （idempotency_key 未指定の通常作成は何件でも共存できる）。
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_cases_user_id_idempotency_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # WEEK 2 で認証追加後に nullable=False + ForeignKey に変更する
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)

    # 利用目的 ("片付け整理" / "遺品整理" / "引っ越し" / "その他")
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)

    # 住所情報
    prefecture: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    address_detail: Mapped[str | None] = mapped_column(Text)

    # 住居情報
    housing_type: Mapped[str | None] = mapped_column(String(32))   # "一戸建て" / "マンション"
    floor_plan: Mapped[str | None] = mapped_column(String(32))     # "1K" / "3LDK" etc
    floor_number: Mapped[int | None] = mapped_column(Integer)
    has_elevator: Mapped[bool | None] = mapped_column(Boolean)

    # Gemini Vision が生成した案件サマリー
    ai_summary: Mapped[str | None] = mapped_column(Text)

    # AI 解析の進捗（"pending" → "done" / "failed"）。案件作成は解析を待たずに
    # commit して即応答し、解析は BackgroundTasks 内の別セッションで行うため、
    # 依頼者・フロントが「まだ解析中」を判別できる状態列が必要になる（r6 H-1/ADD-1）。
    # "failed" でも案件自体は有効（ai_summary には作成時のフォールバック文が入る）。
    ai_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True
    )
    # 失敗理由（運営の切り分け用。例外の型名+要約のみを保持し、写真やAPIキーは載せない）
    ai_failed_reason: Mapped[str | None] = mapped_column(String(255))

    # 冪等キー（クライアント発行 UUID）。プロキシタイムアウト由来の再送信で同一内容の
    # 案件が二重作成されるのを防ぐ（r6 H-1）。直近 10 分・同一ユーザー内での照合は
    # アプリ層（_find_idempotent_case_id）が担うが、真の一意性（同時2リクエストの
    # 競合防止）は __table_args__ の uq_cases_user_id_idempotency_key が担保する
    # （r6-verify-fix M2）。同一キーの恒久的な再利用拒否ではなく「同一ユーザーで
    # 同じキーの行は高々1件」という不変条件であり、10分窓での既存案件返却
    # （cases.py の create_case）と両立する。
    idempotency_key: Mapped[str | None] = mapped_column(String(64), index=True)

    # relations
    photos: Mapped[list[CasePhoto]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CasePhoto.sort_order",
    )
    items: Mapped[list["CaseItem"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseItem.sort_order",
    )
    bids: Mapped[list[Bid]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="case",
        uselist=False,
    )
    cancellations: Mapped[list[Cancellation]] = relationship(
        back_populates="case",
    )


class CaseItem(Base, TimestampMixin):
    """案件配下の商品（アルバム単位）。撮影・AI解析・表示をこの単位で整理する。

    入札・成約の単位ではない（あくまで Case に対する表示・解析のグルーピング）。
    """

    __tablename__ = "case_items"
    __table_args__ = (
        Index("ix_case_items_case_id_sort_order", "case_id", "sort_order"),
        # 複合FK (case_photos.case_item_id, case_photos.case_id) の参照先として
        # (id, case_id) の複合ユニーク制約が必要（他案件の item_id を指す写真を
        # DB制約レベルで拒否するため）。
        UniqueConstraint("id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_detected_name: Mapped[str | None] = mapped_column(String(64))
    # ItemCondition を ORM 型として再利用するが、DDL は native_enum=False
    # （pg_enum が生成する VARCHAR(32)）に固定する。Album 系の pg_enum で
    # Railway デプロイ障害が起きた記録があるため、ネイティブ ENUM 型は作らない。
    ai_condition: Mapped[ItemCondition | None] = mapped_column(pg_enum(ItemCondition))
    ai_summary: Mapped[str | None] = mapped_column(Text)
    # ユーザーが自ら編集したコンディション/説明。ai_condition/ai_summary（AI推定値）
    # とは別カラムで持ち、AI推定を上書き消去しない（ユーザー編集後もAI推定結果を
    # 保持し続けるための分離。同じ pg_enum(native_enum=False) を踏襲する）。
    user_condition: Mapped[ItemCondition | None] = mapped_column(pg_enum(ItemCondition))
    user_description: Mapped[str | None] = mapped_column(Text)

    case: Mapped[Case] = relationship(back_populates="items")
    # foreign_keys を case_item_id のみに限定する: case_photos.case_id は
    # 既存の Case.photos / CasePhoto.case 関係が単独FK(case_id→cases.id)で
    # 既に管理している列であり、同じ列を本関係（複合FK経由）でも同期対象に
    # すると SQLAlchemy が "conflicting relationship" 警告/不整合を起こす。
    # DB制約（複合FK）自体は case_photos.__table_args__ 側でそのまま有効。
    photos: Mapped[list["CasePhoto"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CasePhoto.sort_order",
        foreign_keys="CasePhoto.case_item_id",
    )


class CasePhoto(Base, TimestampMixin):
    """案件に紐づく写真。sort_order の昇順で表示する。

    ``case_item_id`` は商品グループへの任意の紐づけ（NULL = 未分類写真）。
    複合FK (case_item_id, case_id) → case_items(id, case_id) により、
    他案件の CaseItem を指すことは DB 制約レベルで拒否される。
    """

    __tablename__ = "case_photos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_item_id", "case_id"],
            ["case_items.id", "case_items.case_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_case_photos_case_item_id",
            "case_item_id",
            postgresql_where=text("case_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # UNIQUE制約（security review 指摘対応・H-1）: storage_key は「実ファイルが
    # 存在する」ことの検証にのみ使われ、所有者チェックを一切伴わない
    # （presign は認証済みユーザーなら誰でも新規キーを発行できる設計）。
    # UNIQUE制約が無いと、他人の案件の storage_key（案件一覧等から収集可能）を
    # 自分の商品に「追加」でき、その後自分の案件からその写真を「削除」すると
    # 他人の実ファイルが物理削除されてしまう（クロステナントでの写真破壊）。
    # 1つの実ファイルは常に高々1つの CasePhoto 行にのみ紐づく不変条件をDB制約で強制する。
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    url: Mapped[str | None] = mapped_column(String(2048))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    case: Mapped[Case] = relationship(back_populates="photos")
    item: Mapped["CaseItem | None"] = relationship(
        back_populates="photos", foreign_keys=[case_item_id]
    )
