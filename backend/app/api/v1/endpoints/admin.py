"""Admin endpoints."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    InviteBulkCreateRequest,
    InviteBulkCreateResponse,
    InviteCreateRequest,
    InviteOut,
    OperatorOut,
    OperatorVerifyRequest,
)

router = APIRouter()


def _generate_code() -> str:
    return f"KDZ-{secrets.token_hex(4).upper()}"


@router.post("/admin/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteCreateRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    code = _generate_code()
    while await session.scalar(select(Invite).where(Invite.code == code)) is not None:
        code = _generate_code()
    invite = Invite(code=code, email=body.email.lower() if body.email else None)
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return InviteOut.model_validate(invite)


@router.post("/admin/invites/bulk", response_model=InviteBulkCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_invites_bulk(
    body: InviteBulkCreateRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> InviteBulkCreateResponse:
    codes = []
    for _ in range(body.count):
        while True:
            code = _generate_code()
            if await session.scalar(select(Invite).where(Invite.code == code)) is None:
                break
        invite = Invite(code=code, email=None, lot_name=body.lot_name)
        session.add(invite)
        codes.append(code)
    await session.commit()
    return InviteBulkCreateResponse(codes=codes, lot_name=body.lot_name, count=len(codes))


@router.get("/admin/invites", response_model=list[InviteOut])
async def list_invites(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[InviteOut]:
    invites = (await session.scalars(select(Invite).order_by(Invite.created_at.desc()))).all()
    return [InviteOut.model_validate(i) for i in invites]


@router.get("/admin/operators", response_model=list[OperatorOut])
async def list_operators(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[OperatorOut]:
    operators = (await session.scalars(select(Operator).order_by(Operator.created_at.desc()))).all()
    return [OperatorOut.model_validate(o) for o in operators]


@router.patch("/admin/operators/{operator_id}/verify", response_model=OperatorOut)
async def verify_operator(
    operator_id: uuid.UUID,
    body: OperatorVerifyRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> OperatorOut:
    operator = await session.get(Operator, operator_id)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found.")
    operator.verified_at = datetime.now(timezone.utc) if body.verified else None
    operator.vendor_status = "active" if body.verified else "limited"
    await session.commit()
    await session.refresh(operator)
    return OperatorOut.model_validate(operator)


@router.get("/admin/cell-density")
async def get_cell_density(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    active_suppliers_count = await session.scalar(
        select(func.count()).select_from(Operator).where(
            Operator.vendor_status.in_(["limited", "active"]),
            Operator.is_suspended.is_(False),
        )
    )
    active_suppliers = int(active_suppliers_count or 0)

    rows = await session.execute(
        text(
            "SELECT prefecture, purpose, COUNT(*) AS open_cases "
            "FROM cases "
            "WHERE status IN ('open', 'bidding') "
            "AND created_at >= datetime('now', '-30 days') "
            "GROUP BY prefecture, purpose "
            "ORDER BY open_cases DESC"
        )
    )

    result = []
    for row in rows:
        open_cases = int(row.open_cases)
        demand_per_supplier = round(open_cases / active_suppliers, 2) if active_suppliers > 0 else 0.0
        result.append({
            "prefecture": row.prefecture,
            "purpose": row.purpose,
            "open_cases": open_cases,
            "active_suppliers": active_suppliers,
            "demand_per_supplier": demand_per_supplier,
            "status": "dense" if demand_per_supplier > 1.5 else "normal",
        })

    return result
