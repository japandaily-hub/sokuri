"""パスワード再設定エンドポイント（無認証）— 依頼者・業者共通。

- ``POST /auth/password-reset/request``: 常に同じ 202。アカウントの照会・トークン発行・
  メール送信は応答後のバックグラウンド処理（``services.password_reset.process_reset_request``）。
- ``POST /auth/password-reset/confirm``: 1回限りトークンで新しいパスワードを設定し、
  既存のログインを失効させる。失敗（無効・期限切れ・使用済み・種別違い）は一律の 400。

どちらも JSON 以外の本文はカウントより前に 415 で止め（``require_json_body``。第三者の
ページから訪問者の IP の枠を使い切らせない＝CSRF 的な悪用の防止）、IP 軸の全リクエスト
カウント（``RateLimitGuard``）で連打を止める。認証は Cookie ではなく本文のトークンだけで、
ブラウザが自動で付ける資格情報に依存しない。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.json_body_deps import require_json_body
from app.api.rate_limit_deps import RateLimitGuard
from app.core.http_errors import http_exception_factory
from app.db.session import get_session
from app.schemas_katadzuke import (
    PasswordResetAcceptedResponse,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
)
from app.services import password_reset as password_reset_service

logger = logging.getLogger(__name__)

router = APIRouter()

#: 要求の応答文言（登録の有無にかかわらず同一。web の表示もこの意味に揃える）。
PASSWORD_RESET_ACCEPTED_DETAIL = (
    "入力されたアドレスが登録されている場合は、再設定の案内を送りました。"
    "メールが届かない場合は、迷惑メールフォルダもご確認ください。"
)
#: 確定の失敗文言（理由を区別しない）。
_INVALID_RESET_TOKEN = http_exception_factory(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail={
        "code": "password_reset_invalid",
        "message": (
            "再設定のリンクが無効か、有効期限が切れています。"
            "お手数ですが、もう一度パスワード再設定の手続きをしてください。"
        ),
    },
)


@router.post(
    "/auth/password-reset/request",
    response_model=PasswordResetAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="パスワード再設定の要求（登録の有無にかかわらず常に同じ 202）",
)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    background: BackgroundTasks,
    # 依存は宣言順に実行される。JSON 以外の本文はカウントより前に 415 で止める。
    _json_only: None = Depends(require_json_body),
    _rl: object = Depends(RateLimitGuard("password_reset_request")),
) -> PasswordResetAcceptedResponse:
    email = body.email.lower()
    # アカウント軸（同じアドレス宛の案内の連打防止）。識別子は種別で名前空間分離し、
    # 実在しないアドレスでも同じに数える（429 の有無から登録の有無は分からない）。
    request.state.rate_limit.hit_account(f"{body.account_type}:{email}")
    # 照会・発行・送信は応答の後に行う（登録の有無で応答時間が変わらないようにする）。
    background.add_task(password_reset_service.process_reset_request, body.account_type, email)
    return PasswordResetAcceptedResponse(detail=PASSWORD_RESET_ACCEPTED_DETAIL)


@router.post(
    "/auth/password-reset/confirm",
    response_model=PasswordResetConfirmResponse,
    summary="パスワード再設定の確定（1回限りトークン。成功時は既存のログインを失効させる）",
)
async def confirm_password_reset(
    body: PasswordResetConfirmRequest,
    session: AsyncSession = Depends(get_session),
    _json_only: None = Depends(require_json_body),
    _rl: object = Depends(RateLimitGuard("password_reset_confirm")),
) -> PasswordResetConfirmResponse:
    now = datetime.now(timezone.utc)
    account_id = await password_reset_service.consume_reset_token(
        session, body.account_type, body.token, now
    )
    if account_id is None:
        await session.rollback()
        logger.info(
            "password_reset: 無効なトークンでの確定を拒否しました（type=%s）", body.account_type
        )
        raise _INVALID_RESET_TOKEN()

    applied = await password_reset_service.apply_new_password(
        session, body.account_type, account_id, body.new_password, now
    )
    if not applied:
        # トークンは使用済みのまま確定させる（退会・停止したアカウントの再試行を止める）。
        await session.commit()
        logger.warning(
            "password_reset: 再設定できない状態のアカウントのため拒否しました"
            "（type=%s account_id=%s）",
            body.account_type,
            account_id,
        )
        raise _INVALID_RESET_TOKEN()

    await session.commit()
    logger.info(
        "password_reset: パスワードを再設定し、既存のログインを失効させました（type=%s account_id=%s）",
        body.account_type,
        account_id,
    )
    return PasswordResetConfirmResponse(
        detail="パスワードを再設定しました。新しいパスワードでログインしてください。"
    )
