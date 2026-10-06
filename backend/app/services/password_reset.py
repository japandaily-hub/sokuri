"""メールによるパスワード再設定（依頼者 users・業者 operators 共通）。

流れ:
1. 要求（``POST /auth/password-reset/request``）: エンドポイントは本文の検証とレート制限だけを
   行って常に同じ 202 を返し、アカウントの照会・トークン発行・メール送信は応答の後の
   バックグラウンド処理（``process_reset_request``）で行う。登録の有無で応答の中身も
   応答時間も変わらない（照会・DB 書き込み・メール送信の時間差が応答に乗らない）。
2. 確定（``POST /auth/password-reset/confirm``）: ``consume_reset_token`` が
   「未使用・期限内・種別一致」の行を1文の UPDATE で使用済みにして相手のアカウントを返し
   （同じトークンの同時確定でも成功するのは1回だけ）、``apply_new_password`` が
   パスワードを差し替えて既存のログイン（JWT）を失効させる。

トークンの扱い:
- ``secrets.token_urlsafe(32)``（256bit）。DB には SHA-256 の16進だけを保存し、平文は
  メール本文（``notify.send_password_reset``）以外に出さない（ログ・アラートにも出さない）。
- 有効期限30分・1回限り。同一アカウントで新しい要求が来たら未使用の旧トークンを無効化し、
  使用済み・期限切れの行は削除する（1アカウントあたり高々2行）。確定時も同じアカウントの
  他の未使用トークンを無効化する。

既存ログインの失効（再設定の確定時）:
- 依頼者: パスワード変更（``PUT /users/me/password``）と同じ ``password_changed_at`` を
  確定時刻にする（deps.is_user_token_revoked が iat < password_changed_at のトークンを 401）。
- 業者: パスワード変更の失効ゲートが無いため、停止解除と同じ ``sessions_revoked_at`` を
  確定時刻にする（deps._is_session_revoked_by_suspension が iat <= 境界のトークンを 401。
  停止中は 403 が優先されるが、停止中の業者にはトークンを発行しない）。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_summary import describe_exception
from app.core.security import hash_password
from app.db import session as db_session_module
from app.db.models.operator import Operator
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.user import User
from app.services import notify

logger = logging.getLogger(__name__)

#: 再設定リンクの有効期限（分）。メール本文にもこの値を載せる。
RESET_TOKEN_TTL_MINUTES = 30
#: ``secrets.token_urlsafe`` に渡すバイト数（256bit・43文字）。
RESET_TOKEN_BYTES = 32


def hash_reset_token(raw_token: str) -> str:
    """平文トークンを保存・照合用の SHA-256 16進（64文字）にする。

    トークン自体が 256bit の乱数のため、総当たり対策の鍵伸長（scrypt 等）は不要で、
    索引で引ける決定的なハッシュにする。
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _account_filter(account_type: str, account_id: uuid.UUID):  # noqa: ANN202 -- SQL 式
    return (
        PasswordResetToken.account_type == account_type,
        PasswordResetToken.account_id == account_id,
    )


