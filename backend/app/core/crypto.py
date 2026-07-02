"""機微データ（振込先口座情報等）の対称鍵暗号化ユーティリティ。

``cryptography`` の ``Fernet``（AES-128-CBC + HMAC-SHA256）を用いる。
鍵は環境変数 ``APP_ENCRYPTION_KEY``（``config.Settings.app_encryption_key``）から読む。

暗号化必須の機微データ（銀行口座番号等）を扱うため、鍵が未設定の場合は
``notify.py`` のようにログのみで処理を継続せず、起動直後の初回呼び出し時点で
例外を送出してプロセスを止める（鍵欠如を握りつぶすと平文保存に繋がり危険なため）。
"""

from __future__ import annotations

import json
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)


class EncryptionKeyMissingError(RuntimeError):
    """APP_ENCRYPTION_KEY が未設定、または不正な形式のときに送出する。"""


class DecryptionFailedError(RuntimeError):
    """暗号文の復号に失敗したときに送出する（鍵不一致・改ざん等）。"""


def _get_fernet() -> Fernet:
    settings = get_settings()
    key = settings.app_encryption_key
    if not key:
        logger.error("crypto: APP_ENCRYPTION_KEY が未設定です。機微データの暗号化ができません。")
        raise EncryptionKeyMissingError(
            "APP_ENCRYPTION_KEY が設定されていません。"
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "で鍵を生成し、環境変数に設定してください。"
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.error("crypto: APP_ENCRYPTION_KEY の形式が不正です - %s", exc)
        raise EncryptionKeyMissingError(
            "APP_ENCRYPTION_KEY の形式が不正です（urlsafe base64 32byte を想定）。"
        ) from exc


def encrypt_json(data: dict) -> str:
    """dict を JSON 直列化した上で Fernet 暗号化し、トークン文字列を返す。"""
    fernet = _get_fernet()
    plaintext = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = fernet.encrypt(plaintext)
    return token.decode("utf-8")


def decrypt_json(token: str) -> dict:
    """Fernet 暗号文トークンを復号し、dict として返す。"""
    fernet = _get_fernet()
    try:
        plaintext = fernet.decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        logger.error("crypto: 復号に失敗しました（鍵不一致または改ざんの可能性）")
        raise DecryptionFailedError("暗号文の復号に失敗しました。") from exc
    return json.loads(plaintext.decode("utf-8"))
