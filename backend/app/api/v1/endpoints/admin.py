"""Admin endpoints."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    AdminCaseListItem,
    AdminCaseListResponse,
    AdminTransactionListItem,
    AdminTransactionListResponse,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserRoleResponse,
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
    UserSuspendRequest,
    UserSuspendResponse,
)
from app.services import alerts, notify
from app.services.review_stats import recalc_operator_review_stats

# admin 一覧系 API 共通の既定/上限（M2対応）。既存 web 呼び出し（クエリ省略時）が
# 従来どおり動くよう、既定値は「事実上の全件」に近い値にする。
_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 500

logger = logging.getLogger(__name__)

router = APIRouter()


def _escape_ilike_value(value: str) -> str:
    """ilike の特殊文字（``%`` / ``_`` / ``\\``）をエスケープする（security review M-3対応）。

    ``.ilike(pattern, escape="\\")`` と組み合わせて使うこと。エスケープ文字
    自体を最初に置換しないと、後続の ``%``/``_`` エスケープが二重解釈されて
    しまう（例: 元の文字列に ``\\%`` を含む入力）。
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _try_parse_uuid(value: str) -> uuid.UUID | None:
    """``value`` を UUID としてパースできればその値を、できなければ ``None`` を返す。

    admin 一覧の ID 検索で使う（security review M-3: ``cast(id, String).ilike``
    による前方一致・全表スキャンをやめ、UUID として厳密にパースできた場合のみ
    ``==`` の等価比較で絞り込む）。
    """
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


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
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[InviteOut]:
    invites = (
        await session.scalars(
            select(Invite).order_by(Invite.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return [InviteOut.model_validate(i) for i in invites]


@router.get("/admin/operators", response_model=list[OperatorOut])
async def list_operators(
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[OperatorOut]:
    operators = (
        await session.scalars(
            select(Operator).order_by(Operator.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
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


# ──────────────────────────── 案件・成約の横断閲覧（R3-operator H2対応） ────────────────────────────
#
# 運営は従来 GET /cases・GET /transactions を叩いても「admin自身がuserとして
# 作成した案件」しか返らず、トラブル対応・強制介入の起点となるID自体に到達
# できなかった（一覧が空を返す）。個別取得（GET /cases/{id}・GET /transactions/{id}）
# は既に role=="admin" を許容済みのため、ここでは一覧・検索のみを提供する。

_ADMIN_CASE_TXN_DEFAULT_LIMIT = 50
_ADMIN_CASE_TXN_MAX_LIMIT = 200


@router.get(
    "/admin/cases",
    response_model=AdminCaseListResponse,
    summary="案件一覧（admin横断閲覧・依頼者メール/案件IDで検索可）",
)
async def admin_list_cases(
    q: str | None = Query(default=None, max_length=255, description="案件IDの完全一致（UUID） または 依頼者メールの部分一致"),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=_ADMIN_CASE_TXN_DEFAULT_LIMIT, ge=1, le=_ADMIN_CASE_TXN_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminCaseListResponse:
    conditions = []
    if status_filter:
        conditions.append(Case.status == status_filter)
    q_norm = (q or "").strip()
    if q_norm:
        # ``q`` は ORM のバインドパラメータとして渡すため SQL インジェクションの
        # 余地はないが、ilike の `%`/`_` はワイルドカードとして解釈されるため
        # escape 付きで無害化する（security review M-3）。ID 検索は
        # cast(id, String).ilike による前方一致（全表スキャン）をやめ、UUID として
        # 厳密にパースできた場合のみ == の等価比較にする。
        owner_ids_subq = select(User.id).where(
            User.email.ilike(f"%{_escape_ilike_value(q_norm)}%", escape="\\")
        )
        or_clauses: list = [Case.user_id.in_(owner_ids_subq)]
        parsed_case_id = _try_parse_uuid(q_norm)
        if parsed_case_id is not None:
            or_clauses.append(Case.id == parsed_case_id)
        conditions.append(or_(*or_clauses))

    total = await session.scalar(
        select(func.count()).select_from(Case).where(*conditions)
    )

    stmt = (
        select(Case)
        .where(*conditions)
        .options(
            selectinload(Case.bids).selectinload(Bid.operator),
            selectinload(Case.bids).selectinload(Bid.transaction),
        )
        # QA M3対応: created_at 単独キーは同時刻の複数行で順序が不定になりうるため、
        # id を tie-breaker として付け、ページング結果を決定的にする。
        .order_by(Case.created_at.desc(), Case.id.desc())
        .limit(limit)
        .offset(offset)
    )
    cases = (await session.scalars(stmt)).all()

    # 依頼者メールをバッチ取得する（N+1回避。Case には user へのORMリレーションが
    # 無いため、行ごとに session.get するとケース数分のクエリになってしまう）。
    user_ids = {c.user_id for c in cases if c.user_id is not None}
    users_by_id: dict[uuid.UUID, User] = {}
    if user_ids:
        rows = (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
        users_by_id = {u.id: u for u in rows}

    items: list[AdminCaseListItem] = []
    for case in cases:
        selected_bid = next((b for b in case.bids if b.status == "selected"), None)
        txn = selected_bid.transaction if selected_bid is not None else None
        owner = users_by_id.get(case.user_id) if case.user_id is not None else None
        items.append(
            AdminCaseListItem(
                id=case.id,
                status=case.status,
                created_at=case.created_at,
                purpose=case.purpose,
                prefecture=case.prefecture,
                city=case.city,
                user_email=owner.email if owner is not None else None,
                company_name=selected_bid.operator.company_name if selected_bid is not None else None,
                amount=(txn.final_amount if txn is not None and txn.final_amount is not None else (
                    txn.initial_amount if txn is not None else (
                        selected_bid.amount if selected_bid is not None else None
                    )
                )),
                visit_date=txn.visit_date if txn is not None else None,
            )
        )

    logger.info(
        "admin: 案件一覧を取得しました - count=%d total=%d admin_id=%s", len(items), total or 0, admin.id
    )
    return AdminCaseListResponse(items=items, total=int(total or 0))


@router.get(
    "/admin/transactions",
    response_model=AdminTransactionListResponse,
    summary="成約一覧（admin横断閲覧・依頼者メール/業者名/成約ID/案件IDで検索可）",
)
async def admin_list_transactions(
    q: str | None = Query(
        default=None,
        max_length=255,
        description="成約ID/案件IDの完全一致（UUID） または 依頼者メール/業者名の部分一致",
    ),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=_ADMIN_CASE_TXN_DEFAULT_LIMIT, ge=1, le=_ADMIN_CASE_TXN_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminTransactionListResponse:
    conditions = []
    if status_filter:
        conditions.append(Transaction.status == status_filter)
    q_norm = (q or "").strip()
    if q_norm:
        # security review M-3: ilike は escape 付きで無害化し、ID 検索は UUID として
        # 厳密にパースできた場合のみ == の等価比較にする（admin_list_cases と同じ方針）。
        escaped_q = _escape_ilike_value(q_norm)
        owner_ids_subq = select(User.id).where(User.email.ilike(f"%{escaped_q}%", escape="\\"))
        case_ids_by_owner_subq = select(Case.id).where(Case.user_id.in_(owner_ids_subq))
        operator_ids_subq = select(Operator.id).where(
            Operator.company_name.ilike(f"%{escaped_q}%", escape="\\")
        )
        bid_ids_by_operator_subq = select(Bid.id).where(Bid.operator_id.in_(operator_ids_subq))
        or_clauses: list = [
            Transaction.case_id.in_(case_ids_by_owner_subq),
            Transaction.bid_id.in_(bid_ids_by_operator_subq),
        ]
        parsed_id = _try_parse_uuid(q_norm)
        if parsed_id is not None:
            # 貼り付けられた ID が Transaction.id / Case.id のどちらかは
            # UI側では区別できないため、両方に対する厳密一致を許容する
            # （前方一致だった従来動作の意味的等価物）。
            or_clauses.append(Transaction.id == parsed_id)
            or_clauses.append(Transaction.case_id == parsed_id)
        conditions.append(or_(*or_clauses))

    total = await session.scalar(
        select(func.count()).select_from(Transaction).where(*conditions)
    )

    stmt = (
        select(Transaction)
        .where(*conditions)
        .options(
            selectinload(Transaction.case),
            selectinload(Transaction.bid).selectinload(Bid.operator),
        )
        # QA M3対応: created_at 単独キーは同時刻の複数行で順序が不定になりうるため、
        # id を tie-breaker として付け、ページング結果を決定的にする。
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    txns = (await session.scalars(stmt)).all()

    # 依頼者メールをバッチ取得する（N+1回避。上記 admin_list_cases と同じ理由）。
    user_ids = {t.case.user_id for t in txns if t.case is not None and t.case.user_id is not None}
    users_by_id: dict[uuid.UUID, User] = {}
    if user_ids:
        rows = (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
        users_by_id = {u.id: u for u in rows}

    items: list[AdminTransactionListItem] = []
    for txn in txns:
        owner = (
            users_by_id.get(txn.case.user_id)
            if txn.case is not None and txn.case.user_id is not None
            else None
        )
        items.append(
            AdminTransactionListItem(
                id=txn.id,
                case_id=txn.case_id,
                status=txn.status,
                created_at=txn.created_at,
                user_email=owner.email if owner is not None else None,
                company_name=txn.bid.operator.company_name if txn.bid is not None else None,
                amount=txn.final_amount if txn.final_amount is not None else txn.initial_amount,
                visit_date=txn.visit_date,
            )
        )

    logger.info(
        "admin: 成約一覧を取得しました - count=%d total=%d admin_id=%s", len(items), total or 0, admin.id
    )
    return AdminTransactionListResponse(items=items, total=int(total or 0))


@router.get(
    "/admin/users",
    response_model=AdminUserListResponse,
    summary="依頼者一覧（admin横断閲覧・メール/表示名/IDで検索可・既定で退会済みを除外）",
)
async def admin_list_users(
    q: str | None = Query(default=None, max_length=255, description="メール/表示名/IDの部分一致・完全一致"),
    limit: int = Query(default=_ADMIN_CASE_TXN_DEFAULT_LIMIT, ge=1, le=_ADMIN_CASE_TXN_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    include_deleted: bool = Query(
        default=False,
        description="true の場合、退会済み（匿名化済み・deleted_at 非null）ユーザーも含める。既定は除外。",
    ),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminUserListResponse:
    # QA M2対応: 退会済み（deleted_at 非null）ユーザーは既定で一覧から除外する
    # （個人情報は既に匿名化済みだが、運営の日常オペレーション上はノイズになるため）。
    # include_deleted=true で明示的に含められるようにする。
    conditions = [] if include_deleted else [User.deleted_at.is_(None)]
    q_norm = (q or "").strip()
    if q_norm:
        # security review M-3: ilike は escape 付きで無害化する。QA H-2対応:
        # admin_list_cases/admin_list_transactions と同様に ID（UUID厳密一致）
        # 検索も追加する（web の CopyableId でコピーした ID を貼り付けて
        # 検索した際に0件になる不整合の是正）。
        escaped_q = _escape_ilike_value(q_norm)
        or_clauses: list = [
            User.email.ilike(f"%{escaped_q}%", escape="\\"),
            User.name.ilike(f"%{escaped_q}%", escape="\\"),
        ]
        parsed_id = _try_parse_uuid(q_norm)
        if parsed_id is not None:
            or_clauses.append(User.id == parsed_id)
        conditions.append(or_(*or_clauses))

    total = await session.scalar(select(func.count()).select_from(User).where(*conditions))

    stmt = (
        select(User)
        .where(*conditions)
        # QA M3対応: created_at は同時刻の複数行がありうる単独キーのため、
        # limit/offset のページングで並び順が不定になりうる（行の重複・欠落）。
        # id を tie-breaker として付け、決定的な順序を保証する
        # （admin_list_cases/admin_list_transactions と同型の是正）。
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(limit)
        .offset(offset)
    )
    users = (await session.scalars(stmt)).all()

    # 案件数をバッチ集計する（N+1回避。admin_list_cases の依頼者メール取得と同じ理由。
    # ユーザーごとに個別クエリを発行すると一覧件数分のクエリになってしまう）。
    user_ids = [u.id for u in users]
    case_counts: dict[uuid.UUID, int] = {}
    if user_ids:
        rows = (
            await session.execute(
                select(Case.user_id, func.count(Case.id))
                .where(Case.user_id.in_(user_ids))
                .group_by(Case.user_id)
            )
        ).all()
        case_counts = {uid: cnt for uid, cnt in rows if uid is not None}

    items = [
        AdminUserListItem(
            id=u.id,
            email=u.email,
            display_name=u.name,
            role=u.role,
            is_suspended=u.is_suspended,
            suspended_at=u.suspended_at,
            created_at=u.created_at,
            case_count=case_counts.get(u.id, 0),
        )
        for u in users
    ]

    logger.info(
        "admin: 依頼者一覧を取得しました - count=%d total=%d admin_id=%s", len(items), total or 0, admin.id
    )
    return AdminUserListResponse(items=items, total=int(total or 0))


@router.patch("/admin/users/{user_id}/suspend", response_model=UserSuspendResponse)
async def suspend_user(
    user_id: uuid.UUID,
    body: UserSuspendRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> UserSuspendResponse:
    """依頼者アカウントを停止（suspended=true）／停止解除（false）する（r3-verify-operator ADD-2対応）。

    停止中は ``assert_user_not_suspended``（deps.py）により既存トークンでの全操作が
    403 になり、ログインも拒否される（auth.py の ``user_login`` / ``line_exchange``）。
    admin 自身、および role="admin" のユーザーは対象外（409）とし、運営操作の
    誤ロックアウトを防ぐ（``suspend_operator`` には無い制約だが、admin は user
    テーブルを共用するため依頼者側にのみ必要な安全策）。
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="自分自身のアカウントは停止できません。",
        )
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="管理者アカウントは停止できません。",
        )
    target.is_suspended = body.suspended
    target.suspended_at = datetime.now(timezone.utc) if body.suspended else None
    target.suspended_reason = body.reason if body.suspended else None
    await session.commit()
    await session.refresh(target)

    # QA未解決リスク（依頼者停止後の進行中案件の扱いが未定義）対応: 停止操作自体では
    # 案件・成約の状態には一切干渉しないが、運営が後続対応（案件のキャンセル・
    # 業者への連絡等）を判断できるよう、停止操作時点の open/bidding 案件数を返す
    # （admin_list_cases の active 判定 admin.py:get_cell_density と同じ状態集合）。
    open_case_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Case)
            .where(Case.user_id == target.id, Case.status.in_(("open", "bidding")))
        )
        or 0
    )

    logger.info(
        "admin_user_suspend admin=%s user=%s suspended=%s open_case_count=%d",
        admin.id,
        target.id,
        body.suspended,
        open_case_count,
    )
    return UserSuspendResponse(
        id=target.id,
        is_suspended=target.is_suspended,
        suspended_at=target.suspended_at,
        open_case_count=open_case_count,
    )


async def _has_other_active_admin(session: AsyncSession, exclude_user_id: uuid.UUID) -> bool:
    """``exclude_user_id`` 以外に有効な（``deleted_at IS NULL``）admin が
    1人でも存在すれば True を返す（demote で「最後の1人」判定に使う）。
    """
    other_admin = await session.scalar(
        select(User.id).where(
            User.role == "admin",
            User.deleted_at.is_(None),
            User.id != exclude_user_id,
        ).limit(1)
    )
    return other_admin is not None


@router.post("/admin/users/{user_id}/promote", response_model=AdminUserRoleResponse)
async def promote_user_to_admin(
    user_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminUserRoleResponse:
    """一般ユーザーを admin に昇格させる（R3再レビュー Critical対応）。

    ADMIN_EMAILS 経由の自動昇格（auth.py の ``_promote_to_admin_if_listed``）は
    「DB に有効な admin が1人も居ない場合のみ」に限定したため、既に admin が
    存在する状態での2人目以降の admin 追加は、本エンドポイント（admin 認可必須）
    のみを正規経路とする。対象は ``deleted_at IS NULL``・``is_suspended=False``・
    role="user" であることを要求し、自己（既に admin）への呼び出しは 409 とする。
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="自分自身の権限は変更できません。",
        )
    target = await session.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="停止中のアカウントは昇格できません。",
        )
    if target.role != "user":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="対象は既に admin 権限を持っています。",
        )
    target.role = "admin"
    await session.commit()
    await session.refresh(target)

    logger.warning(
        "admin role granted: email=%s via=%s user_id=%s granted_by=%s",
        target.email,
        "admin_promote",
        target.id,
        admin.id,
    )
    alerts.fire_and_forget(
        alerts.send_alert(
            "admin 権限が付与されました",
            f"email={target.email}\nvia=admin_promote\nuser_id={target.id}\n"
            f"granted_by={admin.id}",
            severity="critical",
            key=f"admin-grant:{target.email}",
        )
    )
    return AdminUserRoleResponse(id=target.id, role=target.role)


@router.post("/admin/users/{user_id}/demote", response_model=AdminUserRoleResponse)
async def demote_admin_to_user(
    user_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminUserRoleResponse:
    """admin を一般ユーザーへ降格させる（R3再レビュー Critical対応）。

    自己降格・最後の1人の admin の降格はいずれも 409 とする（誤操作で
    運営が誰も admin 操作できなくなる自己ロックアウトを防ぐため。
    ``suspend_operator``/``suspend_user`` の「admin は対象外」制約と同系統の
    安全策）。
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="自分自身の権限は変更できません。",
        )
    target = await session.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="対象は admin 権限を持っていません。",
        )
    if not await _has_other_active_admin(session, exclude_user_id=target.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="最後の1人の admin は降格できません。",
        )
    target.role = "user"
    await session.commit()
    await session.refresh(target)

    logger.warning(
        "admin role revoked: email=%s user_id=%s revoked_by=%s",
        target.email,
        target.id,
        admin.id,
    )
    alerts.fire_and_forget(
        alerts.send_alert(
            "admin 権限が剥奪されました",
            f"email={target.email}\nuser_id={target.id}\nrevoked_by={admin.id}",
            severity="critical",
            key=f"admin-revoke:{target.email}",
        )
    )
    return AdminUserRoleResponse(id=target.id, role=target.role)


# ──────────────────────────── 業者事前申込（審査） ────────────────────────────


@router.get("/admin/operator-applications", response_model=list[OperatorApplicationOut])
async def list_operator_applications(
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> list[OperatorApplicationOut]:
    applications = (
        await session.scalars(
            select(OperatorApplication)
            .order_by(OperatorApplication.created_at.desc())
            .limit(limit)
            .offset(offset)
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
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
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
    stmt = stmt.limit(limit).offset(offset)

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
