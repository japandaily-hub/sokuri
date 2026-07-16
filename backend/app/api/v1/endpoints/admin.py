"""Admin endpoints."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.crypto import decrypt_json
from app.db.models.case import Case
from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.operator_application import OperatorApplication
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    BankAccountMaskedOut,
    InviteBulkCreateRequest,
    InviteBulkCreateResponse,
    InviteCreateRequest,
    InviteOut,
    OperatorApplicationApproveResponse,
    OperatorApplicationBankAccountRevealOut,
    OperatorApplicationOut,
    OperatorApplicationRejectRequest,
    OperatorOut,
    OperatorVerifyRequest,
)
from app.services import notify

logger = logging.getLogger(__name__)

router = APIRouter()


def _generate_code() -> str:
    return f"KDZ-{secrets.token_hex(4).upper()}"


async def _issue_unique_invite_code(session: AsyncSession) -> str:
    """DB衝突を避けて一意な招待コードを発行する（既存 create_invite と同じ作法）。"""
    code = _generate_code()
    while await session.scalar(select(Invite).where(Invite.code == code)) is not None:
        code = _generate_code()
    return code


def _mask_account_number(account_number: str) -> str:
    """口座番号の下4桁のみ残しマスクする。4桁以下はそのまま返さず全マスクする。"""
    if len(account_number) <= 4:
        return "*" * len(account_number)
    return "*" * (len(account_number) - 4) + account_number[-4:]


def _to_application_out(application: OperatorApplication) -> OperatorApplicationOut:
    bank_account_masked: BankAccountMaskedOut | None = None
    if application.bank_account_enc:
        try:
            decrypted = decrypt_json(application.bank_account_enc)
            bank_account_masked = BankAccountMaskedOut(
                bank_name=decrypted["bank_name"],
                branch_name=decrypted["branch_name"],
                account_type=decrypted["account_type"],
                account_number_masked=_mask_account_number(decrypted["account_number"]),
                account_holder=decrypted["account_holder"],
            )
        except Exception as exc:
            logger.error(
                "admin: operator_application の口座情報復号に失敗 - id=%s - %s",
                application.id,
                exc,
            )
    return OperatorApplicationOut(
        id=application.id,
        status=application.status,
        company_name=application.company_name,
        representative_name=application.representative_name,
        registered_address=application.registered_address,
        contact_name=application.contact_name,
        contact_email=application.contact_email,
        contact_phone=application.contact_phone,
        license_number=application.license_number,
        business_type=application.business_type,
        service_area=application.service_area,
        categories=application.categories,
        message=application.message,
        invoice_number=application.invoice_number,
        bank_account=bank_account_masked,
        agreed_terms_version=application.agreed_terms_version,
        agreed_at=application.agreed_at,
        reviewed_by=application.reviewed_by,
        reviewed_at=application.reviewed_at,
        reject_reason=application.reject_reason,
        operator_id=application.operator_id,
        created_at=application.created_at,
    )


async def _get_application_or_404(session: AsyncSession, application_id: uuid.UUID) -> OperatorApplication:
    application = await session.get(OperatorApplication, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申込が見つかりません。")
    return application


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
    operator.vendor_status = "active" if body.verified else "pending"
    await session.commit()
    await session.refresh(operator)
    return OperatorOut.model_validate(operator)


@router.get("/admin/cell-density")
async def get_cell_density(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    # 需給密度は「入札可能な稼働業者数」が指標として正確なため active のみを数える
    # （pending は入札不可、limited はレガシー値で新規発生しない）。
    active_suppliers_count = await session.scalar(
        select(func.count()).select_from(Operator).where(
            Operator.vendor_status == "active",
            Operator.is_suspended.is_(False),
        )
    )
    active_suppliers = int(active_suppliers_count or 0)

    # 生SQLの datetime('now','-30 days') は SQLite 専用関数で本番 PostgreSQL では
    # エラーになるため、方言非依存の SQLAlchemy 式で書く。
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = await session.execute(
        select(
            Case.prefecture,
            Case.purpose,
            func.count().label("open_cases"),
        )
        .where(Case.status.in_(("open", "bidding")), Case.created_at >= cutoff)
        .group_by(Case.prefecture, Case.purpose)
        .order_by(func.count().desc())
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


# ──────────────────────────── 業者事前申込（審査） ────────────────────────────


@router.get("/admin/operator-applications", response_model=list[OperatorApplicationOut])
async def list_operator_applications(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[OperatorApplicationOut]:
    applications = (
        await session.scalars(
            select(OperatorApplication).order_by(OperatorApplication.created_at.desc())
        )
    ).all()
    return [_to_application_out(a) for a in applications]


@router.get(
    "/admin/operator-applications/{application_id}", response_model=OperatorApplicationOut
)
async def get_operator_application(
    application_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> OperatorApplicationOut:
    application = await _get_application_or_404(session, application_id)
    return _to_application_out(application)


@router.post(
    "/admin/operator-applications/{application_id}/reveal-bank-account",
    response_model=OperatorApplicationBankAccountRevealOut,
    summary="振込先口座情報を全桁復号して開示する（admin限定・アクセスをログ記録）",
)
async def reveal_operator_application_bank_account(
    application_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> OperatorApplicationBankAccountRevealOut:
    application = await _get_application_or_404(session, application_id)
    if not application.bank_account_enc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="口座情報が登録されていません。"
        )
    try:
        decrypted = decrypt_json(application.bank_account_enc)
    except Exception as exc:
        logger.error(
            "admin: operator_application の口座情報復号に失敗 - id=%s admin=%s - %s",
            application.id,
            admin.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="口座情報の復号に失敗しました。"
        ) from exc

    # 誰が・いつ・どの申込の口座情報を復号したかを監査可能な形で記録する。
    logger.info(
        "admin: 口座情報を復号しました - application_id=%s admin_id=%s admin_email=%s",
        application.id,
        admin.id,
        admin.email,
    )
    return OperatorApplicationBankAccountRevealOut(
        bank_name=decrypted["bank_name"],
        branch_name=decrypted["branch_name"],
        account_type=decrypted["account_type"],
        account_number=decrypted["account_number"],
        account_holder=decrypted["account_holder"],
    )


@router.patch(
    "/admin/operator-applications/{application_id}/approve",
    response_model=OperatorApplicationApproveResponse,
    summary="業者申込を承認し招待コードを発行する",
)
async def approve_operator_application(
    application_id: uuid.UUID,
    background: BackgroundTasks,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> OperatorApplicationApproveResponse:
    application = await _get_application_or_404(session, application_id)
    if application.status != "received":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この申込は既に審査済みです。",
        )

    code = await _issue_unique_invite_code(session)
    invite = Invite(code=code, email=application.contact_email)
    session.add(invite)

    application.status = "approved"
    application.reviewed_by = admin.id
    application.reviewed_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(application)
    await session.refresh(invite)

    background.add_task(
        notify.send_operator_application_approved,
        application.contact_email,
        application.company_name,
        invite.code,
    )
    logger.info(
        "admin: 業者申込を承認しました - application_id=%s admin_id=%s invite_code=%s",
        application.id,
        admin.id,
        invite.code,
    )
    return OperatorApplicationApproveResponse(
        application=_to_application_out(application), invite_code=invite.code
    )


@router.patch(
    "/admin/operator-applications/{application_id}/reject",
    response_model=OperatorApplicationOut,
    summary="業者申込を却下する",
)
async def reject_operator_application(
    application_id: uuid.UUID,
    body: OperatorApplicationRejectRequest,
    background: BackgroundTasks,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> OperatorApplicationOut:
    application = await _get_application_or_404(session, application_id)
    if application.status != "received":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この申込は既に審査済みです。",
        )

    application.status = "rejected"
    application.reviewed_by = admin.id
    application.reviewed_at = datetime.now(timezone.utc)
    application.reject_reason = body.reject_reason

    await session.commit()
    await session.refresh(application)

    background.add_task(
        notify.send_operator_application_rejected,
        application.contact_email,
        application.company_name,
        body.reject_reason,
    )
    logger.info(
        "admin: 業者申込を却下しました - application_id=%s admin_id=%s",
        application.id,
        admin.id,
    )
    return _to_application_out(application)
