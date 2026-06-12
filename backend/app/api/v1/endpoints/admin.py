"""管理エンドポイント — 招待コード発行 / 業者承認（admin ロールのみ）。"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    InviteCreateRequest,
    InviteOut,
    OperatorOut,
    OperatorVerifyRequest,
)

router = APIRouter()


def _generate_code() -> str:
    """KDZ-XXXXXXXX 形式の招待コード（推測困難・読み上げ可能）。"""
    return f"KDZ-{secrets.token_hex(4).upper()}"


@router.post(
    "/admin/invites",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
    summary="業者招待コードの発行",
)
async def create_invite(
    body: InviteCreateRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    # 衝突時は再生成（unique 制約があるため事前確認）
    code = _generate_code()
    while await session.scalar(select(Invite).where(Invite.code == code)) is not None:
        code = _generate_code()
    invite = Invite(code=code, email=body.email.lower() if body.email else None)
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return InviteOut.model_validate(invite)


@router.get("/admin/invites", response_model=list[InviteOut], summary="招待コード一覧")
async def list_invites(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[InviteOut]:
    invites = (
        await session.scalars(select(Invite).order_by(Invite.created_at.desc()))
    ).all()
    return [InviteOut.model_validate(i) for i in invites]


@router.get("/admin/operators", response_model=list[OperatorOut], summary="業者一覧")
async def list_operators(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[OperatorOut]:
    operators = (
        await session.scalars(select(Operator).order_by(Operator.created_at.desc()))
    ).all()
    return [OperatorOut.model_validate(o) for o in operators]


@router.patch(
    "/admin/operators/{operator_id}/verify",
    response_model=OperatorOut,
    summary="業者の承認 / 承認取消",
)
async def verify_operator(
    operator_id: uuid.UUID,
    body: OperatorVerifyRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> OperatorOut:
    operator = await session.get(Operator, operator_id)
    if operator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="業者が見つかりません。"
        )
    operator.verified_at = datetime.now(timezone.utc) if body.verified else None
    await session.commit()
    await session.refresh(operator)
    return OperatorOut.model_validate(operator)
