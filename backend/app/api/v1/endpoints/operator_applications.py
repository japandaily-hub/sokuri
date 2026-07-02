"""業者事前申込エンドポイント — 公開 POST /operator-applications（/business フォーム本配線）。

全業者は admin 承認必須（招待コードありでも即active化はしない）。本エンドポイントは
認証不要で、申込内容を operator_applications テーブルに status="received" で保存する。

振込先口座は平文で受け取るが、DB保存直前に暗号化する（app.core.crypto.encrypt_json）。
ログには口座情報の平文を絶対に出力しない。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_json
from app.core.request_ip import get_client_ip
from app.db.models.operator_application import OperatorApplication
from app.db.session import get_session
from app.schemas_katadzuke import (
    CURRENT_OPERATOR_TERMS_VERSION,
    OperatorApplicationCreateRequest,
    OperatorApplicationCreateResponse,
)
from app.config import get_settings
from app.services import notify

logger = logging.getLogger(__name__)

router = APIRouter()

# ── レート制限・スパム対策（security review Critical指摘対応） ──────────────
# 認証不要の公開エンドポイントのため、DB肥大化・暗号化コスト増幅・
# 第三者へのメール爆撃（contact_email に任意アドレスを指定して送信させる）を防ぐ。
# 新規インフラ（Redis等）は導入せず、既存テーブルの created_at のみで判定する。

# 同一IPからの申込は1時間あたりこの件数まで許容する。
_RATE_LIMIT_MAX_PER_IP_PER_WINDOW = 5
_RATE_LIMIT_WINDOW = timedelta(hours=1)

# 同一 contact_email 宛の受付確認メールは、直近この期間内に送信済みなら再送しない
# （メール爆撃対策。申込自体は保存する＝正規ユーザーの再申込を拒否しない）。
_EMAIL_NOTIFY_THROTTLE_WINDOW = timedelta(hours=1)


@router.post(
    "/operator-applications",
    response_model=OperatorApplicationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="業者事前申込（公開・認証不要。/business フォームの送信先）",
)
async def create_operator_application(
    request: Request,
    body: OperatorApplicationCreateRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> OperatorApplicationCreateResponse:
    if not body.agreed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="利用規約・プライバシーポリシーへの同意が必要です。",
        )

    client_ip = get_client_ip(request)
    now = datetime.now(timezone.utc)
    window_start = now - _RATE_LIMIT_WINDOW

    # ── レート制限（IPアドレス単位） ────────────────────────────────
    # client_ip が取得できない（テスト環境等）場合は判定をスキップする
    # （取得不能を理由に正規リクエストを一律ブロックしない。可用性目的の対策のため）。
    if client_ip is not None:
        recent_count_from_ip = await session.scalar(
            select(func.count())
            .select_from(OperatorApplication)
            .where(
                OperatorApplication.client_ip == client_ip,
                OperatorApplication.created_at >= window_start,
            )
        )
        if (recent_count_from_ip or 0) >= _RATE_LIMIT_MAX_PER_IP_PER_WINDOW:
            logger.warning(
                "operator_applications: レート制限超過 - client_ip=%s count=%s",
                client_ip,
                recent_count_from_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="送信回数の上限に達しました。しばらく時間をおいて再度お試しください。",
            )

    # 口座情報は保存直前に暗号化する。平文はここで使い切り、以降ログ・変数に残さない。
    bank_account_enc = encrypt_json(body.bank_account.model_dump())

    contact_email = body.email.lower()

    # ── 受付確認メールのスロットル判定（メール爆撃対策） ────────────────
    # 申込自体は常に保存する。メール送信のみ「直近に同一emailへ送信済みなら送らない」。
    email_notify_window_start = now - _EMAIL_NOTIFY_THROTTLE_WINDOW
    recent_application_to_same_email = await session.scalar(
        select(func.count())
        .select_from(OperatorApplication)
        .where(
            OperatorApplication.contact_email == contact_email,
            OperatorApplication.created_at >= email_notify_window_start,
        )
    )
    should_send_received_email = (recent_application_to_same_email or 0) == 0

    application = OperatorApplication(
        status="received",
        company_name=body.company_name,
        representative_name=body.representative_name,
        registered_address=body.registered_address,
        contact_name=body.contact_name,
        contact_email=contact_email,
        contact_phone=body.phone,
        license_number=body.license_number,
        business_type=body.business_type,
        service_area=body.service_area,
        categories=body.categories,
        message=body.message,
        invoice_number=body.invoice_number,
        bank_account_enc=bank_account_enc,
        agreed_terms_version=CURRENT_OPERATOR_TERMS_VERSION,
        agreed_at=datetime.now(timezone.utc),
        client_ip=client_ip,
    )
    session.add(application)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "operator_applications: 申込の保存に失敗しました - company=%s email=%s - %s",
            body.company_name,
            body.email,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="申込の保存に失敗しました。時間をおいて再度お試しください。",
        ) from exc
    await session.refresh(application)

    if should_send_received_email:
        background.add_task(
            notify.send_operator_application_received,
            application.contact_email,
            application.company_name,
        )
    else:
        logger.info(
            "operator_applications: 直近%s以内に同一emailへ受付確認済みのため送信をスキップ - id=%s",
            _EMAIL_NOTIFY_THROTTLE_WINDOW,
            application.id,
        )
    for admin_email in get_settings().admin_emails:
        background.add_task(
            notify.send_operator_application_admin_alert, admin_email, application.company_name
        )

    logger.info(
        "operator_applications: 新規申込を受け付けました - id=%s company=%s",
        application.id,
        application.company_name,
    )
    return OperatorApplicationCreateResponse(
        application_id=application.id, status=application.status
    )
