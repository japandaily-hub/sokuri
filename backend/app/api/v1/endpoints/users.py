"""アカウント（マイページ）エンドポイント — プロフィール取得/更新・パスワード変更・退会。

退会（DELETE /users/me）は物理削除ではなく匿名化（論理削除）で実施する。
transactions / messages / reviews は業者側の会計・履歴・レビュー保全のため保持し、
User 行のみ個人情報を匿名化した上で ``deleted_at`` を設定する
（deps.py の失効ゲートにより旧JWTは即時無効化される）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_current_user_claims
from app.api.rate_limit_deps import RateLimitGuard
from app.core.crypto import DecryptionFailedError, decrypt_json, encrypt_json
from app.core.masking import mask_account_number
from app.core.security import (
    REAUTH_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_reauth_token,
    hash_password,
    verify_password,
)
from app.db.models.bid import BID_STATUS_PENDING, BID_STATUS_REJECTED, Bid
from app.db.models.case import Case
from app.db.models.contact_message import ContactMessage
from app.db.models.transaction import Cancellation, Transaction
from app.db.models.user import User
from app.db.models.user_identity_document import UserIdentityDocument
from app.db.session import get_session
from app.schemas_katadzuke import (
    AccountDeleteRequest,
    AccountDeleteResponse,
    LineLinkUnlinkRequest,
    PasswordChangeRequest,
    PasswordChangeResponse,
    ReauthTokenRequest,
    ReauthTokenResponse,
    UserAddressOut,
    UserAddressUpdateRequest,
    UserBankAccountDeleteRequest,
    UserBankAccountMaskedOut,
    UserBankAccountUpdateRequest,
    UserProfileOut,
    UserProfileUpdateRequest,
    prefecture_to_residence_area,
)
from app.services import notify, notify_dispatch
from app.services.case_lock import lock_case_row

logger = logging.getLogger(__name__)

router = APIRouter()

# 「現在のパスワードが正しくありません。」は password/reauth/bank-account/line-link/
# 退会など複数のエンドポイントで共有する（文言統一のため一箇所にまとめる）。
_WRONG_CURRENT_PASSWORD = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="現在のパスワードが正しくありません。",
)


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
        birth_date=user.birth_date,
        occupation=user.occupation,
        identity_status=user.identity_status,
        has_bank_account=user.bank_account_enc is not None,
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
    """プロフィール更新。

    ``residence_area`` は本来 /users/me/address の ``prefecture`` から自動導出
    される値であり（``prefecture_to_residence_area``）、このエンドポイントの
    ``body.residence_area`` は住所未登録ユーザー向けの後方互換入力にすぎない。
    住所が既に登録済み（``user.prefecture`` あり）のユーザーについてまで
    body 側の値で上書きを許すと、都道府県と居住エリア表示が食い違う（QA M-1）。
    そのため住所登録済みなら常に prefecture 由来の値を維持し、body は無視する。
    """
    user.family_name = body.family_name
    user.given_name = body.given_name
    user.family_name_kana = body.family_name_kana
    user.given_name_kana = body.given_name_kana
    user.phone = body.phone
    if user.prefecture is not None:
        user.residence_area = prefecture_to_residence_area(user.prefecture)
    else:
        user.residence_area = body.residence_area
    user.birth_date = body.birth_date
    user.occupation = body.occupation
    # name は表示用キャッシュ。プロフィール更新のたびに氏名から同期する。
    user.name = f"{body.family_name} {body.given_name}"

    await session.commit()
    await session.refresh(user)
    return _to_profile_out(user)


# ──────────────────────────── 住所 ────────────────────────────


@router.get(
    "/users/me/address",
    response_model=UserAddressOut,
    summary="住所取得（未登録は各項目null）",
)
async def get_my_address(user: User = Depends(get_current_user)) -> UserAddressOut:
    return UserAddressOut(
        postal_code=user.postal_code,
        prefecture=user.prefecture,
        city=user.city,
        address_line1=user.address_line1,
        address_line2=user.address_line2,
        residence_area=user.residence_area,
    )


@router.put(
    "/users/me/address",
    response_model=UserAddressOut,
    summary="住所更新（residence_areaを都道府県から自動同期）",
)
async def update_my_address(
    body: UserAddressUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserAddressOut:
    user.postal_code = body.postal_code
    user.prefecture = body.prefecture
    user.city = body.city
    user.address_line1 = body.address_line1
    user.address_line2 = body.address_line2
    user.residence_area = prefecture_to_residence_area(body.prefecture)

    await session.commit()
    await session.refresh(user)
    return UserAddressOut(
        postal_code=user.postal_code,
        prefecture=user.prefecture,
        city=user.city,
        address_line1=user.address_line1,
        address_line2=user.address_line2,
        residence_area=user.residence_area,
    )


# ──────────────────────────── 振込先口座 ────────────────────────────


def _to_bank_account_masked_out(user: User) -> UserBankAccountMaskedOut:
    """暗号化済み口座情報を復号し、下4桁マスクのみのレスポンスへ変換する。

    復号失敗（鍵不一致・改ざん）はユーザーに詳細を返さず、未登録として扱う
    （呼び出し元でエラーログを出す。admin の reveal 系とは異なりユーザー自身が
    見る画面のため、復号エラーの詳細を露出させない）。
    """
    if not user.bank_account_enc:
        return UserBankAccountMaskedOut(has_bank_account=False)
    try:
        decrypted = decrypt_json(user.bank_account_enc)
    except DecryptionFailedError as exc:
        logger.error(
            "users/me/bank-account: 口座情報の復号に失敗 - user_id=%s - %s",
            user.id,
            exc,
        )
        return UserBankAccountMaskedOut(has_bank_account=False)
    return UserBankAccountMaskedOut(
        has_bank_account=True,
        bank_name=decrypted["bank_name"],
        branch_name=decrypted["branch_name"],
        account_type=decrypted["account_type"],
        account_number_masked=mask_account_number(decrypted["account_number"]),
        account_holder_kana=decrypted["account_holder_kana"],
        updated_at=user.bank_account_updated_at,
    )


@router.get(
    "/users/me/bank-account",
    response_model=UserBankAccountMaskedOut,
    summary="振込先口座取得（下4桁マスクのみ。未登録は has_bank_account=false）",
)
async def get_my_bank_account(user: User = Depends(get_current_user)) -> UserBankAccountMaskedOut:
    return _to_bank_account_masked_out(user)


_BANK_ACCOUNT_CURRENT_PASSWORD_REQUIRED = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="現在のパスワードを入力してください。",
)


# LINE専用ユーザーの step-up 判定に用いる「直近ログイン」の許容時間（秒）。
_BANK_ACCOUNT_RECENT_LOGIN_MAX_AGE_SEC = 10 * 60

_BANK_ACCOUNT_RELOGIN_REQUIRED = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail=(
        "振込先口座の変更には本人確認のため再ログインが必要です。"
        "一度ログアウトし、LINEで再度ログインしてから操作してください。"
    ),
)


def _verify_bank_account_reauth(
    user: User, current_password: str | None, token_iat: int | float | None
) -> None:
    """振込口座の変更・削除の直前に呼ぶ再認証チェック（security review H-1 / 再レビュー A）。

    - パスワード設定済みユーザー: current_password の一致を必須とする
      （口座の乗っ取り書き換え＝金銭の流出先変更に直結するため）。
    - LINEログイン専用ユーザー（``password_hash`` が None）: パスワードによる
      再認証手段が無いため、代わりに **直近 10 分以内に発行された JWT** のみ許可する。
      これにより、窃取された古いトークンでは口座を書き換えられず、攻撃者は LINE
      で再ログイン（＝本人の LINE アカウント）を要求される。フロントは 403 を受けたら
      再ログインを案内する。
    """
    if user.password_hash is None:
        now_ts = datetime.now(timezone.utc).timestamp()
        if (
            token_iat is None
            or now_ts - float(token_iat) > _BANK_ACCOUNT_RECENT_LOGIN_MAX_AGE_SEC
        ):
            raise _BANK_ACCOUNT_RELOGIN_REQUIRED
        return
    if not current_password:
        raise _BANK_ACCOUNT_CURRENT_PASSWORD_REQUIRED
    if not verify_password(current_password, user.password_hash):
        raise _WRONG_CURRENT_PASSWORD


@router.put(
    "/users/me/bank-account",
    response_model=UserBankAccountMaskedOut,
    summary="振込先口座登録・更新（保存直前に暗号化。平文はDB・ログに残さない。current_password必須）",
)
async def update_my_bank_account(
    body: UserBankAccountUpdateRequest,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("bank_account_update")),
) -> UserBankAccountMaskedOut:
    request.state.rate_limit.hit_account(str(user.id))
    _verify_bank_account_reauth(user, body.current_password, claims.get("iat"))

    is_new_registration = user.bank_account_enc is None
    user.bank_account_enc = encrypt_json(
        {
            "bank_name": body.bank_name,
            "branch_name": body.branch_name,
            "account_type": body.account_type,
            "account_number": body.account_number,
            "account_holder_kana": body.account_holder_kana,
        }
    )
    user.bank_account_updated_at = datetime.now(timezone.utc)

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "users/me/bank-account PUT: 保存に失敗 - user_id=%s - %s",
            user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="振込先口座の保存に失敗しました。時間をおいて再度お試しください。",
        ) from exc
    await session.refresh(user)

    # 口座の登録・変更を本人へ通知する（security review M-1・不正な書き換えの早期検知）。
    # LINE 連携済みなら LINE Push、実メールがあればメールも送る（両方。セキュリティ通知の
    # ため片方に絞らない）。本文に口座番号は含めない。
    action = "登録" if is_new_registration else "変更"
    background.add_task(
        notify_dispatch.dispatch_bank_account_changed, user.line_user_id, user.email, action
    )
    return _to_bank_account_masked_out(user)


@router.delete(
    "/users/me/bank-account",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="振込先口座削除（current_password必須。レート制限・監査ログあり）",
)
async def delete_my_bank_account(
    body: UserBankAccountDeleteRequest,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("bank_account_update")),
) -> None:
    request.state.rate_limit.hit_account(str(user.id))
    _verify_bank_account_reauth(user, body.current_password, claims.get("iat"))

    user.bank_account_enc = None
    user.bank_account_updated_at = None

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "users/me/bank-account DELETE: 削除に失敗 - user_id=%s - %s",
            user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="振込先口座の削除に失敗しました。時間をおいて再度お試しください。",
        ) from exc

    logger.info("users/me/bank-account DELETE: 振込先口座を削除しました - user_id=%s", user.id)
    background.add_task(
        notify_dispatch.dispatch_bank_account_changed, user.line_user_id, user.email, "削除"
    )


# ──────────────────────────── パスワード変更 ────────────────────────────

_LINE_ONLY_PASSWORD_CHANGE = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="このアカウントはパスワード未設定（LINEログイン専用）のため、パスワード変更はご利用いただけません。",
)
# _WRONG_CURRENT_PASSWORD はファイル冒頭で定義済み（bank-account 等と共有）。


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


# ──────────────────────────── LINE連携（再認証トークン・連携解除） ────────────────────────────

_REAUTH_LINE_ONLY = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="このアカウントはパスワード未設定（LINEログイン専用）のため、この操作はご利用いただけません。",
)
_REAUTH_WRONG_PASSWORD = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="現在のパスワードが正しくありません。",
)


@router.post(
    "/users/me/reauth-token",
    response_model=ReauthTokenResponse,
    summary="LINE連携用の短命再認証トークンを発行する（purpose=line_link・5分間有効）",
)
async def issue_reauth_token(
    body: ReauthTokenRequest,
    request: Request,
    user: User = Depends(get_current_user),
    _rl: object = Depends(RateLimitGuard("line_link_reauth")),
) -> ReauthTokenResponse:
    ctx = request.state.rate_limit
    account_key = str(user.id)
    ctx.check_account(account_key)

    # LINE専用ユーザー（password_hash=None）はパスワードによる再認証手段が無い。
    if user.password_hash is None:
        raise _REAUTH_LINE_ONLY
    if not verify_password(body.current_password, user.password_hash):
        ctx.record_failure(account_key)
        raise _REAUTH_WRONG_PASSWORD
    ctx.reset_account(account_key)

    token = create_reauth_token(user.id, "user")
    return ReauthTokenResponse(
        reauth_token=token, expires_in=REAUTH_TOKEN_EXPIRE_MINUTES * 60
    )


_LINE_UNLINK_NO_PASSWORD = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="パスワード未設定のためLINE連携を解除できません（ログイン手段が失われるため）。",
)
_LINE_UNLINK_WRONG_PASSWORD = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="現在のパスワードが正しくありません。",
)


@router.delete(
    "/users/me/line-link",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="LINE連携の解除（current_password必須。解除するとログイン手段が消滅するため未設定ユーザーは409）",
)
async def unlink_line(
    body: LineLinkUnlinkRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("line_link_reauth")),
) -> None:
    ctx = request.state.rate_limit
    account_key = str(user.id)
    ctx.check_account(account_key)

    # LINE専用ユーザー（password_hash=None）が解除するとログイン手段が完全に
    # 消滅するため、パスワード未設定のうちは解除自体を許可しない。
    if user.password_hash is None:
        raise _LINE_UNLINK_NO_PASSWORD
    if not verify_password(body.current_password, user.password_hash):
        ctx.record_failure(account_key)
        raise _LINE_UNLINK_WRONG_PASSWORD
    ctx.reset_account(account_key)

    user.line_user_id = None
    await session.commit()


# ──────────────────────────── アカウント削除（退会） ────────────────────────────

_DELETE_CONFIRM_REQUIRED = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="削除の確認が必要です。",
)
# 退会（＝復旧不能な破壊的操作）の再認証失敗のみ 403 に統一する（r8-verify-fix の
# 契約非対称の是正）。業者退会（operator_profile._OPERATOR_DELETE_WRONG_PASSWORD）と
# 同一の status・同一の文言にし、web は「パスワードが正しくありません」を出す。
# パスワード変更・reauth-token・bank-account・line-link の再認証失敗は従来どおり
# 400（_WRONG_CURRENT_PASSWORD 系）— こちらは user 側・operator 側で既に対称であり、
# 退会だけを 403 に分離することで「不可逆操作か否か」を status で区別できる。
_DELETE_WRONG_PASSWORD = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="パスワードが正しくありません。",
)
_DELETE_ACTIVE_TRANSACTION = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="進行中のお取引があります。お取引の完了またはキャンセル後に、あらためて退会手続きをお願いします。",
)
# 取引未成立のまま宙に浮いた案件を退会時にキャンセル化するための非終端ステータス一覧。
_NON_TERMINAL_CASE_STATUSES = ("draft", "open", "bidding")
# うち「公開済み＝業者から入札が付きうる」ステータス。cases.cancel_case が
# 取り下げを許可する範囲と同一（draft は同関数が409で弾くため含めない）。
_CANCELLABLE_CASE_STATUSES = ("open", "bidding")
_WITHDRAWAL_CANCEL_REASON = "依頼者の退会に伴う自動取り下げ"

# 落選通知1件ぶんのプリミティブ値（line_user_id, email, case_id, prefecture, city, purpose）。
# BackgroundTasks へ ORM オブジェクトを渡さない既存規約に従うため tuple で持ち回す。
_LostBidNotification = tuple[str | None, str, str, str, str, str]


async def _cancel_open_case_on_withdrawal(
    session: AsyncSession, case: Case, notifications: list[_LostBidNotification]
) -> None:
    """退会に伴う open/bidding 案件の暗黙キャンセル（cases.cancel_case と同じ手順）。

    退会経路は従来 ``case.status = "cancelled"`` の直接代入だけで、
    ①pending入札の一括却下 ②Cancellation（監査証跡）の記録 ③落選業者への通知
    の3点を欠いていた。その結果、案件が cancelled でも Bid が pending のまま
    永久に残り、入札した業者には何も通知されなかった（r6-flow H-1）。

    申し送り: 本関数は cases.cancel_case の手順を複製している（cases.py が別担当の
    ため）。**両者は services/ の共通関数（許可ステータスと reason を引数化）へ
    統合すべき**。放置すると片方だけ直る二重メンテになる。
    """
    # cases.cancel_case・bids.select_bid と同じロック規約に参加する（Case行→…の順）。
    # 退会は本人操作のため競合は稀だが、多案件ユーザーではロック保持が案件数ぶん
    # 積み上がる点に留意（退会は低頻度操作のため許容と判断）。
    await lock_case_row(session, case.id)

    # losers の収集は必ず一括UPDATEの**前**に行う（ORM Update の同期方式により
    # identity map 上の Bid.status がその場で書き換わる。cases.py と同じ罠）。
    losers: list[tuple[str | None, str]] = [
        (b.operator.line_user_id, b.operator.contact_email)
        for b in case.bids
        if b.status == BID_STATUS_PENDING
    ]

    # 条件付きUPDATE（open/bidding であることをWHERE句で再検証してから更新する）。
    result = await session.execute(
        update(Case)
        .where(Case.id == case.id, Case.status.in_(_CANCELLABLE_CASE_STATUSES))
        .values(status="cancelled")
    )
    if result.rowcount != 1:
        # ロック取得前に他経路（取り下げ・落札）で状態が変わった場合。退会自体は
        # 続行し、当該案件の暗黙キャンセルのみ見送る（入札も触らない）。
        logger.warning(
            "users/me delete: 案件の暗黙キャンセルを見送り - case_id=%s status=%s",
            case.id,
            case.status,
        )
        return
    case.status = "cancelled"

    await session.execute(
        update(Bid)
        .where(Bid.case_id == case.id, Bid.status == BID_STATUS_PENDING)
        .values(status=BID_STATUS_REJECTED)
    )
    session.add(
        Cancellation(
            case_id=case.id,
            transaction_id=None,
            cancelled_by="user",
            reason=_WITHDRAWAL_CANCEL_REASON,
        )
    )
    for loser_line_user_id, loser_email in losers:
        notifications.append(
            (
                loser_line_user_id,
                loser_email,
                str(case.id),
                case.prefecture,
                case.city,
                case.purpose,
            )
        )


@router.delete(
    "/users/me",
    response_model=AccountDeleteResponse,
    summary="アカウント削除（匿名化。取引・メッセージ・レビューは業者側の記録として保持）",
)
async def delete_my_account(
    body: AccountDeleteRequest,
    request: Request,
    background: BackgroundTasks,
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
            select(Case)
            .where(Case.user_id == user.id)
            .options(
                selectinload(Case.transaction),
                # 暗黙キャンセル時の落選通知先（業者）を解決するため入札も読む。
                selectinload(Case.bids).selectinload(Bid.operator),
            )
        )
    ).all()
    lost_bid_notifications: list[_LostBidNotification] = []
    for case in cases:
        txn = case.transaction
        if txn is None and case.status in _NON_TERMINAL_CASE_STATUSES:
            if case.status in _CANCELLABLE_CASE_STATUSES:
                await _cancel_open_case_on_withdrawal(session, case, lost_bid_notifications)
            else:
                # draft は業者に公開されておらず入札も付かない（cases.cancel_case も
                # 409で弾く状態）ため、監査証跡・通知の対象にせず status のみ更新する。
                case.status = "cancelled"
        # 完了済み取引に紐づく案件のみ住所詳細を保持する（業者側の完了記録の整合性維持）。
        # それ以外（取引なし／キャンセル済み取引）は居住地PIIを退会時に除去する。
        if txn is None or txn.status != "completed":
            case.address_detail = None

    original_email_norm = user.email.strip().lower()

    # r10-review M1: privacy:110 の削除請求対応。contact_messages は認証不要の
    # 公開フォーム由来で本人以外も投稿しうるため物理削除はせず、退会と同じ
    # 「匿名化」方針（email 一致のみで足りる規模・admin_list_contacts の一覧
    # 表示に穴を開けない）で name/email/message を置換する。
    await session.execute(
        update(ContactMessage)
        .where(func.lower(ContactMessage.email) == original_email_norm)
        .values(
            name=f"deleted-{user.id}",
            email=f"deleted-{user.id}@deleted.katazuke.internal",
            message="[削除済み]",
        )
    )

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
    # ── マイページ拡張PIIの匿名化 ──────────────────────────────────
    user.birth_date = None
    user.occupation = None
    user.postal_code = None
    user.prefecture = None
    user.city = None
    user.address_line1 = None
    user.address_line2 = None
    user.bank_account_enc = None
    user.bank_account_updated_at = None
    user.deleted_at = datetime.now(timezone.utc)

    # 本人確認書類: 行・審査ステータス（承認/却下履歴）は業者側の記録と同様に
    # 保持するが、画像本体（機微PII）のみ Core の UPDATE で除去する。
    # ORM経由（deferred属性への代入）だとロード漏れで反映されない懸念があるため、
    # 明示的な Core UPDATE 文を使う（operator_license.py の _load_license_image
    # と同じ「BLOBはCoreで直接操作する」方針）。
    await session.execute(
        update(UserIdentityDocument)
        .where(UserIdentityDocument.user_id == user.id)
        .values(
            front_image_data=None,
            back_image_data=None,
            back_image_content_type=None,
        )
    )

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

    # 落選通知は commit 後にプリミティブ値で送る（cases.cancel_case と同じ規約）。
    for line_user_id, email, case_id, prefecture, city, purpose in lost_bid_notifications:
        background.add_task(
            notify_dispatch.dispatch_bid_lost,
            line_user_id,
            email,
            case_id,
            prefecture,
            city,
            purpose,
        )

    return AccountDeleteResponse(detail="退会手続きが完了しました。")
