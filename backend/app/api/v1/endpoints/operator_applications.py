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

from app.api.json_body_deps import require_json_body
from app.api.rate_limit_deps import RateLimitGuard
from app.core.client_ip import (
    is_private_or_loopback,
    is_skippable_special_use_address,
    resolve_client_ip_with_reason,
)
from app.core.crypto import encrypt_json
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
# 同一IPからの申込数は RateLimitGuard("operator_application")（IP軸・全リクエスト
# カウント・1時間5件）で絞る。以前はここで X-Forwarded-For の先頭（利用者が自由に
# 書ける値）を使って client_ip の件数を DB で数えていたため、ヘッダを付け替える
# だけで制限を回避でき、記録される IP も偽の値になっていた。IP の解決は他の
# レート制限と同じ正本（app.core.client_ip.resolve_client_ip_with_reason）に揃える。

# 同一 contact_email 宛の受付確認メールは、直近この期間内に送信済みなら再送しない
# （メール爆撃対策。申込自体は保存する＝正規ユーザーの再申込を拒否しない）。
_EMAIL_NOTIFY_THROTTLE_WINDOW = timedelta(hours=1)

# operator_applications.client_ip の列長（String(64)）。正規化済みの IP は IPv6 でも
# 39 文字に収まるが、IPv6 のゾーン ID（"%" 以降）は長さに上限なく受理されるため、
# 列に収まらない値は記録しない（PostgreSQL では超過すると保存そのものが失敗する）。
_CLIENT_IP_MAX_LENGTH = OperatorApplication.client_ip.type.length


def _client_ip_for_record(request: Request) -> str | None:
    """申込に記録する送信元 IP を、レート制限と同じ正本の解決で求める。

    記録するのは ``RateLimitGuard`` が IP 軸で数えるのと同じ値だけにする。
    プライベート/ループバック・特殊用途のアドレス（TRUSTED_PROXY_HOPS の誤設定等で
    内部プロキシの IP を掴んでいる状態。ガードは数えずにスキップする）は、
    別々の申込者が同じ IP として並び追跡を誤らせるため記録しない。解決できない場合と
    列に収まらない場合も ``None``（記録なし）。

    判定（不正な X-Forwarded-For の 400・上限超過の 429）はガードの責務で、本関数は
    記録専用。ガードとは別に解決し直す（1リクエスト2回・文字列処理のみ）のは、
    緊急停止スイッチ（RATE_LIMIT_ENABLED=false）中はガードが IP を解決しないため。
    ここで 400 を返さないのも、停止中にガードが素通しになる挙動を記録のために変えないため。
    """
    ip = resolve_client_ip_with_reason(request, get_settings().trusted_proxy_hops).ip
    if (
        ip is None
        or is_private_or_loopback(ip)
        or is_skippable_special_use_address(ip)
        or len(ip) > _CLIENT_IP_MAX_LENGTH
    ):
        return None
    return ip


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
    # 依存は宣言順に実行される。JSON 以外の本文はカウントより前に 415 で止める
    # （第三者のページから訪問者の IP の枠を使い切らせないため。require_json_body 参照）。
    _json_only: None = Depends(require_json_body),
    # 同一IPからの申込数の制限（IP軸・全リクエストカウント・1時間5件）。ハンドラ本体
    # より前に判定・カウントされ、上限超過なら 429、解決できない X-Forwarded-For
    # なら 400 で止まる（_scope_spec の "operator_application" 分岐を参照）。
    _rl: object = Depends(RateLimitGuard("operator_application")),
) -> OperatorApplicationCreateResponse:
    if not body.agreed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="利用規約・プライバシーポリシーへの同意が必要です。",
        )

    client_ip = _client_ip_for_record(request)
    now = datetime.now(timezone.utc)

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
