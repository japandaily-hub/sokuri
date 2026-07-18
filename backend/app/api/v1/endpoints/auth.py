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

from app.api.deps import Actor, get_current_actor
from app.api.rate_limit_deps import RateLimitGuard
from app.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db.models.invite import Invite
from app.db.models.operator import Operator
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

logger = logging.getLogger(__name__)

router = APIRouter()

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
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このメールアドレスは既に登録されています。",
        )
    role = "admin" if email in get_settings().admin_emails else "user"
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
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

    operator = await session.scalar(select(Operator).where(Operator.contact_email == email))
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
    if operator.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントが停止されています。運営にお問い合わせください。",
        )
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
