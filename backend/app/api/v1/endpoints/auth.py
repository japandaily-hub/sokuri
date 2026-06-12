"""認証エンドポイント — ユーザー（email+password）/ 業者（招待コード+email）。

JWT はバックエンドが発行し、フロントエンド（NextAuth.js）は本 API を
Credentials Provider から呼び出して取得したトークンをセッションに保持する。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Actor, get_current_actor
from app.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    AuthTokenResponse,
    OperatorLoginRequest,
    OperatorOut,
    OperatorSignupRequest,
    UserLoginRequest,
    UserOut,
    UserSignupRequest,
)

router = APIRouter()

_LOGIN_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="メールアドレスまたはパスワードが正しくありません。",
)


# ──────────────────────────── ユーザー ────────────────────────────


@router.post(
    "/auth/signup",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="ユーザー登録",
)
async def user_signup(
    body: UserSignupRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokenResponse:
    email = body.email.lower()
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このメールアドレスは既に登録されています。",
        )
    role = "admin" if email in get_settings().admin_emails else "user"
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    token = create_access_token(user.id, "user", user.role)
    return AuthTokenResponse(
        access_token=token, account_type="user", user=UserOut.model_validate(user)
    )


@router.post("/auth/login", response_model=AuthTokenResponse, summary="ユーザーログイン")
async def user_login(
    body: UserLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokenResponse:
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise _LOGIN_FAILED
    token = create_access_token(user.id, "user", user.role)
    return AuthTokenResponse(
        access_token=token, account_type="user", user=UserOut.model_validate(user)
    )


# ──────────────────────────── 業者 ────────────────────────────


@router.post(
    "/auth/operator/signup",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="業者登録（招待コード必須）",
)
async def operator_signup(
    body: OperatorSignupRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokenResponse:
    invite = await session.scalar(select(Invite).where(Invite.code == body.invite_code))
    if invite is None or invite.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="招待コードが無効、または既に使用されています。",
        )
    email = body.email.lower()
    existing = await session.scalar(select(Operator).where(Operator.contact_email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このメールアドレスは既に登録されています。",
        )
    operator = Operator(
        company_name=body.company_name,
        contact_email=email,
        license_number=body.license_number,
        invite_code=body.invite_code,
        password_hash=hash_password(body.password),
        verified_at=None,  # 管理者承認待ち
    )
    session.add(operator)
    await session.flush()
    invite.used_at = datetime.now(timezone.utc)
    invite.operator_id = operator.id
    await session.commit()
    await session.refresh(operator)
    token = create_access_token(operator.id, "operator", "operator")
    return AuthTokenResponse(
        access_token=token,
        account_type="operator",
        operator=OperatorOut.model_validate(operator),
    )


@router.post(
    "/auth/operator/login", response_model=AuthTokenResponse, summary="業者ログイン"
)
async def operator_login(
    body: OperatorLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokenResponse:
    operator = await session.scalar(
        select(Operator).where(Operator.contact_email == body.email.lower())
    )
    if (
        operator is None
        or operator.password_hash is None
        or not verify_password(body.password, operator.password_hash)
    ):
        raise _LOGIN_FAILED
    if operator.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントが停止されています。運営にお問い合わせください。",
        )
    token = create_access_token(operator.id, "operator", "operator")
    return AuthTokenResponse(
        access_token=token,
        account_type="operator",
        operator=OperatorOut.model_validate(operator),
    )


# ──────────────────────────── 共通 ────────────────────────────


@router.get("/auth/me", response_model=AuthTokenResponse, summary="ログイン中アカウント情報")
async def me(actor: Actor = Depends(get_current_actor)) -> AuthTokenResponse:
    """トークン検証を兼ねたプロフィール取得（access_token は返却しない）。"""
    if actor.typ == "user":
        assert actor.user is not None
        return AuthTokenResponse(
            access_token="", account_type="user", user=UserOut.model_validate(actor.user)
        )
    assert actor.operator is not None
    return AuthTokenResponse(
        access_token="",
        account_type="operator",
        operator=OperatorOut.model_validate(actor.operator),
    )
