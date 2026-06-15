"""案件エンドポイント — 作成 / 一覧 / 詳細。

住所詳細（address_detail）の開示制御（品質基準）:
- 所有ユーザー: CaseOut（住所詳細あり）
- 業者:        CaseMaskedOut（prefecture / city のみ。詳細は落札後に
               GET /transactions/{id} で開示する）
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Actor, get_current_actor, get_current_user
from app.db.models.bid import Bid
from app.db.models.case import Case, CasePhoto
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    BidOut,
    CaseCreateRequest,
    CaseMaskedOut,
    CaseOut,
    CasePhotoOut,
)
from app.services import notify, storage
from app.services.summary import generate_case_summary, photo_url_for_ai

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_case_out(case: Case) -> CaseOut:
    out = CaseOut.model_validate(case)
    out.bid_count = len(case.bids)
    return out


def _to_masked_out(case: Case, my_operator_id: uuid.UUID | None = None) -> CaseMaskedOut:
    my_bid = None
    if my_operator_id is not None:
        for bid in case.bids:
            if bid.operator_id == my_operator_id:
                my_bid = BidOut.model_validate(bid)
                if bid.status == "selected" and bid.transaction is not None:
                    my_bid.transaction_id = bid.transaction.id
                break
    return CaseMaskedOut(
        id=case.id,
        status=case.status,
        purpose=case.purpose,
        prefecture=case.prefecture,
        city=case.city,
        housing_type=case.housing_type,
        floor_plan=case.floor_plan,
        floor_number=case.floor_number,
        has_elevator=case.has_elevator,
        ai_summary=case.ai_summary,
        created_at=case.created_at,
        photos=[CasePhotoOut.model_validate(p) for p in case.photos],
        bid_count=len(case.bids),
        my_bid=my_bid,
    )


_CASE_LOAD = (
    selectinload(Case.photos),
    selectinload(Case.bids).selectinload(Bid.operator),
    selectinload(Case.bids).selectinload(Bid.transaction),
)


async def _get_case(session: AsyncSession, case_id: uuid.UUID) -> Case:
    case = await session.scalar(
        select(Case).where(Case.id == case_id).options(*_CASE_LOAD)
    )
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="案件が見つかりません。"
        )
    return case


@router.post(
    "/cases",
    response_model=CaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="案件作成（写真 + 住居情報 + AI 要約）",
)
async def create_case(
    body: CaseCreateRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CaseOut:
    case = Case(
        user_id=user.id,
        purpose=body.purpose,
        status="open",
        prefecture=body.prefecture,
        city=body.city,
        address_detail=body.address_detail,
        housing_type=body.housing_type,
        floor_plan=body.floor_plan,
        floor_number=body.floor_number,
        has_elevator=body.has_elevator,
    )
    for photo_in in body.photos:
        if not storage.is_valid_key(photo_in.storage_key):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="storage_key が不正です。presign からやり直してください。",
            )
        case.photos.append(
            CasePhoto(
                storage_key=photo_in.storage_key,
                url=storage.public_url(photo_in.storage_key),
                sort_order=photo_in.sort_order,
            )
        )

    ai_refs = [
        ref
        for p in case.photos
        if (ref := photo_url_for_ai(p.storage_key, p.url)) is not None
    ]
    try:
        case.ai_summary = await generate_case_summary(
            purpose=case.purpose,
            housing_type=case.housing_type,
            floor_plan=case.floor_plan,
            photo_urls=ai_refs,
        )
    except Exception as exc:
        logger.error("cases: AI サマリー生成に失敗（フォールバック） - %s", exc)
        case.ai_summary = f"利用目的: {case.purpose}。写真 {len(case.photos)} 枚。"

    session.add(case)
    await session.commit()
    await session.refresh(case, attribute_names=["photos", "bids"])

    background.add_task(notify.send_case_created, user.email, str(case.id))
    return _to_case_out(case)


@router.get(
    "/cases",
    summary="案件一覧（ユーザー: 自分の案件 / 業者: 入札可能案件）",
)
async def list_cases(
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> list[CaseOut] | list[CaseMaskedOut]:
    if actor.typ == "user":
        assert actor.user is not None
        cases = (
            await session.scalars(
                select(Case)
                .where(Case.user_id == actor.user.id)
                .options(*_CASE_LOAD)
                .order_by(Case.created_at.desc())
            )
        ).all()
        return [_to_case_out(c) for c in cases]

    assert actor.operator is not None
    _op = actor.operator
    if not (_op.vendor_status in ("limited", "active") or _op.verified_at is not None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントの登録承認が完了していません。承認後に案件を閲覧できます。",
        )
    cases = (
        await session.scalars(
            select(Case)
            .where(Case.status.in_(["open", "bidding"]))
            .options(*_CASE_LOAD)
            .order_by(Case.created_at.desc())
        )
    ).all()
    return [_to_masked_out(c, actor.operator.id) for c in cases]


@router.get(
    "/cases/{case_id}",
    summary="案件詳細（業者には住所詳細をマスク）",
)
async def get_case(
    case_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_session),
) -> CaseOut | CaseMaskedOut:
    case = await _get_case(session, case_id)

    if actor.typ == "user":
        assert actor.user is not None
        if case.user_id != actor.user.id and actor.user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="この案件への権限がありません。"
            )
        return _to_case_out(case)

    assert actor.operator is not None
    _op = actor.operator
    if not (_op.vendor_status in ("limited", "active") or _op.verified_at is not None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントの登録承認が完了していません。",
        )
    return _to_masked_out(case, actor.operator.id)
