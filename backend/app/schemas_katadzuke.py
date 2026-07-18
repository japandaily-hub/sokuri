"""カタヅケ API の Pydantic スキーマ（既存 schemas.py には手を入れず分離）。"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

# ──────────────────────────── 認証 ────────────────────────────


class UserSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=128)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


# 業者向け利用規約・プライバシーポリシーの現行バージョン。
# クライアントからは受け取らず、同意時点でサーバーがこの値を確定させて記録する
# （クライアント入力のバージョン文字列は改ざん・偽装され得るため信用しない）。
CURRENT_OPERATOR_TERMS_VERSION = "2026-07-02"


class OperatorSignupRequest(BaseModel):
    invite_code: str | None = Field(default=None, max_length=64, description="招待コード（任意。あればactive、なければpending登録＝要admin承認）")
    company_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # 古物商許可番号は個人・法人問わず必須（カタヅケ自体は許可を取得しない）。
    # フォーマットの厳格な正規表現検証は行わない（表記ゆれが大きく誤弾きリスクの方が実利より大きいため）。
    license_number: str = Field(min_length=5, max_length=128)
    agreed: bool = Field(description="利用規約・プライバシーポリシーへの同意")


class OperatorLoginRequest(BaseModel):
    email: EmailStr
    password: str


class LineExchangeRequest(BaseModel):
    """LINEログイン統合 — フロントから受け取った LINE アクセストークンをバックエンドで検証する。

    id_token/JWKS 検証は行わず、このトークンを使ってバックエンド自身が
    LINE Profile API を叩いて userId を取得する MVP 方式（将来強化: OIDC id_token 検証）。
    """

    line_access_token: str = Field(min_length=1, max_length=4096)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    role: str


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    contact_email: str
    license_number: str | None
    verified_at: datetime | None
    vendor_status: str
    rating: float | None
    is_suspended: bool
    created_at: datetime
    agreed_terms_version: str | None = None
    agreed_at: datetime | None = None


class OperatorPublicOut(BaseModel):
    """ユーザーに見せる業者公開情報。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    rating: float | None
    verified_at: datetime | None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    account_type: Literal["user", "operator"]
    user: UserOut | None = None
    operator: OperatorOut | None = None


# ──────────────────────────── アカウント（マイページ） ────────────────────────────

# カナ（全角カタカナ・長音符・半角/全角スペース）のみを許容する。
# 半角カナ・ひらがな混入に加え、\s だとタブ・改行等の制御空白まで通るため
# スペース2種を明示列挙する（QAレビュー指摘対応）。
_KANA_RE = r"^[ァ-ヶー 　]*$"
# 電話番号（数字・+・-・()・半角スペースのみ）。国内表記ゆれを広く許容する。
_PHONE_RE = r"^[0-9+\-() ]*$"

ResidenceArea = Literal[
    "tokyo", "kanagawa", "saitama", "chiba", "osaka", "aichi", "fukuoka", "other"
]


class UserProfileOut(BaseModel):
    email: str
    family_name: str | None
    given_name: str | None
    family_name_kana: str | None
    given_name_kana: str | None
    phone: str | None
    residence_area: str | None
    has_password: bool
    line_linked: bool


class UserProfileUpdateRequest(BaseModel):
    # str_strip_whitespace: 空白のみの姓名（" " / "　"）を strip→min_length で弾く
    # （フロントは trim 済みだが API 直叩き対策。QAレビュー指摘対応）。
    model_config = ConfigDict(str_strip_whitespace=True)

    family_name: str = Field(min_length=1, max_length=64)
    given_name: str = Field(min_length=1, max_length=64)
    family_name_kana: str | None = Field(default=None, max_length=64)
    given_name_kana: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    residence_area: ResidenceArea | None = None

    @field_validator("family_name_kana", "given_name_kana")
    @classmethod
    def _validate_kana(cls, v: str | None) -> str | None:
        if v is not None and not re.match(_KANA_RE, v):
            raise ValueError("カナは全角カタカナで入力してください。")
        return v

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str | None) -> str | None:
        if v is not None and not re.match(_PHONE_RE, v):
            raise ValueError("電話番号の形式が正しくありません。")
        return v


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class PasswordChangeResponse(BaseModel):
    detail: str
    access_token: str


class AccountDeleteRequest(BaseModel):
    password: str | None = None
    confirm: bool


class AccountDeleteResponse(BaseModel):
    detail: str


# ──────────────────────────── 写真アップロード ────────────────────────────


