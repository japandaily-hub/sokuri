"""カタヅケ API の Pydantic スキーマ。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=128)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class OperatorSignupRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=64)
    company_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    license_number: str | None = Field(default=None, max_length=128)


class OperatorLoginRequest(BaseModel):
    email: EmailStr
    password: str


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
    rating: float | None
    is_suspended: bool
    created_at: datetime


class OperatorPublicOut(BaseModel):
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


class PresignRequest(BaseModel):
    filename: str = Field(max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class PresignResponse(BaseModel):
    storage_key: str
    upload_url: str
    public_url: str


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


class TransactionAddressOut(BaseModel):
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
    status: str
    created_at: datetime


class TransactionDetailOut(TransactionOut):
    case: CaseMaskedOut | None = None
    operator: OperatorPublicOut | None = None
    address: TransactionAddressOut | None = None
    contact_email: str | None = None
    reduction_requests: list[ReductionOut] = []
    reviews: list[ReviewOut] = []


class TransactionCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class TransactionListItem(BaseModel):
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


class InviteCreateRequest(BaseModel):
    email: EmailStr | None = None


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    email: str | None
    used_at: datetime | None
    operator_id: uuid.UUID | None
    created_at: datetime


class OperatorVerifyRequest(BaseModel):
    verified: bool = True


CaseMaskedOut.model_rebuild()
TransactionDetailOut.model_rebuild()
