"""パスワードハッシュ（stdlib scrypt）と JWT（PyJWT / HS256）。

外部依存を最小化するため bcrypt ではなく hashlib.scrypt を採用する。
フォーマット: "scrypt$<salt_hex>$<hash_hex>"（N=2^14, r=8, p=1）。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt

from app.config import get_settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

TokenType = Literal["user", "operator"]


def hash_password(password: str) -> str:
    """平文パスワードを scrypt でハッシュ化して保存形式の文字列を返す。"""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """保存形式の文字列と平文を比較する（定数時間比較）。"""
    try:
        algo, salt_hex, hash_hex = stored.split("$", 2)
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def create_access_token(
    subject_id: uuid.UUID,
    token_type: TokenType,
    role: str,
    expires_minutes: int | None = None,
) -> str:
    """JWT を発行する。payload: sub / typ / role / exp / iat。"""
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject_id),
        "typ": token_type,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """JWT を検証してペイロードを返す。不正・期限切れは jwt.PyJWTError を送出。"""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


# ──────────────────────────── 再認証トークン（LINE連携専用） ────────────────────────────
# パスワード設定済みアカウントが LINE 連携を新規に「付与」する際の再認証に使う
# 短命トークン。通常の access_token（"typ"="user"/"operator"）とはクレーム体系を
# 分離し、"purpose" クレームを持たせることで get_current_user 等の通常認証ゲートを
# 誤って通過できないようにする（用途限定トークン）。
#
# "typ"（"user"/"operator"）は通常の access_token と同じクレーム名で持たせる。
# user 用・operator 用の再認証トークンはどちらも purpose="line_link" で
# 見分けが付かないため、"typ" を必須検証項目に加えることで、user が発行した
# reauth_token を operator 側の line_exchange に流用する（またはその逆）
# アカウント種別跨ぎの誤通過を構造的に防ぐ（security review H-1対応）。

REAUTH_PURPOSE_LINE_LINK = "line_link"
REAUTH_TOKEN_EXPIRE_MINUTES = 5


def create_reauth_token(subject_id: uuid.UUID, subject_type: TokenType) -> str:
    """LINE連携の再認証用トークンを発行する（有効期限5分・purpose="line_link"）。

    payload: sub / typ / purpose / iat / exp。
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject_id),
        "typ": subject_type,
        "purpose": REAUTH_PURPOSE_LINE_LINK,
        "iat": now,
        "exp": now + timedelta(minutes=REAUTH_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