class PresignRequest(BaseModel):
    filename: str = Field(max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class PresignResponse(BaseModel):
    storage_key: str
    upload_url: str
    public_url: str


# ──────────────────────────── 案件 ────────────────────────────


class CasePhotoIn(BaseModel):
    storage_key: str = Field(max_length=512)
    sort_order: int = 0


class CasePhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str | None
    sort_order: int


class CaseCreateRequest(BaseModel):
    purpose: str = Field(max_length=64)
    prefecture: str = Field(min_length=1, max_length=32)
    city: str = Field(min_length=1, max_length=64)
    address_detail: str | None = None
    housing_type: str | None = Field(default=None, max_length=32)
    floor_plan: str | None = Field(default=None, max_length=32)
    floor_number: int | None = Field(default=None, ge=0, le=100)
    has_elevator: bool | None = None
    photos: list[CasePhotoIn] = Field(default_factory=list, max_length=20)


class CaseOut(BaseModel):
    """案件（所有ユーザー向け・住所詳細を含む）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    purpose: str
    prefecture: str
    city: str
    address_detail: str | None
    housing_type: str | None
    floor_plan: str | None
    floor_number: int | None
    has_elevator: bool | None
    ai_summary: str | None
    created_at: datetime
    photos: list[CasePhotoOut] = []
    bid_count: int = 0


class CaseMaskedOut(BaseModel):
    """案件（業者向け・住所詳細はマスク。落札後は /transactions で開示）。"""

    id: uuid.UUID
    status: str
    purpose: str
    prefecture: str
    city: str
    housing_type: str | None
    floor_plan: str | None
    floor_number: int | None
    has_elevator: bool | None
    ai_summary: str | None
    created_at: datetime
    photos: list[CasePhotoOut] = []
    bid_count: int = 0
    my_bid: BidOut | None = None
    top_bid_amount: int | None = None


# ──────────────────────────── 入札 ────────────────────────────


class BidCreateRequest(BaseModel):
    amount: int = Field(gt=0, le=100_000_000)
    message: str | None = Field(default=None, max_length=2000)


class BidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    amount: int
    message: str | None
    status: str
    created_at: datetime
    operator: OperatorPublicOut | None = None
    transaction_id: uuid.UUID | None = None


# ──────────────────────────── 成約 ────────────────────────────


class TransactionAddressOut(BaseModel):
    """落札業者にのみ開示する住所詳細。"""

    prefecture: str
    city: str
    address_detail: str | None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    bid_id: uuid.UUID
    initial_amount: int
    final_amount: int | None
    fee_amount: int
    visit_date: date | None
    visit_time_slot: str | None = None
    status: str
    created_at: datetime


class TransactionDetailOut(TransactionOut):
    """当事者向け詳細。address は落札業者・所有ユーザーにのみ含める。"""

    case: CaseMaskedOut | None = None
    operator: OperatorPublicOut | None = None
    address: TransactionAddressOut | None = None
    contact_email: str | None = None
    awaiting_approval: bool = False
    reduction_requests: list[ReductionOut] = []
    reviews: list[ReviewOut] = []
    unread_count: int = 0


class TransactionCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class TransactionListItem(BaseModel):
    """成約一覧（当事者向け・住所詳細なし）。"""

    id: uuid.UUID
    case_id: uuid.UUID
    status: str
    initial_amount: int
    final_amount: int | None
    visit_date: date | None
    created_at: datetime
    purpose: str
    prefecture: str
    city: str
    company_name: str | None = None
    has_pending_reduction: bool = False
    # ユーザー側レビュー（reviewer_type=='user'）が既に投稿済みかどうか（通知の恒久残存防止用）。
    # 業者側レビューの有無は含めない（意味は固定契約: フロントは !has_review で評価待ち通知を判定）。
    has_review: bool = False


# ──────────────────────────── 減額申請 ────────────────────────────


class ReductionCreateRequest(BaseModel):
    requested_amount: int = Field(gt=0)
    reason: str = Field(min_length=10, max_length=2000)


class ReductionDecisionRequest(BaseModel):
    action: Literal["approve", "reject"]


class ReductionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    original_amount: int
    requested_amount: int
    reason: str
    status: str
    created_at: datetime


# ──────────────────────────── レビュー ────────────────────────────


class ReviewCreateRequest(BaseModel):
    transaction_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    reviewer_type: str
    rating: int
    comment: str | None
    created_at: datetime


class PublicReviewOut(BaseModel):
    """無認証の公開プロフィール用レビュー。内部識別子（transaction_id）や
    reviewer_type を含めない最小フィールドのみ公開する。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rating: int
    comment: str | None
    created_at: datetime


# ──────────────────────────── 管理 ────────────────────────────


class InviteCreateRequest(BaseModel):
    email: EmailStr | None = None


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    email: str | None
    used_at: datetime | None
    operator_id: uuid.UUID | None
    lot_name: str | None
    created_at: datetime


class InviteBulkCreateRequest(BaseModel):
    count: int = Field(ge=1, le=500, description="発行件数")
    lot_name: str | None = Field(default=None, max_length=128, description="ロット名（管理用）")


class InviteBulkCreateResponse(BaseModel):
    codes: list[str]
    lot_name: str | None
    count: int


class OperatorVerifyRequest(BaseModel):
    verified: bool = True


# ──────────────────────────── 業者事前申込（/business） ────────────────────────────


class BankAccountIn(BaseModel):
    """振込先口座情報。DB保存直前に暗号化する（平文はDB・ログに残さない）。"""

    bank_name: str = Field(max_length=100)
    branch_name: str = Field(max_length=100)
    account_type: Literal["ordinary", "checking"]
    account_number: str = Field(max_length=20)
    account_holder: str = Field(max_length=100)


class OperatorApplicationCreateRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    representative_name: str = Field(min_length=1, max_length=255)
    registered_address: str = Field(min_length=1, max_length=512)
    contact_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=32)
    business_type: Literal["corp", "sole"]
    service_area: str = Field(max_length=32)
    categories: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=2000)
    license_number: str = Field(min_length=5, max_length=128)
    invoice_number: str | None = Field(default=None, max_length=20)
    bank_account: BankAccountIn
    agreed: bool = Field(description="利用規約・プライバシーポリシーへの同意")


