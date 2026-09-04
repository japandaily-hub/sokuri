"""カタヅケ API の Pydantic スキーマ（既存 schemas.py には手を入れず分離）。"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.limits import MAX_ITEMS_PER_CASE, MAX_PHOTOS_PER_CASE, MAX_PHOTOS_PER_ITEM
from app.db.models.enums import ItemCondition
from app.services.message_guard import contains_contact_info
from app.services.text_sanitize import normalize_and_strip_control_chars

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

    ``reauth_token`` は、パスワード設定済みユーザーが LINE 連携を新規に「付与」する際
    （Bearer付き経路・初回連携時のみ）に必須となる短命トークン
    （``POST /users/me/reauth-token`` で発行。purpose="line_link"）。
    LINE専用アカウント（password_hash が None）・未連携でない再送（冪等）・
    Bearerなし経路では不要。
    """

    line_access_token: str = Field(min_length=1, max_length=4096)
    reauth_token: str | None = Field(default=None, max_length=4096)


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
    # BLOB本体（license_image_data）は含めない。導出フラグのみ（Operatorモデルの
    # has_license_image プロパティから from_attributes 経由で取得する）。
    has_license_image: bool = False


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
    birth_date: date | None = None
    occupation: str | None = None
    identity_status: str = "unverified"
    has_bank_account: bool = False


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
    # 既存フィールドと同じ「フルリプレース」方式（未送信=None は既存値のクリアを意味する）。
    # phone / residence_area 等と挙動を揃える（QAレビュー指摘: 部分更新セマンティクスの混在防止）。
    birth_date: date | None = None
    occupation: str | None = Field(default=None, max_length=64)

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


class ReauthTokenRequest(BaseModel):
    current_password: str


class ReauthTokenResponse(BaseModel):
    reauth_token: str
    expires_in: int = 300


class LineLinkUnlinkRequest(BaseModel):
    current_password: str


class AccountDeleteRequest(BaseModel):
    password: str | None = None
    confirm: bool


class AccountDeleteResponse(BaseModel):
    detail: str


# ──────────────────────────── マイページ: 住所 ────────────────────────────

# 47都道府県（表記ゆれ防止のため固定リストで検証する）。
PREFECTURES: tuple[str, ...] = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)  # fmt: skip
_PREFECTURE_SET = frozenset(PREFECTURES)
# 都道府県 → residence_area の自動同期マップ（既存 ResidenceArea 定数と一致させる）。
_PREFECTURE_TO_RESIDENCE_AREA: dict[str, str] = {
    "東京都": "tokyo",
    "神奈川県": "kanagawa",
    "埼玉県": "saitama",
    "千葉県": "chiba",
    "大阪府": "osaka",
    "愛知県": "aichi",
    "福岡県": "fukuoka",
}


def prefecture_to_residence_area(prefecture: str) -> str:
    """都道府県名から居住エリア（ResidenceArea）を導出する。該当なしは "other"。"""
    return _PREFECTURE_TO_RESIDENCE_AREA.get(prefecture, "other")


_POSTAL_CODE_DIGITS_RE = r"^\d{7}$"


class UserAddressOut(BaseModel):
    postal_code: str | None
    prefecture: str | None
    city: str | None
    address_line1: str | None
    address_line2: str | None
    residence_area: str | None


class UserAddressUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    postal_code: str = Field(min_length=1, max_length=16)
    prefecture: str
    city: str = Field(min_length=1, max_length=64)
    address_line1: str = Field(min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)

    @field_validator("postal_code")
    @classmethod
    def _normalize_postal_code(cls, v: str) -> str:
        digits = v.replace("-", "").replace("ー", "").strip()
        if not re.match(_POSTAL_CODE_DIGITS_RE, digits):
            raise ValueError("郵便番号は数字7桁で入力してください。")
        return digits

    @field_validator("prefecture")
    @classmethod
    def _validate_prefecture(cls, v: str) -> str:
        if v not in _PREFECTURE_SET:
            raise ValueError("都道府県の指定が正しくありません。")
        return v


# ──────────────────────────── マイページ: 振込先口座 ────────────────────────────


class UserBankAccountMaskedOut(BaseModel):
    has_bank_account: bool
    bank_name: str | None = None
    branch_name: str | None = None
    account_type: str | None = None
    account_number_masked: str | None = None
    account_holder_kana: str | None = None
    updated_at: datetime | None = None


class UserBankAccountUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    bank_name: str = Field(min_length=1, max_length=64)
    branch_name: str = Field(min_length=1, max_length=64)
    account_type: Literal["普通", "当座"]
    account_number: str
    account_holder_kana: str = Field(min_length=1, max_length=64)

    @field_validator("account_number")
    @classmethod
    def _validate_account_number(cls, v: str) -> str:
        if not re.match(r"^\d{7}$", v):
            raise ValueError("口座番号は数字7桁で入力してください。")
        return v

    @field_validator("account_holder_kana")
    @classmethod
    def _validate_account_holder_kana(cls, v: str) -> str:
        if not re.match(_KANA_RE, v) or v.strip() == "":
            raise ValueError("口座名義（カナ）は全角カタカナで入力してください。")
        return v


# ──────────────────────────── マイページ: 本人確認 ────────────────────────────

IdentityDocType = Literal[
    "drivers_license", "my_number_card", "passport", "residence_card", "health_insurance_card"
]


class UserIdentityStatusOut(BaseModel):
    status: str
    document_id: uuid.UUID | None = None
    doc_type: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    reject_reason: str | None = None
    has_back: bool = False


class UserIdentityDocumentAdminOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    user_name: str | None
    doc_type: str
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None
    reject_reason: str | None
    has_back: bool


class IdentityDocumentRejectRequest(BaseModel):
    reject_reason: str = Field(min_length=1, max_length=500)


# ──────────────────────────── 写真アップロード ────────────────────────────


class PresignRequest(BaseModel):
    filename: str = Field(max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class PresignResponse(BaseModel):
    storage_key: str
    upload_url: str
    public_url: str


class OperatorLicenseImageUploadResponse(BaseModel):
    uploaded_at: datetime


# ──────────────────────────── 案件 ────────────────────────────


class CasePhotoIn(BaseModel):
    storage_key: str = Field(max_length=512)
    # 上限1000は運用上ありえない極端な値（DoS/DB肥大化目的の乱数投入等）を
    # 弾くための緩い上限（security review 指摘対応）。表示順の実用範囲は
    # 高々 MAX_PHOTOS_PER_ITEM/MAX_PHOTOS_PER_CASE 程度のため十分な余裕がある。
    sort_order: int = Field(default=0, ge=0, le=1000)


class CasePhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str | None
    sort_order: int


def _sanitize_free_text(
    value: str | None, *, max_length: int, field_label: str
) -> str | None:
    """自由入力テキスト（ユーザー入力）をサーバ側で無害化する（DRY共通関数）。

    CaseItemIn.name / CaseItemUpdateRequest.name・user_description で共通して
    使う無害化ロジック（既存の CaseItemIn._sanitize_name のロジックをここへ
    集約し、他フィールドからも再利用できるようにする）。

    - Unicode NFKC正規化 + 制御文字・双方向制御文字の除去
      （summary.py の _safe_attr と同じロジックを text_sanitize.py に
      共通化して再利用する）。
    - プラットフォーム外への直接連絡を誘導する電話番号・メールアドレス・
      URL の埋め込みは bids.py の入札メッセージと同様に拒否する
      （既存の contains_contact_info() を適用）。
    """
    if value is None:
        return None
    text = normalize_and_strip_control_chars(value)
    if not text:
        return None
    # Field(max_length=...) はNFKC正規化"前"の文字列に対して検証されるため、
    # 正規化によって文字数が増える文字(例: "㍿"→"株式会社"で4倍)が含まれると
    # 正規化後に上限を超えたままDBへ保存され、切り詰めエラーになりうる
    # (CaseItemIn.name の最終レビューで発見)。正規化後に再度上限を適用する。
    if len(text) > max_length:
        text = text[:max_length]
    if contains_contact_info(text):
        raise ValueError(
            f"{field_label}に電話番号・メールアドレス・URLは記載できません。"
        )
    return text


class CaseItemIn(BaseModel):
    """案件作成時に指定する商品（アルバム）1件分の入力。"""

    name: str | None = Field(default=None, max_length=64)
    sort_order: int = 0
    # 0枚（写真の紐づいていない商品アルバム）は成立しないユースケースのため
    # min_length=1 を必須にする（security review 指摘対応）。
    # 注意: Pydantic v2 はデフォルト値を検証しない(validate_default=False既定)ため、
    # default_factory=list を残したままでは photos キー自体を省略した場合に
    # min_length チェックをすり抜けて空リストが採用されてしまう(実装バグとして
    # 最終レビューで発見)。デフォルトを設けず必須フィールドにすることで、
    # 省略時も明示的な422(missing)にする。
    photos: list[CasePhotoIn] = Field(min_length=1, max_length=MAX_PHOTOS_PER_ITEM)

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v: str | None) -> str | None:
        return _sanitize_free_text(v, max_length=64, field_label="商品名")


class CaseItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    sort_order: int
    ai_detected_name: str | None
    ai_condition: ItemCondition | None
    ai_summary: str | None
    # ユーザーが自ら編集したコンディション/説明（AI推定値の ai_condition/ai_summary
    # とは別カラム。case.py の CaseItem 参照）。
    user_condition: ItemCondition | None = None
    user_description: str | None = None
    photos: list[CasePhotoOut] = []


class CaseItemUpdateRequest(BaseModel):
    """商品(CaseItem)情報のユーザー編集。単純なPUT方式（exclude_unsetは使わず、
    送られたフィールドをそのまま代入する。null を明示送信すればクリアされる）。"""

    # extra="forbid"（security review 指摘対応・L-3）: 将来 CaseItem にフィールドを
    # 追加した際、本スキーマの更新を忘れても未知フィールドが黙って無視される
    # （＝更新されるべきなのに更新されない静かな退行）ことを防ぐ。未知フィールドは
    # 422 で明示的に拒否し、スキーマの更新漏れに気づけるようにする。
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=64)
    user_condition: ItemCondition | None = None
    user_description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v: str | None) -> str | None:
        return _sanitize_free_text(v, max_length=64, field_label="商品名")

    @field_validator("user_description")
    @classmethod
    def _sanitize_user_description(cls, v: str | None) -> str | None:
        return _sanitize_free_text(v, max_length=500, field_label="商品の説明")

    @field_validator("user_condition", mode="before")
    @classmethod
    def _validate_user_condition(cls, v: object) -> object:
        """不正な値の場合、Pydantic既定の英語メッセージではなく日本語メッセージ
        に変換する（QA指摘対応・Low#5）。mode="before" で型強制（Enum変換）より
        前に検証することで、既定の英語エラーメッセージが先に確定するのを防ぐ。
        """
        if v is None or isinstance(v, ItemCondition):
            return v
        valid_values = {c.value for c in ItemCondition}
        if v not in valid_values:
            allowed = "/".join(c.value for c in ItemCondition)
            raise ValueError(f"状態は {allowed} のいずれかを指定してください。")
        return v


class CaseCreateRequest(BaseModel):
    purpose: str = Field(max_length=64)
    prefecture: str = Field(min_length=1, max_length=32)
    city: str = Field(min_length=1, max_length=64)
    address_detail: str | None = None
    housing_type: str | None = Field(default=None, max_length=32)
    floor_plan: str | None = Field(default=None, max_length=32)
    floor_number: int | None = Field(default=None, ge=0, le=100)
    has_elevator: bool | None = None
    # 未分類写真（商品グループに属さない写真）。既存クライアント向けに維持する。
    photos: list[CasePhotoIn] = Field(default_factory=list, max_length=MAX_PHOTOS_PER_CASE)
    # 商品ごとにグルーピングした写真。photos と併用可能（合計枚数は model_validator で検証）。
    items: list[CaseItemIn] = Field(default_factory=list, max_length=MAX_ITEMS_PER_CASE)

    @model_validator(mode="after")
    def _validate_total_photo_count(self) -> "CaseCreateRequest":
        """items 配下の全 photos + 直下の photos の合計が上限を超えないことを検証する。

        items[].photos は max_length=MAX_PHOTOS_PER_ITEM で個別に制限済みだが、
        商品数 × 商品ごとの上限を単純合算すると案件全体の上限（MAX_PHOTOS_PER_CASE）を
        超えうるため、ここで合計値を別途検証する。
        """
        total = len(self.photos) + sum(len(item.photos) for item in self.items)
        if total > MAX_PHOTOS_PER_CASE:
            raise ValueError(
                f"写真の合計枚数が上限（{MAX_PHOTOS_PER_CASE}枚）を超えています。"
            )
        return self


class CaseCancelRequest(BaseModel):
    """出品取り下げ（ユーザー向け）。TransactionCancelRequest と同型。"""

    reason: str | None = Field(default=None, max_length=2000)


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
    items: list[CaseItemOut] = []
    item_count: int = 0
    photo_count: int = 0
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
    items: list[CaseItemOut] = []
    item_count: int = 0
    photo_count: int = 0
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


class OperatorSuspendRequest(BaseModel):
    """業者アカウントの停止／停止解除（admin 専用）。"""

    suspended: bool


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
    # 許可証画像のアップロード有無・時刻（BLOB本体は含めない）。
    license_image_uploaded_at: datetime | None = None


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
    # 運営承認済み（vendor_status == "active"）。公開画面の「古物商許可済」バッジはこれを根拠にする
    # （verified_at は招待コード登録だと付かない古い手動承認フィールドのため）。
    is_approved: bool = False
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
