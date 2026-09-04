"""認証エンドポイント — ユーザー（email+password）/ 業者（招待コード+email）。

JWT はバックエンドが発行し、フロントエンド（NextAuth.js）は本 API を
Credentials Provider から呼び出して取得したトークンをセッションに保持する。
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Actor,
    assert_operator_not_suspended,
    assert_user_not_revoked,
    assert_user_not_suspended,
    get_current_actor,
)
from app.api.rate_limit_deps import RateLimitGuard
from app.config import get_settings
from app.core.security import (
    REAUTH_PURPOSE_LINE_LINK,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.operator_application import OperatorApplication
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import (
    AuthTokenResponse,
    CURRENT_OPERATOR_TERMS_VERSION,
    LineExchangeRequest,
    OperatorLoginRequest,
    OperatorOut,
    OperatorSignupRequest,
    UserLoginRequest,
    UserOut,
    UserSignupRequest,
)
from app.services import alerts
from app.services.notify import is_placeholder_email

logger = logging.getLogger(__name__)

router = APIRouter()


def _is_listed_admin_email(email: str) -> bool:
    """``email`` が ADMIN_EMAILS に含まれるかを判定する（security review L-1対応）。

    ``get_settings().admin_emails`` は既に ``.strip().lower()`` 済みのリストだが、
    比較対象の ``email`` 側は正規化されているとは限らない（LINE 連携経由で
    作成されたユーザーの ``User.email`` は正規化が保証されない）。比較直前に
    必ず ``.strip().lower()`` してから照合することで、大文字小文字・前後空白の
    揺れによる判定ミスを防ぐ。
    """
    return email.strip().lower() in get_settings().admin_emails


async def _admin_role_available(session: AsyncSession) -> bool:
    """DB に有効な（``deleted_at IS NULL`` の）``role="admin"`` ユーザーが
    1人も存在しない場合に True を返す。

    R3再レビュー Critical対応: ADMIN_EMAILS 経由の自動昇格（signup 時の初回
    ブートストラップ／ログイン時の再評価昇格）が許される条件を、この関数
    1つに一本化する（従来は signup 側にのみ同等のインライン判定があり、
    ログイン時昇格 ``_promote_to_admin_if_listed`` は無条件で昇格していたため、
    ADMIN_EMAILS に一般ユーザーのメールアドレスが誤って残っていると際限なく
    admin を量産できる特権昇格経路になっていた）。論理削除済み（退会済み）の
    admin は「不在」として扱い、再ブートストラップを許可する。
    """
    existing = await session.scalar(
        select(User.id).where(User.role == "admin", User.deleted_at.is_(None)).limit(1)
    )
    return existing is None


async def _promote_to_admin_if_listed(session: AsyncSession, user: User) -> bool:
    """ADMIN_EMAILS に含まれ、かつ DB に有効な admin が1人も居ない場合のみ昇格させる。

    R3-operator ADD-3対応: 従来 role="admin" の付与はサインアップ時の一度きり
    だったため、後から ADMIN_EMAILS に追記しても既存アカウントは永久に一般
    ユーザーのままだった。ログイン成功のたびに再評価することで、既存
    アカウントも次回ログイン時に自動昇格させる（降格は行わない一方向）。

    R3再レビュー Critical対応: 上記の再評価を「ADMIN_EMAILS 該当なら常に昇格」
    のまま実装していたため、既に admin が存在する状態でも ADMIN_EMAILS に
    残った/誤って追記されたメールアドレスでログインするだけで際限なく admin を
    増やせてしまっていた。signup 側の初回ブートストラップ条件
    （``_admin_role_available``）と判定を一本化し、「DB に有効な admin が
    1人も存在しない場合のみ」昇格する。既存 admin が居る状態での2人目以降の
    admin 付与は ``POST /admin/users/{id}/promote``（admin 認可必須）経由のみ
    とする。呼び出し元は戻り値が True の場合のみ commit し、commit **成功後**に
    昇格アラートを発火すること（commit 失敗時に「昇格した」という偽の通知を
    送らないため）。
    """
    if user.role == "admin" or not _is_listed_admin_email(user.email):
        return False
    if not await _admin_role_available(session):
        # security review C-1対応の延長: 昇格をブロックした事実も検知可能に
        # しておく（ADMIN_EMAILS の設定不備・退職者アドレス残存の早期発見のため）。
        logger.warning(
            "admin promotion blocked (admin already exists): email=%s user_id=%s",
            user.email,
            user.id,
        )
        alerts.fire_and_forget(
            alerts.send_alert(
                "ADMIN_EMAILS 記載アドレスが admin 不在条件を満たさずログイン",
                f"email={user.email}\nuser_id={user.id}\nvia=login_promotion",
                severity="warning",
                key=f"admin-promotion-blocked:{user.email}",
            )
        )
        return False
    user.role = "admin"
    # security review C-1対応: admin 権限の付与はアカウント奪取の直接経路になり
    # うるため、昇格が発生した瞬間を必ず WARNING ログに残す（アラート基盤が
    # 拾える形にする）。本番の ADMIN_EMAILS 実値・該当ユーザー行の存在は運用側で
    # 別途確認すること（本修正の対象外・r3-review-security.md R-3）。
    logger.warning(
        "admin role granted: email=%s via=%s user_id=%s",
        user.email,
        "login_promotion",
        user.id,
    )
    return True


_LOGIN_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="メールアドレスまたはパスワードが正しくありません。",
)

_LINE_PROFILE_ENDPOINT = "https://api.line.me/v2/profile"
_LINE_VERIFY_ENDPOINT = "https://api.line.me/oauth2/v2.1/verify"
# LINE userId は "U" + 32桁の16進数文字列（LINE Platform API仕様）。
_LINE_USER_ID_RE = re.compile(r"^U[0-9a-f]{32}$")

_LINE_AUTH_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="LINEアカウントの認証に失敗しました。もう一度お試しください。",
)
_LINE_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="LINEログイン機能は現在ご利用いただけません。",
)


# ──────────────────────────── ユーザー ────────────────────────────


@router.post(
    "/auth/signup",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="ユーザー登録",
)
async def user_signup(
    body: UserSignupRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("signup")),
) -> AuthTokenResponse:
    email = body.email.lower()
    # LINE専用アカウント用の内部プレースホルダドメイン（line.katazuke.internal /
    # deleted.katazuke.internal）での新規登録は拒否する（実在しない内部専用メールを
    # 一般ユーザーが自称登録すると、退会済み/LINE専用アカウントとの衝突・
    # なりすまし経路になり得るため）。
    if is_placeholder_email(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="このメールアドレスは登録できません。別のメールアドレスをご利用ください。",
        )
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このメールアドレスは既に登録されています。",
        )
    # security review L-1対応: email は既に .lower() 済みだが、比較関数側と
    # 判定条件を一本化するため _is_listed_admin_email 経由で比較する。
    # N-1（Critical）対応: signup 時の admin 付与は「DB に有効な role=admin の
    # ユーザーがまだ1人も存在しない（＝初回ブートストラップ）」場合のみに限定
    # する（判定は ``_admin_role_available`` に一本化。ログイン時昇格
    # ``_promote_to_admin_if_listed`` も同じ関数で同じ条件を判定する）。
    # ADMIN_EMAILS は運用上変更・追記されうるため、2人目以降の admin 付与は
    # 既存アカウントのログイン時昇格、または ``POST /admin/users/{id}/promote``
    # （admin 認可必須）のみを経路とする。これにより ADMIN_EMAILS に後から
    # 追記されたアドレスへ、初回登録より前に第三者が signup して admin を
    # 先取りする経路を塞ぐ。
    role = (
        "admin"
        if await _admin_role_available(session) and _is_listed_admin_email(email)
        else "user"
    )
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    if role == "admin":
        # security review C-1対応: サインアップ時の admin 付与はアカウント奪取の
        # 直接経路（ADMIN_EMAILS 未登録アドレスの land-grab）になりうるため、
        # 発生した瞬間を必ず WARNING ログに残す（アラート基盤が拾える形にする）。
        logger.warning("admin role granted: email=%s via=%s user_id=%s", email, "signup", user.id)
        # N-1対応: WARNING ログのみでは検知漏れになりうるため、運営アラート
        # （severity=critical）でも通知する（login_promotion 側と同一パターン）。
        alerts.fire_and_forget(
            alerts.send_alert(
                "admin 権限が付与されました",
                f"email={email}\nvia=signup\nuser_id={user.id}",
                severity="critical",
                key=f"admin-grant:{email}",
            )
        )
    token = create_access_token(user.id, "user", user.role)
    return AuthTokenResponse(
        access_token=token, account_type="user", user=UserOut.model_validate(user)
    )


@router.post("/auth/login", response_model=AuthTokenResponse, summary="ユーザーログイン")
async def user_login(
    body: UserLoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("login")),
) -> AuthTokenResponse:
    ctx = request.state.rate_limit
    email = body.email.lower()
    # レート制限のアカウント軸識別子は "user:"/"operator:" で名前空間分離する
    # （security review 指摘・最優先）。user login と operator login は scope="login"
    # で上限値・窓・文言を共有しているが、識別子を素の email のままにすると、
    # 同一メールアドレスで user/operator 双方のアカウントが存在する場合に
    # ストアキーの実体まで共有されてしまい、無認証の第三者が相手のメール
    # アドレスを知るだけで（例: user 側を誤パスワードで5回叩く）相手の
    # operator 側ログインまで巻き添えでブロックできてしまう。
    rl_account_key = f"user:{email}"
    ctx.check_account(rl_account_key)

    user = await session.scalar(select(User).where(User.email == email))
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        ctx.record_failure(rl_account_key)
        raise _LOGIN_FAILED
    ctx.reset_account(rl_account_key)
    # 停止判定はレート制限（総当たり対策）とは別関心のビジネスルールのため、
    # リセット後に判定する（operator_login と同じ順序）。deps.py の
    # assert_user_not_suspended と同一の detail（security review L-2対応の
    # dict 形式）を使うため、判定ロジックを重複させずそちらへ委譲する。
    assert_user_not_suspended(user)
    if await _promote_to_admin_if_listed(session, user):
        await session.commit()
        await session.refresh(user)
        # R3再レビュー Critical対応: 昇格アラートは commit 成功後にのみ発火する
        # （commit 前に発火すると、commit が何らかの理由で失敗した場合に
        # 「昇格した」という偽の通知が運営に届いてしまうため）。
        alerts.fire_and_forget(
            alerts.send_alert(
                "admin 権限が付与されました",
                f"email={user.email}\nvia=login_promotion\nuser_id={user.id}",
                severity="critical",
                key=f"admin-grant:{user.email}",
            )
        )
    token = create_access_token(user.id, "user", user.role)
    return AuthTokenResponse(
        access_token=token, account_type="user", user=UserOut.model_validate(user)
    )


# ──────────────────────────── 業者 ────────────────────────────


@router.post(
    "/auth/operator/signup",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="業者登録（招待コード任意: あれば審査済み前提でactive、なければpending＝要admin承認）",
)
async def operator_signup(
    body: OperatorSignupRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("signup")),
) -> AuthTokenResponse:
    if not body.agreed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="利用規約・プライバシーポリシーへの同意が必要です。",
        )
    invite = None
    email = body.email.lower()
    # LINE専用アカウント用の内部プレースホルダドメインでの新規登録は拒否する
    # （user_signup と同じ理由。security review 指摘対応）。
    if is_placeholder_email(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="このメールアドレスは登録できません。別のメールアドレスをご利用ください。",
        )
    # 招待コードがある場合のみ検証・消込
    if body.invite_code:
        invite = await session.scalar(select(Invite).where(Invite.code == body.invite_code))
        if invite is None or invite.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="招待コードが無効、または既に使用されています。",
            )
        # 招待コードが特定emailに紐付けて発行されている場合（admin承認フロー等）は、
        # signup時のemailと一致することを必須にする。不一致だと招待コード漏洩時に
        # 全く別人が任意emailで無審査のまま active 業者アカウントを作成できてしまうため
        # （security review High指摘対応）。
        # email無し（None）で発行された招待コード（admin/invites, admin/invites/bulk 等）は
        # 従来通り誰でも使用可能な運用を維持する。
        if invite.email is not None and invite.email.lower() != email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="この招待コードは別のメールアドレス向けに発行されています。",
            )
    existing = await session.scalar(select(Operator).where(Operator.contact_email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このメールアドレスは既に登録されています。",
        )
    # 招待コードあり=admin事前審査済み前提でactive（即フル稼働）。
    # 招待コードなし（オープン登録）=pending（案件閲覧は可・入札は admin 承認まで不可）。
    vendor_status = "active" if invite else "pending"
    operator = Operator(
        company_name=body.company_name,
        contact_email=email,
        license_number=body.license_number,
        invite_code=body.invite_code or None,
        password_hash=hash_password(body.password),
        vendor_status=vendor_status,
        verified_at=None,  # admin approveで更新
        agreed_terms_version=CURRENT_OPERATOR_TERMS_VERSION,
        agreed_at=datetime.now(timezone.utc),
    )
    session.add(operator)
    await session.flush()
    if invite is not None:
        invite.used_at = datetime.now(timezone.utc)
        invite.operator_id = operator.id
        # M-4対応: admin承認フローで発行された招待コードなら、その発行元の
        # 事前申込（invite_codeで対応付け）に operator_id を書き戻す。
        # 招待コードとの対応付けは OperatorApplication.invite_code
        # （承認時に発行コードを控える。app/api/v1/endpoints/admin.py の
        # approve_operator_application 参照）で引く。
        application = await session.scalar(
            select(OperatorApplication).where(OperatorApplication.invite_code == invite.code)
        )
        if application is not None:
            application.operator_id = operator.id
    await session.commit()
    await session.refresh(operator)
    token = create_access_token(operator.id, "operator", "operator")
    return AuthTokenResponse(
        access_token=token,
        account_type="operator",
        operator=OperatorOut.model_validate(operator),
    )


@router.post(
    "/auth/operator/login", response_model=AuthTokenResponse, summary="業者ログイン"
)
async def operator_login(
    body: OperatorLoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("login")),
) -> AuthTokenResponse:
    ctx = request.state.rate_limit
    email = body.email.lower()
    # "operator:" 名前空間分離の理由は user_login と同じ（security review 指摘・
    # 最優先）。同一メールで user/operator 双方が存在する場合にストアキーの
    # 実体まで共有されるのを防ぐ（上限値・窓・文言は user_login と同一のまま）。
    rl_account_key = f"operator:{email}"
    ctx.check_account(rl_account_key)

    # 退会済み業者は contact_email がトムストン化されるため通常は一致しないが、
    # 多層防御として deleted_at でも明示的に除外する（r8-M6）。
    operator = await session.scalar(
        select(Operator).where(
            Operator.contact_email == email, Operator.deleted_at.is_(None)
        )
    )
    if (
        operator is None
        or operator.password_hash is None
        or not verify_password(body.password, operator.password_hash)
    ):
        ctx.record_failure(rl_account_key)
        raise _LOGIN_FAILED
    # パスワード照合の成功をレート制限上の「成功」境界とする（アカウント軸をリセット）。
    # 停止判定はレート制限（総当たり対策）とは別関心のビジネスルールのため、
    # リセット後に判定する。
    ctx.reset_account(rl_account_key)
    # R3再レビュー Medium対応: 停止時の detail を独自の文字列で組み立てず、
    # deps.py の assert_operator_not_suspended（dict detail・SUSPENDED_ACCOUNT_DETAIL
    # 共用）に委譲する（user_login・LINE連携経路と契約を一本化する）。
    assert_operator_not_suspended(operator)
    token = create_access_token(operator.id, "operator", "operator")
    return AuthTokenResponse(
        access_token=token,
        account_type="operator",
        operator=OperatorOut.model_validate(operator),
    )


# ──────────────────────────── LINEログイン統合 ────────────────────────────


async def _verify_line_access_token(line_access_token: str) -> None:
    """LINE Verify API でアクセストークンの発行元チャネル（audience）を検証する。

    LINE の Profile API はアクセストークンの発行元チャネルを問わず有効なユーザーの
    プロフィールを返してしまうため、Profile API を叩く前に本関数で
    「このアクセストークンが自社の LINE Login チャネル向けに発行されたものか」を
    必ず確認する（cross-channel token confusion によるなりすまし対策）。

    検証項目:
      - Verify API 自体が 200 を返すこと（無効・期限切れトークンは 400 を返す）。
      - レスポンスの client_id が自社チャネル ID と一致すること。
      - expires_in > 0 であること。
    """
    settings = get_settings()
    if not settings.line_client_id:
        logger.error("auth/line/exchange: LINE_CLIENT_ID が未設定のため LINE ログインを拒否")
        raise _LINE_NOT_CONFIGURED

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                _LINE_VERIFY_ENDPOINT,
                params={"access_token": line_access_token},
            )
        if res.status_code != 200:
            logger.error(
                "auth/line/exchange: LINE Verify API がエラーを返却 - status=%s body=%s",
                res.status_code,
                res.text[:500],
            )
            raise _LINE_AUTH_FAILED
        data = res.json()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("auth/line/exchange: LINE Verify API 呼び出し失敗 - %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LINEアカウント情報の取得に失敗しました。",
        ) from exc

    client_id = data.get("client_id")
    expires_in = data.get("expires_in")
    if client_id != settings.line_client_id:
        logger.error(
            "auth/line/exchange: LINEアクセストークンのchannel不一致 - client_id=%s",
            client_id,
        )
        raise _LINE_AUTH_FAILED
    if not isinstance(expires_in, int) or expires_in <= 0:
        logger.error(
            "auth/line/exchange: LINEアクセストークンが期限切れ - expires_in=%s", expires_in
        )
        raise _LINE_AUTH_FAILED


async def _fetch_line_user_id(line_access_token: str) -> str:
    """アクセストークンのチャネル検証後、LINE Profile API を叩いて userId を取得する。

    id_token/JWKS 検証は行わない MVP 方式（将来強化: OIDC id_token 検証への切替）。
    LINE 側のエラー・タイムアウトは認証系のため握りつぶさず 502 を返す。
    """
    await _verify_line_access_token(line_access_token)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                _LINE_PROFILE_ENDPOINT,
                headers={"Authorization": f"Bearer {line_access_token}"},
            )
        if res.status_code != 200:
            logger.error(
                "auth/line/exchange: LINE Profile API がエラーを返却 - status=%s body=%s",
                res.status_code,
                res.text[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="LINEアカウント情報の取得に失敗しました。",
            )
        data = res.json()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("auth/line/exchange: LINE Profile API 呼び出し失敗 - %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LINEアカウント情報の取得に失敗しました。",
        ) from exc

    line_user_id = data.get("userId")
    if not line_user_id or not _LINE_USER_ID_RE.match(str(line_user_id)):
        logger.error(
            "auth/line/exchange: LINE Profile API 応答の userId が不正な書式 - userId=%s",
            line_user_id,
        )
        raise _LINE_AUTH_FAILED
    return str(line_user_id)


def _extract_bearer_token(request: Request) -> str | None:
    """Authorization: Bearer ヘッダを任意で読み取る（未指定なら None）。"""
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header[len("Bearer ") :].strip()
    return token or None


_ALREADY_LINKED_TO_OTHER_LINE = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="このアカウントは既に別のLINEアカウントと連携済みです。"
    "連携を解除してから再度お試しください。",
)
_REAUTH_REQUIRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="LINE連携には再認証が必要です。現在のパスワードで再認証してください。",
)
_REAUTH_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="再認証トークンが無効、または有効期限が切れています。",
)


def _validate_reauth_token(
    reauth_token: str | None,
    expected_subject_id: uuid.UUID,
    expected_typ: str,
) -> None:
    """LINE連携（新規付与）の再認証トークンを検証する。

    検証項目: purpose一致（"line_link"）・typ一致（"user"/"operator"）・
    sub（user_id/operator_id）がBearerの本人IDと一致・有効期限内
    （decode_access_token が exp を検証し期限切れは PyJWTError で送出）。
    typ を検証することで、user 用に発行された reauth_token を operator 側の
    line_exchange に流用する（またはその逆）誤通過を防ぐ（アカウント種別を
    跨いだ再認証トークンの使い回しを構造的に禁止する。security review H-1対応）。
    パスワード未設定（LINE専用）アカウントはこの関数を呼び出さない
    （呼び出し元 line_exchange で password_hash is None の場合はスキップする）。
    """
    if reauth_token is None:
        raise _REAUTH_REQUIRED
    try:
        payload = decode_access_token(reauth_token)
    except pyjwt.PyJWTError as exc:
        raise _REAUTH_INVALID from exc
    if payload.get("purpose") != REAUTH_PURPOSE_LINE_LINK:
        raise _REAUTH_INVALID
    if payload.get("typ") != expected_typ:
        raise _REAUTH_INVALID
    try:
        token_subject_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _REAUTH_INVALID from exc
    if token_subject_id != expected_subject_id:
        raise _REAUTH_INVALID


@router.post(
    "/auth/line/exchange",
    response_model=AuthTokenResponse,
    summary="LINEログイン統合 — LINEアクセストークンを検証しJWTを発行する",
)
async def line_exchange(
    body: LineExchangeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _rl: object = Depends(RateLimitGuard("line_exchange")),
) -> AuthTokenResponse:
    line_user_id = await _fetch_line_user_id(body.line_access_token)

    bearer_token = _extract_bearer_token(request)

    # ── ケース1: Bearer あり（連携）── 既存アカウントに line_user_id を紐付ける。
    if bearer_token is not None:
        try:
            payload = decode_access_token(bearer_token)
        except pyjwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials. Please log in again.",
            ) from exc
        # reauth_token（purposeクレーム付きの用途限定トークン）は通常のセッション
        # 識別（Authorization: Bearer）には使えない。deps._decode と同じガードを
        # ここでも適用する（security review Medium指摘対応）。
        if payload.get("purpose") is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials. Please log in again.",
            )

        typ = payload.get("typ")
        try:
            subject_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials. Please log in again.",
            ) from exc

        if typ == "user":
            user = await session.get(User, subject_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials. Please log in again.",
                )
            # 退会（論理削除）済み・パスワード変更後の旧トークンは deps.py と同一ゲートで失効させる
            # （security review 指摘: line_exchange のBearer経路はこのゲートを経由していなかった）。
            assert_user_not_revoked(user, payload)
            # 停止中依頼者の旧トークンも deps.py と同一ゲートで失効させる（r3-verify-operator ADD-2）。
            assert_user_not_suspended(user)

            # 既に別のLINEアカウントに連携済みの場合は無条件で拒否する（再バインド禁止。
            # security review 最重要指摘）。同一 line_user_id の再送（冪等な再連携）は許可する。
            if user.line_user_id is not None and user.line_user_id != line_user_id:
                raise _ALREADY_LINKED_TO_OTHER_LINE

            if user.line_user_id != line_user_id:
                # 初回連携（付与）。パスワード設定済みユーザーのみ再認証トークンを要求する
                # （LINE専用アカウントは再認証手段が無いためスキップ。security review指摘）。
                if user.password_hash is not None:
                    _validate_reauth_token(body.reauth_token, user.id, "user")

                # 既に別ユーザーに同じ line_user_id が使われていないか事前チェック
                # （IntegrityError にも二重で備える: レースコンディション対策）。
                conflict = await session.scalar(
                    select(User).where(User.line_user_id == line_user_id, User.id != user.id)
                )
                if conflict is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="このLINEアカウントは既に別のアカウントと連携されています。",
                    )
                # User.line_user_id / Operator.line_user_id は別テーブルの独立した UNIQUE 制約
                # のため、DB制約だけでは同一 line_user_id が User と Operator の両方に
                # 紐づくことを防げない。アプリ層で相互チェックする（Medium-2 対応）。
                conflict_cross = await session.scalar(
                    select(Operator).where(Operator.line_user_id == line_user_id)
                )
                if conflict_cross is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="このLINEアカウントは既に別のアカウントと連携されています。",
                    )
                user.line_user_id = line_user_id
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="このLINEアカウントは既に別のアカウントと連携されています。",
                    ) from exc
                await session.refresh(user)
            token = create_access_token(user.id, "user", user.role)
            return AuthTokenResponse(
                access_token=token, account_type="user", user=UserOut.model_validate(user)
            )

        if typ == "operator":
            operator = await session.get(Operator, subject_id)
            if operator is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials. Please log in again.",
                )
            # 停止中業者の旧トークンは deps.py と同一ゲートで失効させる（security review指摘）。
            assert_operator_not_suspended(operator)

            # 再バインド禁止ガード（user分岐と同様。同一 line_user_id の再送は許可する）。
            if operator.line_user_id is not None and operator.line_user_id != line_user_id:
                raise _ALREADY_LINKED_TO_OTHER_LINE

            if operator.line_user_id != line_user_id:
                # 初回連携（付与）。パスワード設定済み業者のみ再認証トークンを要求する
                # （user分岐と同様の理由・同一の再認証トークン検証を用いる。
                # operator は operator_signup で必ず password_hash を持つため、
                # 実質すべての業者が対象になる。security review H-1対応）。
                if operator.password_hash is not None:
                    _validate_reauth_token(body.reauth_token, operator.id, "operator")

                conflict_op = await session.scalar(
                    select(Operator).where(
                        Operator.line_user_id == line_user_id, Operator.id != operator.id
                    )
                )
                if conflict_op is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="このLINEアカウントは既に別のアカウントと連携されています。",
                    )
                # User テーブル側でも同じ line_user_id が使われていないか相互チェック（Medium-2 対応）。
                conflict_cross = await session.scalar(
                    select(User).where(User.line_user_id == line_user_id)
                )
                if conflict_cross is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="このLINEアカウントは既に別のアカウントと連携されています。",
                    )
                operator.line_user_id = line_user_id
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="このLINEアカウントは既に別のアカウントと連携されています。",
                    ) from exc
                await session.refresh(operator)
            token = create_access_token(operator.id, "operator", "operator")
            return AuthTokenResponse(
                access_token=token,
                account_type="operator",
                operator=OperatorOut.model_validate(operator),
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials. Please log in again.",
        )

    # ── ケース2: Bearer なし（新規登録 / ログイン）── User テーブルのみを対象とする。
    # 業者テーブルへの LINE 単独新規作成はここでは行わない（連携情報が無いため）。
    existing_user = await session.scalar(select(User).where(User.line_user_id == line_user_id))
    if existing_user is not None:
        # 停止中依頼者は LINE ログインでも新規トークンを発行しない（user_login と同一ゲート・
        # detail は deps.py の assert_user_not_suspended に委譲し文言を一本化する）。
        assert_user_not_suspended(existing_user)
        if await _promote_to_admin_if_listed(session, existing_user):
            await session.commit()
            await session.refresh(existing_user)
            # user_login と同じ理由でcommit成功後にのみ発火する。
            alerts.fire_and_forget(
                alerts.send_alert(
                    "admin 権限が付与されました",
                    f"email={existing_user.email}\nvia=login_promotion\n"
                    f"user_id={existing_user.id}",
                    severity="critical",
                    key=f"admin-grant:{existing_user.email}",
                )
            )
        token = create_access_token(existing_user.id, "user", existing_user.role)
        return AuthTokenResponse(
            access_token=token, account_type="user", user=UserOut.model_validate(existing_user)
        )

    # 新規 User 作成前に、同じ line_user_id が既に Operator テーブル側で
    # 使われていないか確認する（Medium-2 対応）。放置すると同一LINEアカウントで
    # User と Operator の両方が作られてしまい、アカウント種別の境界が崩れる。
    existing_operator = await session.scalar(
        select(Operator).where(Operator.line_user_id == line_user_id)
    )
    if existing_operator is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このLINEアカウントは既に別のアカウントと連携されています。",
        )

    # 新規作成。LINE Profile API は email を返さないため、今回は email 突合による
    # 二重アカウント統合は行わずシンプルに新規作成する（スコープ外・将来対応）。
    # User.email は NOT NULL + UNIQUE 制約のため、実メールが確定するまでの
    # プレースホルダを生成する（実メールは /mypage/profile で後から設定させる想定）。
    placeholder_email = f"line-{line_user_id}@line.katazuke.internal"
    new_user = User(
        email=placeholder_email,
        password_hash=None,
        name=None,
        role="user",
        line_user_id=line_user_id,
    )
    session.add(new_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # line_user_id か placeholder_email の重複（レースコンディション）。
        # 通常はここに到達しない想定（事前 SELECT で existing_user None を確認済み）。
        logger.error("auth/line/exchange: 新規User作成が一意制約違反で失敗 - %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このLINEアカウントは既に別のアカウントと連携されています。",
        ) from exc
    await session.refresh(new_user)
    token = create_access_token(new_user.id, "user", new_user.role)
    return AuthTokenResponse(
        access_token=token, account_type="user", user=UserOut.model_validate(new_user)
    )


# ──────────────────────────── 共通 ────────────────────────────


@router.get("/auth/me", response_model=AuthTokenResponse, summary="ログイン中アカウント情報")
async def me(actor: Actor = Depends(get_current_actor)) -> AuthTokenResponse:
    """トークン検証を兼ねたプロフィール取得（access_token は返却しない）。"""
   
    if actor.typ == "user":
        assert actor.user is not None
        return AuthTokenResponse(
            access_token="", account_type="user", user=UserOut.model_validate(actor.user)
        )
    assert actor.operator is not None
    return AuthTokenResponse(
        access_token="",
        account_type="operator",
        operator=OperatorOut.model_validate(actor.operator),
    )