async def find_resettable_account(
    session: AsyncSession, account_type: str, email: str
) -> User | Operator | None:
    """再設定の案内を送ってよいアカウントを返す（無ければ None）。

    送らない（None を返す）もの:
    - 退会・削除済み（``deleted_at``。トムストンのメールにも一致しないが多層防御として除外）
    - 停止中（停止中はログインできず、再設定しても使えない。解除後に手続きしてもらう）
    - パスワード未設定（LINE ログイン専用。メールだけでパスワードを新設できると、
      LINE で本人確認しているアカウントの入口がメールの受信だけで増えてしまう）
    - 実在しない内部用アドレス（LINE 専用の仮メール・退会トムストン。``is_placeholder_email``）
    ``email`` は呼び出し側で小文字化済み（ログインと同じ照合）。
    """
    if notify.is_placeholder_email(email):
        return None
    account: User | Operator | None
    if account_type == "user":
        account = await session.scalar(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
    else:
        account = await session.scalar(
            select(Operator).where(
                Operator.contact_email == email, Operator.deleted_at.is_(None)
            )
        )
    if account is None or account.is_suspended or account.password_hash is None:
        return None
    return account


async def issue_reset_token(
    session: AsyncSession, account_type: str, account_id: uuid.UUID, now: datetime
) -> str:
    """新しいトークンを発行して平文を返す（commit は呼び出し側）。

    同じアカウントの使用済み・期限切れの行を削除し、未使用の旧トークンを無効化してから
    新しい行を追加する（新しい要求が来たら古いリンクは使えない）。
    """
    await session.execute(
        delete(PasswordResetToken)
        .where(*_account_filter(account_type, account_id))
        .where(
            or_(
                PasswordResetToken.used_at.is_not(None),
                PasswordResetToken.expires_at <= now,
            )
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(PasswordResetToken)
        .where(*_account_filter(account_type, account_id))
        .where(PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    raw_token = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    session.add(
        PasswordResetToken(
            account_type=account_type,
            account_id=account_id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        )
    )
    return raw_token


async def process_reset_request(account_type: str, email: str) -> None:
    """要求の本体（応答の後にバックグラウンドで実行する）。例外は外へ出さない。

    対象アカウントがあればトークンを発行して案内メールを送る。無ければ何もしない。
    ログには種別・アカウント ID・送信の成否だけを出す（メールアドレス・トークンは出さない）。
    """
    try:
        session_factory = db_session_module.get_background_session_factory()
        async with session_factory() as session:
            account = await find_resettable_account(session, account_type, email)
            if account is None:
                logger.info(
                    "password_reset: 案内の対象となるアカウントが無いため送信しません（type=%s）",
                    account_type,
                )
                return
            account_id = account.id
            to_address = account.email if isinstance(account, User) else account.contact_email
            raw_token = await issue_reset_token(
                session, account_type, account_id, datetime.now(timezone.utc)
            )
            await session.commit()
        sent = await notify.send_password_reset(
            to_address, account_type, raw_token, RESET_TOKEN_TTL_MINUTES
        )
        logger.info(
            "password_reset: 再設定の案内を発行しました（type=%s account_id=%s mail_sent=%s）",
            account_type,
            account_id,
            sent,
        )
    except Exception as exc:  # noqa: BLE001 -- 応答後の処理のため、ここで記録して握る
        logger.error(
            "password_reset: 再設定の案内の発行に失敗しました（type=%s）: %s",
            account_type,
            describe_exception(exc),
        )


async def consume_reset_token(
    session: AsyncSession, account_type: str, raw_token: str, now: datetime
) -> uuid.UUID | None:
    """トークンを使用済みにしてアカウント ID を返す（無効・期限切れ・使用済み・種別違いは None）。

    「未使用・期限内・種別一致」の条件付き UPDATE 1文で使用済みにするため、同じトークンの
    同時確定でも成功するのは1回だけ。照合は SHA-256 の一致で索引を引き、返った行の
    ハッシュも ``hmac.compare_digest``（定数時間比較）で確かめる（多層防御）。
    commit は呼び出し側。
    """
    token_hash = hash_reset_token(raw_token)
    result = await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.account_type == account_type,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(PasswordResetToken.account_id, PasswordResetToken.token_hash)
        .execution_options(synchronize_session=False)
    )
    row = result.first()
    if row is None or not hmac.compare_digest(row.token_hash, token_hash):
        return None
    return row.account_id


async def apply_new_password(
    session: AsyncSession,
    account_type: str,
    account_id: uuid.UUID,
    new_password: str,
    now: datetime,
) -> bool:
    """パスワードを差し替え、既存のログインを失効させる（commit は呼び出し側）。

    発行後に退会・停止・LINE 専用化（通常は起きない）したアカウントは False を返して
    何も変えない。成功時は同じアカウントの他の未使用トークンも無効化する。
    """
    account: User | Operator | None
    if account_type == "user":
        account = await session.get(User, account_id)
    else:
        account = await session.get(Operator, account_id)
    if (
        account is None
        or account.deleted_at is not None
        or account.is_suspended
        or account.password_hash is None
    ):
        return False

    account.password_hash = hash_password(new_password)
    if isinstance(account, User):
        account.password_changed_at = now
    else:
        account.sessions_revoked_at = now
    await session.execute(
        update(PasswordResetToken)
        .where(*_account_filter(account_type, account_id))
        .where(PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    return True
