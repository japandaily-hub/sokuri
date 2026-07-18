"""FastAPI deps -- JWT auth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timezone

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
    detail="Invalid credentials. Please log in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _decode(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None or not credentials.credentials:
        raise _CRED_EXC
    try:
        return decode_access_token(credentials.credentials)
    except pyjwt.PyJWTError as exc:
        raise _CRED_EXC from exc


def _assert_user_not_revoked(user: User, payload: dict) -> None:
    """退会（論理削除）済み・パスワード変更後の旧トークンを 401 で失効させる。

    - 論理削除ゲート: deleted_at が設定済みのアカウントの旧トークンは即時失効させる。
    - パスワード変更失効ゲート: JWT の iat が password_changed_at より古い場合に拒否する。
      iat は PyJWT により epoch 秒の int にエンコードされるため、比較も int 切り捨てで行い
      同一秒内に発行された新トークンを誤って弾かないようにする。
      SQLite は tz-naive な datetime を返すため、tzinfo が無ければ UTC を補って比較する
      （tz なしのまま timestamp() するとローカルタイム解釈になりズレるため）。
    """
    if user.deleted_at is not None:
        raise _CRED_EXC

    if user.password_changed_at is None:
        return
    iat = payload.get("iat")
    if iat is None:
        return
    changed_at = user.password_changed_at
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    if int(iat) < int(changed_at.timestamp()):
        raise _CRED_EXC


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
    _assert_user_not_revoked(user, payload)
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
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
            detail="アカウントは停止中です。運営へお問い合わせください。",
        )
    return operator


async def get_verified_operator(
    operator: Operator = Depends(get_current_operator),
) -> Operator:
    """入札等のフル稼働操作を許可するゲート。

    全業者は admin 承認必須。vendor_status="active" の業者のみ許可する
    （"pending"=未承認、"limited"=レガシー値のいずれも入札不可）。
    案件の閲覧はこのゲートを経由しない別ゲート（get_current_actor等）で
    pending でも許可している点に注意（意図的な非対称: 閲覧可・入札不可）。
    """
    if operator.vendor_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントは承認待ちです。運営の承認完了後に入札などの操作ができるようになります。",
        )
    if operator.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントは停止中です。運営へお問い合わせください。",
        )
    return operator


@dataclass
class Actor:
    """Either user or operator principal."""

    typ: str
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
        _assert_user_not_revoked(user, payload)
        return Actor(typ="user", user=user)
    if typ == "operator":
        operator = await session.get(Operator, subject_id)
        if operator is None:
            raise _CRED_EXC
        if operator.is_suspended:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="アカウントは停止中です。運営へお問い合わせください。",
            )
        return Actor(typ="operator", operator=operator)
    raise _CRED_EXC
