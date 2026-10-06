"""メールによるパスワード再設定（依頼者 users・業者 operators 共通）。

流れ:
1. 要求（``POST /auth/password-reset/request``）: エンドポイントは本文の検証とレート制限だけを
   行って常に同じ 202 を返し、アカウントの照会・トークン発行・メール送信は応答の後の
   バックグラウンド処理（``process_reset_request``）で行う。登録の有無で応答の中身も
   応答時間も変わらない（照会・DB 書き込み・メール送信の時間差が応答に乗らない）。
2. 確定（``POST /auth/password-reset/confirm``）: ``consume_reset_token`` が
   「未使用・期限内・種別一致」の行を1文の UPDATE で使用済みにして相手のアカウントを返し
   （同じトークンの同時確定でも成功するのは1回だけ）、``apply_new_password`` が
   パスワードを差し替えて既存のログイン（JWT）を失効させる。確定後は本人へ
   「パスワードが変更されました」を LINE（連携済みなら）とメールの両方で送る。

トークンの扱い:
- ``secrets.token_urlsafe(32)``（256bit）。DB には SHA-256 の16進だけを保存し、平文は
  メール本文（``notify.send_password_reset``）以外に出さない（ログ・アラートにも出さない）。
- 有効期限30分・1回限り。同一アカウントの有効な未使用トークンは最大3本まで並存させ
  （security review M-1: 新しい要求のたびに旧トークンを無効化すると、第三者の要求の連打で
  本人の手元のリンクを使えなくできた）、4本目の発行時は最古を無効化する。確定に成功したら
  同じアカウントの他の未使用トークンをすべて無効化する（``invalidate_reset_tokens``。
  パスワード変更・停止・退会でも同じ関数を呼ぶ・security review L-1）。
- 実際に発行・送信する回数は DB 基準で絞る（同 M-1。IP・アドレス軸のレート制限は
  プロセス内メモリで再起動・複数台で抜けるため、送信枠の枯渇とメール爆撃をここで止める）:
  同一アカウントへ直近2分以内に発行済みなら発行しない・直近24時間の発行が5件に達したら
  発行しない（応答はどちらも同じ 202）。使用済み・期限切れの行の掃除は24時間より古い
  ものだけにして、この集計が効くようにする（有効期限30分のため24時間より古い行は必ず
  期限切れで、1アカウントの行数は高々5行に保たれる）。
- 管理者（``role == "admin"``）は自己再設定の対象外（security review M-2）。要求は同じ 202 で
  メールを送らず、運営アラートを1通出す（本文は種別とマスク済み ID のみ）。

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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_summary import describe_exception
from app.core.security import hash_password
from app.db import session as db_session_module
from app.db.models.operator import Operator
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.user import User
from app.services import alerts, notify

logger = logging.getLogger(__name__)

#: 再設定リンクの有効期限（分）。メール本文にもこの値を載せる。
RESET_TOKEN_TTL_MINUTES = 30
#: ``secrets.token_urlsafe`` に渡すバイト数（256bit・43文字）。
RESET_TOKEN_BYTES = 32
#: 同一アカウントで並存させる有効な未使用トークンの上限（security review M-1）。
RESET_MAX_ACTIVE_TOKENS = 3
#: 同一アカウントへの再発行（＝案内メールの再送）の最小間隔。
RESET_RESEND_INTERVAL = timedelta(minutes=2)
#: 発行回数を数える窓と、その窓内の上限（Brevo 無料枠の枯渇・メール爆撃の防止）。
RESET_ISSUE_WINDOW = timedelta(hours=24)
RESET_MAX_ISSUES_PER_WINDOW = 5
#: 管理者アカウントへの再設定要求を運営へ知らせるアラートのキー（クールダウンで連打を間引く）。
_ADMIN_RESET_ALERT_KEY = "password_reset_admin_request"


@dataclass(frozen=True)
class PasswordChangeNoticeTarget:
    """再設定の確定後に「パスワードが変更されました」を送る宛先（プリミティブ値のみ）。

    BackgroundTasks はセッションを閉じた後に走るため、ORM オブジェクトではなく値で渡す。
    """

    line_user_id: str | None
    email: str | None


def hash_reset_token(raw_token: str) -> str:
    """平文トークンを保存・照合用の SHA-256 16進（64文字）にする。

    トークン自体が 256bit の乱数のため、総当たり対策の鍵伸長（scrypt 等）は不要で、
    索引で引ける決定的なハッシュにする。
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """SQLite（テスト）では tz 無しで返るため UTC として扱う（PostgreSQL は tz 付き）。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _mask_account_id(account_id: uuid.UUID) -> str:
    """アラート本文用に ID を先頭8文字へ縮める（突き合わせはログの完全な ID で行う）。"""
    return f"{str(account_id)[:8]}…"


def _account_filter(account_type: str, account_id: uuid.UUID):  # noqa: ANN202 -- SQL 式
    return (
        PasswordResetToken.account_type == account_type,
        PasswordResetToken.account_id == account_id,
    )


async def find_resettable_account(
    session: AsyncSession, account_type: str, email: str, *, lock: bool = False
) -> User | Operator | None:
    """再設定の案内を送ってよいアカウントを返す（無ければ None）。

    送らない（None を返す）もの:
    - 退会・削除済み（``deleted_at``。トムストンのメールにも一致しないが多層防御として除外）
    - 停止中（停止中はログインできず、再設定しても使えない。解除後に手続きしてもらう）
    - パスワード未設定（LINE ログイン専用。メールだけでパスワードを新設できると、
      LINE で本人確認しているアカウントの入口がメールの受信だけで増えてしまう）
    - 実在しない内部用アドレス（LINE 専用の仮メール・退会トムストン。``is_placeholder_email``）
    ``email`` は呼び出し側で小文字化済み（ログインと同じ照合）。
    管理者（role="admin"）はここでは除外しない（呼び出し側でアラートを出すため）。

    ``lock=True`` ではアカウント行を ``FOR UPDATE`` で取り、同じアカウントへの要求の
    同時処理を直列化する（直近2分・24時間の発行回数の判定と発行の間に割り込ませない。
    SQLite では無視される）。
    """
    if notify.is_placeholder_email(email):
        return None
    account: User | Operator | None
    if account_type == "user":
        user_stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        account = await session.scalar(user_stmt.with_for_update() if lock else user_stmt)
    else:
        operator_stmt = select(Operator).where(
            Operator.contact_email == email, Operator.deleted_at.is_(None)
        )
        account = await session.scalar(
            operator_stmt.with_for_update() if lock else operator_stmt
        )
    if account is None or account.is_suspended or account.password_hash is None:
        return None
    return account


async def invalidate_reset_tokens(
    session: AsyncSession, account_type: str, account_id: uuid.UUID, now: datetime
) -> None:
    """アカウントの未使用の再設定トークンをすべて無効化する（commit は呼び出し側）。

    再設定の確定・パスワード変更・停止・退会で呼ぶ（security review L-1: 手元に残った
    リンクで、変更後・停止解除後に別の人がパスワードを差し替えられないようにする）。
    行は消さずに ``used_at`` を入れる（直近24時間の発行回数の集計から外さないため）。
    """
    await session.execute(
        update(PasswordResetToken)
        .where(*_account_filter(account_type, account_id))
        .where(PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )


async def issue_reset_token(
    session: AsyncSession, account_type: str, account_id: uuid.UUID, now: datetime
) -> str | None:
    """新しいトークンを発行して平文を返す。送信を抑止すべきときは None（commit は呼び出し側）。

    1. 24時間より古い使用済み・期限切れの行を削除する（集計窓の外だけを掃除する）。
    2. 直近2分以内に発行済み、または直近24時間の発行が上限に達していれば None。
    3. 有効な未使用トークンが既に上限本あれば、新しいものを含めて上限本になるよう
       古い順に無効化する（行は消さない。消すと24時間の発行回数が減って上限を
       すり抜けられるため）。
    4. 新しい行を追加する（``created_at`` は判定と同じ ``now`` を明示して入れる）。
    索引 ``ix_password_reset_tokens_account`` でアカウントの行だけを引き、行数は高々5行。
    """
    window_start = now - RESET_ISSUE_WINDOW
    await session.execute(
        delete(PasswordResetToken)
        .where(*_account_filter(account_type, account_id))
        .where(
            PasswordResetToken.created_at < window_start,
            or_(
                PasswordResetToken.used_at.is_not(None),
                PasswordResetToken.expires_at <= now,
            ),
        )
        .execution_options(synchronize_session=False)
    )
    issued_count, last_issued_at = (
        await session.execute(
            select(func.count(), func.max(PasswordResetToken.created_at))
            .where(*_account_filter(account_type, account_id))
            .where(PasswordResetToken.created_at >= window_start)
        )
    ).one()
    if last_issued_at is not None and _as_utc(last_issued_at) > now - RESET_RESEND_INTERVAL:
        logger.info(
            "password_reset: 直近%d秒以内に発行済みのため再送しません（type=%s account_id=%s）",
            int(RESET_RESEND_INTERVAL.total_seconds()),
            account_type,
            account_id,
        )
        return None
    if int(issued_count or 0) >= RESET_MAX_ISSUES_PER_WINDOW:
        logger.warning(
            "password_reset: 24時間の発行上限（%d件）に達したため送りません（type=%s account_id=%s）",
            RESET_MAX_ISSUES_PER_WINDOW,
            account_type,
            account_id,
        )
        return None

    active_ids = list(
        (
            await session.scalars(
                select(PasswordResetToken.id)
                .where(*_account_filter(account_type, account_id))
                .where(
                    PasswordResetToken.used_at.is_(None),
                    PasswordResetToken.expires_at > now,
                )
                .order_by(PasswordResetToken.created_at.desc(), PasswordResetToken.id.desc())
            )
        ).all()
    )
    surplus_ids = active_ids[RESET_MAX_ACTIVE_TOKENS - 1 :]
    if surplus_ids:
        await session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id.in_(surplus_ids))
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
            created_at=now,
        )
    )
    return raw_token


async def _alert_admin_reset_request(account_id: uuid.UUID) -> None:
    """管理者アカウントへの再設定要求を運営へ知らせる（本文は種別とマスク済み ID のみ）。"""
    await alerts.send_alert(
        "管理者アカウントへのパスワード再設定の要求",
        "管理者アカウントはメールによるパスワード再設定の対象外のため、案内は送っていません。\n"
        f"種別=admin_password_reset_request\naccount_id={_mask_account_id(account_id)}\n"
        "心当たりがない場合は、管理者アカウントへの不正アクセスの試みの可能性があります。",
        severity="warning",
        key=_ADMIN_RESET_ALERT_KEY,
    )


async def process_reset_request(account_type: str, email: str) -> None:
    """要求の本体（応答の後にバックグラウンドで実行する）。例外は外へ出さない。

    対象アカウントがあればトークンを発行して案内メールを送る。無い・管理者・送信の抑止
    （直近2分・24時間の上限）のときは送らない。
    ログには種別・アカウント ID・送信の成否だけを出す（メールアドレス・トークンは出さない）。
    """
    try:
        session_factory = db_session_module.get_background_session_factory()
        async with session_factory() as session:
            account = await find_resettable_account(session, account_type, email, lock=True)
            if account is None:
                logger.info(
                    "password_reset: 案内の対象となるアカウントが無いため送信しません（type=%s）",
                    account_type,
                )
                return
            account_id = account.id
            if isinstance(account, User) and account.role == "admin":
                await session.rollback()
                logger.warning(
                    "password_reset: 管理者アカウントは自己再設定の対象外のため送信しません"
                    "（type=%s account_id=%s）",
                    account_type,
                    account_id,
                )
                await _alert_admin_reset_request(account_id)
                return
            to_address = account.email if isinstance(account, User) else account.contact_email
            raw_token = await issue_reset_token(
                session, account_type, account_id, datetime.now(timezone.utc)
            )
            # 抑止時も掃除（古い行の削除）を確定させる。
            await session.commit()
        if raw_token is None:
            return
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
) -> PasswordChangeNoticeTarget | None:
    """パスワードを差し替え、既存のログインを失効させる（commit は呼び出し側）。

    発行後に退会・停止・LINE 専用化・管理者化（通常は起きない）したアカウントは None を
    返して何も変えない。成功時は同じアカウントの他の未使用トークンも無効化し、
    「パスワードが変更されました」の通知先（LINE・メール）を返す。
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
        or (isinstance(account, User) and account.role == "admin")
    ):
        return None

    account.password_hash = hash_password(new_password)
    email: str | None
    if isinstance(account, User):
        account.password_changed_at = now
        email = account.email
    else:
        account.sessions_revoked_at = now
        email = account.contact_email
    await invalidate_reset_tokens(session, account_type, account_id, now)
    return PasswordChangeNoticeTarget(line_user_id=account.line_user_id, email=email)