class OperatorApplicationCreateResponse(BaseModel):
    application_id: uuid.UUID
    status: str


class BankAccountMaskedOut(BaseModel):
    """admin一覧・詳細用。口座番号は下4桁マスクのみ含める。"""

    bank_name: str
    branch_name: str
    account_type: str
    account_number_masked: str
    account_holder: str


class OperatorApplicationOut(BaseModel):
    """admin一覧・詳細用。口座情報は下4桁マスクのみ含める。"""

    id: uuid.UUID
    status: str
    company_name: str
    representative_name: str
    registered_address: str
    contact_name: str
    contact_email: str
    contact_phone: str
    license_number: str
    business_type: str | None
    service_area: str | None
    categories: str | None
    message: str | None
    invoice_number: str | None
    bank_account: BankAccountMaskedOut | None
    agreed_terms_version: str | None
    agreed_at: datetime | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    reject_reason: str | None
    operator_id: uuid.UUID | None
    created_at: datetime


class OperatorApplicationBankAccountRevealOut(BaseModel):
    """admin向け: 口座情報の全桁復号結果。アクセスは呼び出し元でログに記録すること。"""

    bank_name: str
    branch_name: str
    account_type: str
    account_number: str
    account_holder: str


class OperatorApplicationRejectRequest(BaseModel):
    reject_reason: str = Field(min_length=1, max_length=500)


class OperatorApplicationApproveResponse(BaseModel):
    application: OperatorApplicationOut
    invite_code: str


# ──────────────────────────── チャット ────────────────────────────


class MessageCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender_type: str
    body: str
    kind: str
    meta: dict | None
    created_at: datetime
    mine: bool = False


# ──────────────────────────── 日程調整 ────────────────────────────


class ScheduleProposeRequest(BaseModel):
    slots: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        min_length=1, max_length=10
    )


class ScheduleConfirmRequest(BaseModel):
    visit_date: date
    visit_time_slot: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("visit_date")
    @classmethod
    def _validate_visit_date(cls, v: date) -> date:
        today = date.today()
        if v < today:
            raise ValueError("訪問日は本日以降を指定してください。")
        if v > today + timedelta(days=365):
            raise ValueError("訪問日が遠すぎます。")
        return v


# ──────────────────────────── 業者プロフィール ────────────────────────────


class OperatorProfileOut(BaseModel):
    """自社プロフィール取得（審査確定項目 + 編集可能項目の統合）。"""

    operator_id: uuid.UUID
    company_name: str
    license_number: str | None
    verified_at: datetime | None
    vendor_status: str
    rating: float | None
    areas: list[str] = []
    categories: list[str] = []
    strong_categories: list[str] = []
    staff_count: int | None = None
    business_hours: str | None = None
    intro_message: str | None = None
    is_public: bool = True
    show_stats: bool = True
    show_reviews: bool = True
    show_message: bool = True
    accept_unsellable: bool = False


class OperatorProfileUpdateRequest(BaseModel):
    """編集可能項目のみ受け付ける。審査確定項目（会社名・許可番号等）は含めない。"""

    areas: list[str] = Field(default_factory=list, max_length=50)
    categories: list[str] = Field(default_factory=list, max_length=50)
    strong_categories: list[str] = Field(default_factory=list, max_length=50)
    staff_count: int | None = Field(default=None, ge=0, le=100_000)
    business_hours: str | None = Field(default=None, max_length=255)
    intro_message: str | None = Field(default=None, max_length=500)
    is_public: bool = True
    show_stats: bool = True
    show_reviews: bool = True
    show_message: bool = True
    accept_unsellable: bool = False


class OperatorPublicProfileOut(BaseModel):
    """公開プロフィール（/vendors/{operator_id}）。show_* フラグに応じて項目を省く。"""

    operator_id: uuid.UUID
    company_name: str
    verified_at: datetime | None
    areas: list[str] = []
    categories: list[str] = []
    strong_categories: list[str] = []
    staff_count: int | None = None
    business_hours: str | None = None
    intro_message: str | None = None
    accept_unsellable: bool = False
    rating: float | None = None
    reviews: list[PublicReviewOut] | None = None


# 前方参照の解決
CaseMaskedOut.model_rebuild()
TransactionDetailOut.model_rebuild()
