"""アカウント（マイページ）エンドポイント — プロフィール取得/更新・パスワード変更・退会。

退会（DELETE /users/me）は物理削除ではなく匿名化（論理削除）で実施する。
transactions / messages / reviews は業者側の会計・履歴・レビュー保全のため保持し、
User 行のみ個人情報を匿名化した上で ``deleted_at`` を設定する
（deps.py の失効ゲートにより旧JWTは即時無効化される）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.api.rate_limit_deps import RateLimitGuard
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.case import Case
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    AccountDeleteRequest,
    AccountDeleteResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    UserProfileOut,
    UserProfileUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_profile_out(user: User) -> UserProfileOut:
    return UserProfileOut(
        email=user.email,
        family_name=user.family_name,
        given_name=user.given_name,
        family_name_kana=user.family_name_kana,
        given_name_kana=user.given_name_kana,
        phone=user.phone,
        residence_area=user.residence_area,
        has_password=user.password_hash is not None,
        line_linked=user.line_user_id is not None,
    )


@router.get(
    "/users/me/profile",
    response_model=UserProfileOut,
    summary="プロフィール取得",
)
async def get_my_profile(user: User = Depends(get_current_user)) -> UserProfileOut:
    return _to_profile_out(user)


@router.put(
    "/users/me/profile",
    response_model=UserProfileOut,
    summary="プロフィール更新（name表示用キャッシュを同期更新）",
)
async def update_my_profile(
    body: UserProfileUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserProfileOut:
    user.family_name = body.family_name
    user.given_name = body.given_name
    user.family_name_kana = body.family_name_kana
    user.given_name_kana = body.given_name_kana
    user.phone = body.phone
    user.residence_area = body.residence_area
    # name は表示用キャッシュ。プロフィール更新のたびに氏名から同期する。
    user.name = f"{body.family_name} {body.given_name}"

    await session.commit()
    await session.refresh(user)
    return _to_profile_out(user)


# ──────────────────────────── パスワード変更 ────────────────────────────

_LINE_ONLY_PASSWORD_CHANGE = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="このアカウントはパスワード未設定（LINEログイン専用）のため、パスワード変更はご利用いただけません。",
)
_WRONG_CURRENT_PASSWORD = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="現在のパスワードが正しくありません。",
)


@router.put(
    "/users/me/password",
    response_model=PasswordChangeResponse,
    summary="パスワード変更（成功時は新access_tokenを発行。旧トークンはiatゲートで失効する）",
)
async def change_my_password(
    body: PasswordChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("password_change")),
) -> PasswordChangeResponse:
    ctx = request.state.rate_limit
    account_key = str(user.id)
    ctx.check_account(account_key)

    if user.password_hash is None:
        raise _LINE_ONLY_PASSWORD_CHANGE
    if not verify_password(body.current_password, user.password_hash):
        ctx.record_failure(account_key)
        raise _WRONG_CURRENT_PASSWORD
    ctx.reset_account(account_key)

    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(user)

    # 旧トークンは iat < password_changed_at で deps.py のゲートにより失効するため、
    # クライアントが継続利用できるよう新トークンをここで発行する。
    token = create_access_token(user.id, "user", user.role)
    return PasswordChangeResponse(detail="パスワードを変更しました。", access_token=token)


# ──────────────────────────── アカウント削除（退会） ────────────────────────────

_DELETE_CONFIRM_REQUIRED = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="削除の確認が必要です。",
)
_DELETE_WRONG_PASSWORD = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="パスワードが正しくありません。",
)
_DELETE_ACTIVE_TRANSACTION = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="進行中のお取引があります。お取引の完了またはキャンセル後に、あらためて退会手続きをお願いします。",
)
# 取引未成立のまま宙に浮いた案件を退会時にキャンセル化するための非終端ステータス一覧。
_NON_TERMINAL_CASE_STATUSES = ("draft", "open", "bidding")


@router.delete(
    "/users/me",
    response_model=AccountDeleteResponse,
    summary="アカウント削除（匿名化。取引・メッセージ・レビューは業者側の記録として保持）",
)
async def delete_my_account(
    body: AccountDeleteRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("account_delete")),
) -> AccountDeleteResponse:
    ctx = request.state.rate_limit
    account_key = str(user.id)
    ctx.check_account(account_key)

    if not body.confirm:
        raise _DELETE_CONFIRM_REQUIRED

    # LINE専用ユーザー（password_hash=None）はパスワード確認不要。
    if user.password_hash is not None:
        if not body.password or not verify_password(body.password, user.password_hash):
            ctx.record_failure(account_key)
            raise _DELETE_WRONG_PASSWORD
        ctx.reset_account(account_key)

    active_txn_count = await session.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Case, Transaction.case_id == Case.id)
        .where(Case.user_id == user.id, Transaction.status.in_(("pending", "visiting")))
    )
    if active_txn_count:
        raise _DELETE_ACTIVE_TRANSACTION

    cases = (
        await session.scalars(
            select(Case).where(Case.user_id == user.id).options(selectinload(Case.transaction))
        )
    ).all()
    for case in cases:
        txn = case.transaction
        if txn is None and case.status in _NON_TERMINAL_CASE_STATUSES:
            case.status = "cancelled"
        # 完了済み取引に紐づく案件のみ住所詳細を保持する（業者側の完了記録の整合性維持）。
        # それ以外（取引なし／キャンセル済み取引）は居住地PIIを退会時に除去する。
        if txn is None or txn.status != "completed":
            case.address_detail = None

    user.email = f"deleted-{user.id}@deleted.katazuke.internal"
    user.name = None
    user.family_name = None
    user.given_name = None
    user.family_name_kana = None
    user.given_name_kana = None
    user.phone = None
    user.residence_area = None
    user.line_user_id = None
    user.password_hash = None
    user.deleted_at = datetime.now(timezone.utc)

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "users/me delete: 退会処理のコミットに失敗 - user_id=%s - %s",
            user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="退会処理に失敗しました。時間をおいて再度お試しください。",
        ) from exc

    return AccountDeleteResponse(detail="退会手続きが完了しました。")
