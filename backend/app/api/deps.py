"""FastAPI 依存性 — JWT 認証（user / operator / admin）。

全カタヅケ API はこのモジュールの依存性で保護する。
- get_current_user     : typ=user の JWT 必須
- get_current_admin    : typ=user かつ role=admin
- get_current_operator : typ=operator（停止中業者は 403）
- get_current_actor    : user / operator どちらでも可（成約・レビュー用）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session

_bearer = HTTPBearer(auto_error=False)

_CRED_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="認証情報が無効です。再度ログインしてください。",
    headers={"WWW-Authenticate": "Bearer"},
)


def _decode(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None or not credentials.credentials:
        raise _CRED_EXC
    try:
        return decode_access_token(credentials.credentials)
    except pyjwt.PyJWTError as exc:
        raise _CRED_EXC from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    payload = _decode(credentials)
    if payload.get("typ") != "user":
        raise _CRED_EXC
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise _CRED_EXC
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理者権限が必要です。",
        )
    return user


async def get_current_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Operator:
    payload = _decode(credentials)
    if payload.get("typ") != "operator":
        raise _CRED_EXC
    operator = await session.get(Operator, uuid.UUID(payload["sub"]))
    if operator is None:
        raise _CRED_EXC
    if operator.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントが停止されています。運営にお問い合わせください。",
        )
    return operator


async def get_verified_operator(
    operator: Operator = Depends(get_current_operator),
) -> Operator:
    """承認済み（verified_at あり）の業者のみ許可する。"""
    if operator.verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントは承認待ちです。承認後に利用できます。",
        )
    return operator


@dataclass
class Actor:
    """user / operator いずれかの認証主体。"""

    typ: str  # 'user' | 'operator'
    user: User | None = None
    operator: Operator | None = None

    @property
    def id(self) -> uuid.UUID:
        obj = self.user if self.typ == "user" else self.operator
        assert obj is not None
        return obj.id


async def get_current_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Actor:
    payload = _decode(credentials)
    typ = payload.get("typ")
    subject_id = uuid.UUID(payload["sub"])
    if typ == "user":
        user = await session.get(User, subject_id)
        if user is None:
            raise _CRED_EXC
        return Actor(typ="user", user=user)
    if typ == "operator":
        operator = await session.get(Operator, subject_id)
        if operator is None:
            raise _CRED_EXC
        if operator.is_suspended:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="アカウントが停止されています。",
            )
        return Actor(typ="operator", operator=operator)
    raise _CRED_EXC
