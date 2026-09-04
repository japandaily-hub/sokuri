"""Admin endpoints."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.crypto import decrypt_json
from app.db.models.bid import Bid
from app.core.masking import mask_account_number
from app.db.models.case import Case
from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.operator_application import OperatorApplication
from app.db.models.transaction import Review, Transaction
from app.db.models.user import (
    IDENTITY_STATUS_APPROVED,
    IDENTITY_STATUS_REJECTED,
    User,
)
from app.db.models.user_identity_document import (
    DOCUMENT_STATUS_APPROVED,
    DOCUMENT_STATUS_PENDING,
    DOCUMENT_STATUS_REJECTED,
    UserIdentityDocument,
)
from app.db.session import get_session
from app.schemas_katadzuke import (
    BankAccountMaskedOut,
    IdentityDocumentRejectRequest,
    InviteBulkCreateRequest,
    InviteBulkCreateResponse,
    InviteCreateRequest,
    InviteOut,
    OperatorApplicationApproveResponse,
    OperatorApplicationBankAccountRevealOut,
    OperatorApplicationOut,
    OperatorApplicationRejectRequest,
    OperatorOut,
    OperatorSuspendRequest,
    OperatorVerifyRequest,
    ReviewHideRequest,
    ReviewOut,
    UserIdentityDocumentAdminOut,
)
from app.services import notify
from app.services.review_stats import recalc_operator_review_stats

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


def _to_application_out(application: OperatorApplication) -> OperatorApplicationOut:
    bank_account_masked: BankAccountMaskedOut | None = None
    if application.bank_account_enc:
        try:
            decrypted = decrypt_json(application.bank_account_enc)
            bank_account_masked = BankAccountMaskedOut(
                bank_name=decrypted["bank_name"],
                branch_name=decrypted["branch_name"],
                account_type=decrypted["account_type"],
                account_number_masked=mask_account_number(decrypted["account_number"]),
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
    # 承認（pending/limited → active）は古物商許可証画像の提出を必須にする。
    # 招待コード登録で既に active の業者に対する verified_at の付与は対象外
    # （状態遷移を伴わないため）。フロント（/admin）の disabled 制御と同じ規則。
    if body.verified and operator.vendor_status != "active" and not operator.has_license_image:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="許可証画像が未提出のため承認できません。業者に許可証のアップロードを依頼してください。",
        )
    operator.verified_at = datetime.now(timezone.utc) if body.verified else None
    operator.vendor_status = "active" if body.verified else "pending"
    await session.commit()
    await session.refresh(operator)
    logger.info(
        "admin_operator_verify admin=%s operator=%s verified=%s", admin.id, operator.id, body.verified
    )
    return OperatorOut.model_validate(operator)


@router.patch("/admin/operators/{operator_id}/suspend", response_model=OperatorOut)
async def suspend_operator(
    operator_id: uuid.UUID,
    body: OperatorSuspendRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> OperatorOut:
    """業者アカウントを停止（suspended=true）／停止解除（false）する。

    停止中は ``assert_operator_not_suspended``（deps.py）により既存トークンでの
    全操作が 403 になり、ログインも拒否される。解除すると即時に元の
    vendor_status のまま復帰する（承認状態は変更しない）。
    """
    operator = await session.get(Operator, operator_id)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found.")
    operator.is_suspended = body.suspended
    await session.commit()
    await session.refresh(operator)
    logger.info(
        "admin_operator_suspend admin=%s operator=%s suspended=%s", admin.id, operator.id, body.suspended
    )
    return OperatorOut.model_validate(operator)


@router.patch("/admin/reviews/{review_id}/hide", response_model=ReviewOut)
async def hide_review(
    review_id: uuid.UUID,
    body: ReviewHideRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ReviewOut:
    """口コミを運営が非表示（hidden=true）／再表示（false）にする。

    口コミは常時公開のため、誹謗中傷・第三者の個人情報・送信防止措置の申出への
    対応経路として用意する（security review H-2）。物理削除はせず hidden_at で
    論理削除し、公開プロフィール・一覧・集計（rating / review_count / 抜粋）から除外する。
    """
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    review.hidden_at = datetime.now(timezone.utc) if body.hidden else None
    review.hidden_reason = (body.reason or None) if body.hidden else None
    await session.flush()
    txn = await session.get(Transaction, review.transaction_id)
    bid = await session.get(Bid, txn.bid_id) if txn is not None else None
    if review.reviewer_type == "user" and bid is not None:
        await recalc_operator_review_stats(session, bid.operator_id)
    await session.commit()
    await session.refresh(review)
    logger.info(
        "admin_review_hide admin=%s review=%s hidden=%s", admin.id, review.id, body.hidden
    )
    return ReviewOut.model_validate(review)


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


# ──────────────────────────── 依頼者の本人確認書類（審査） ────────────────────────────

_IDENTITY_DOCUMENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="本人確認書類が見つかりません。"
)
_IDENTITY_DOCUMENT_ALREADY_REVIEWED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="この本人確認書類は既に審査済みです。"
)
_IDENTITY_DOCUMENT_ERASED = HTTPException(
    status_code=status.HTTP_410_GONE, detail="この書類は退会により削除されています。"
)


async def _get_identity_document_or_404(
    session: AsyncSession, document_id: uuid.UUID
) -> UserIdentityDocument:
    document = await session.get(UserIdentityDocument, document_id)
    if document is None:
        raise _IDENTITY_DOCUMENT_NOT_FOUND
    return document


@router.get(
    "/admin/identity-documents",
    response_model=list[UserIdentityDocumentAdminOut],
    summary="依頼者の本人確認書類一覧（既定 status=pending）",
)
async def list_identity_documents(
    status_filter: Literal["pending", "approved", "rejected", "all"] = Query(
        default="pending", alias="status"
    ),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UserIdentityDocumentAdminOut]:
    # BLOB本体（front_image_data/back_image_data）は一覧に一切含めない（deferred属性の
    # 意図しないロードを避けるため、Core の列指定 select で必要な列のみ取得する）。
    stmt = (
        select(
            UserIdentityDocument.id,
            UserIdentityDocument.user_id,
            User.email,
            User.name,
            UserIdentityDocument.doc_type,
            UserIdentityDocument.status,
            UserIdentityDocument.submitted_at,
            UserIdentityDocument.reviewed_at,
            UserIdentityDocument.reject_reason,
            UserIdentityDocument.back_image_data.isnot(None),
        )
        .join(User, UserIdentityDocument.user_id == User.id)
        # 退会（匿名化）済みユーザーの書類は審査対象外のため一覧から除外する
        # （QA M-2。画像本体は退会時に既に消去済みだが、行・審査履歴は保持される
        # ため JOIN だけでは自然には消えない）。
        .where(User.deleted_at.is_(None))
        .order_by(UserIdentityDocument.submitted_at.desc())
    )
    if status_filter != "all":
        stmt = stmt.where(UserIdentityDocument.status == status_filter)

    rows = (await session.execute(stmt)).all()
    # PII本体（氏名・メール等）はログに書かず、監査に必要な操作主体・件数・
    # フィルタ条件のみ記録する（M-3）。
    logger.info(
        "admin: 本人確認書類一覧を取得しました - status=%s count=%d admin_id=%s admin_email=%s",
        status_filter,
        len(rows),
        admin.id,
        admin.email,
    )
    return [
        UserIdentityDocumentAdminOut(
            id=row[0],
            user_id=row[1],
            user_email=row[2],
            user_name=row[3],
            doc_type=row[4],
            status=row[5],
            submitted_at=row[6],
            reviewed_at=row[7],
            reject_reason=row[8],
            has_back=bool(row[9]),
        )
        for row in rows
    ]


@router.get(
    "/admin/identity-documents/{document_id}/file",
    summary="依頼者の本人確認書類の画像を取得（admin限定・アクセスをログ記録）",
)
async def get_identity_document_file_admin(
    document_id: uuid.UUID,
    side: Literal["front", "back"] = Query(...),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if side == "front":
        columns = (UserIdentityDocument.front_image_data, UserIdentityDocument.front_image_content_type)
    else:
        columns = (UserIdentityDocument.back_image_data, UserIdentityDocument.back_image_content_type)
    row = (
        await session.execute(select(*columns).where(UserIdentityDocument.id == document_id))
    ).first()
    if row is None or row[0] is None:
        raise _IDENTITY_DOCUMENT_NOT_FOUND
    data, content_type = row
    logger.info(
        "admin: 本人確認書類を閲覧しました - document_id=%s side=%s admin_id=%s admin_email=%s",
        document_id,
        side,
        admin.id,
        admin.email,
    )
    return Response(
        content=data,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )


@router.patch(
    "/admin/identity-documents/{document_id}/approve",
    response_model=UserIdentityDocumentAdminOut,
    summary="本人確認書類を承認する（pending以外は409）",
)
async def approve_identity_document(
    document_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> UserIdentityDocumentAdminOut:
    # front_image_data は deferred のため Core の列指定 select で明示取得する
    # （operator_license.py と同じ理由）。退会（匿名化）で画像本体のみ消去された
    # 書類は審査対象外として 410 で拒否する（QA M-2）。
    row = (
        await session.execute(
            select(UserIdentityDocument.front_image_data.isnot(None)).where(
                UserIdentityDocument.id == document_id
            )
        )
    ).first()
    if row is None:
        raise _IDENTITY_DOCUMENT_NOT_FOUND
    if not row[0]:
        raise _IDENTITY_DOCUMENT_ERASED

    # TOCTOU対策（security review M-2）: SELECTで確認してからORMで更新すると、
    # 管理画面の多重クリックや複数管理者の同時操作で2回承認処理が走りうる。
    # 「pendingである」ことを WHERE 条件に含めた条件付き UPDATE にすることで、
    # 判定と更新をDB側でアトミックに行う（rowcount==0 なら既に審査済み）。
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(UserIdentityDocument)
        .where(
            UserIdentityDocument.id == document_id,
            UserIdentityDocument.status == DOCUMENT_STATUS_PENDING,
        )
        .values(status=DOCUMENT_STATUS_APPROVED, reviewed_by=admin.id, reviewed_at=now)
    )
    if result.rowcount == 0:
        raise _IDENTITY_DOCUMENT_ALREADY_REVIEWED

    document = await _get_identity_document_or_404(session, document_id)
    user = await session.get(User, document.user_id)
    if user is not None:
        user.identity_status = IDENTITY_STATUS_APPROVED

    await session.commit()
    await session.refresh(document)

    has_back = await session.scalar(
        select(UserIdentityDocument.back_image_data.isnot(None)).where(
            UserIdentityDocument.id == document.id
        )
    )
    logger.info(
        "admin: 本人確認書類を承認しました - document_id=%s user_id=%s admin_id=%s",
        document.id,
        document.user_id,
        admin.id,
    )
    return UserIdentityDocumentAdminOut(
        id=document.id,
        user_id=document.user_id,
        user_email=user.email if user is not None else "",
        user_name=user.name if user is not None else None,
        doc_type=document.doc_type,
        status=document.status,
        submitted_at=document.submitted_at,
        reviewed_at=document.reviewed_at,
        reject_reason=document.reject_reason,
        has_back=bool(has_back),
    )


@router.patch(
    "/admin/identity-documents/{document_id}/reject",
    response_model=UserIdentityDocumentAdminOut,
    summary="本人確認書類を却下する（pending以外は409）",
)
async def reject_identity_document(
    document_id: uuid.UUID,
    body: IdentityDocumentRejectRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> UserIdentityDocumentAdminOut:
    # approve_identity_document と同じ理由（front_image_data は deferred・
    # 退会消去済みは審査対象外として410）。
    row = (
        await session.execute(
            select(UserIdentityDocument.front_image_data.isnot(None)).where(
                UserIdentityDocument.id == document_id
            )
        )
    ).first()
    if row is None:
        raise _IDENTITY_DOCUMENT_NOT_FOUND
    if not row[0]:
        raise _IDENTITY_DOCUMENT_ERASED

    # TOCTOU対策（security review M-2。approve_identity_document と同じ理由）。
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(UserIdentityDocument)
        .where(
            UserIdentityDocument.id == document_id,
            UserIdentityDocument.status == DOCUMENT_STATUS_PENDING,
        )
        .values(
            status=DOCUMENT_STATUS_REJECTED,
            reviewed_by=admin.id,
            reviewed_at=now,
            reject_reason=body.reject_reason,
        )
    )
    if result.rowcount == 0:
        raise _IDENTITY_DOCUMENT_ALREADY_REVIEWED

    document = await _get_identity_document_or_404(session, document_id)
    user = await session.get(User, document.user_id)
    if user is not None:
        user.identity_status = IDENTITY_STATUS_REJECTED

    await session.commit()
    await session.refresh(document)

    has_back = await session.scalar(
        select(UserIdentityDocument.back_image_data.isnot(None)).where(
            UserIdentityDocument.id == document.id
        )
    )
    logger.info(
        "admin: 本人確認書類を却下しました - document_id=%s user_id=%s admin_id=%s",
        document.id,
        document.user_id,
        admin.id,
    )
    return UserIdentityDocumentAdminOut(
        id=document.id,
        user_id=document.user_id,
        user_email=user.email if user is not None else "",
        user_name=user.name if user is not None else None,
        doc_type=document.doc_type,
        status=document.status,
        submitted_at=document.submitted_at,
        reviewed_at=document.reviewed_at,
        reject_reason=document.reject_reason,
        has_back=bool(has_back),
    )
