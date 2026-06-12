"""写真ストレージ — バックエンド内蔵のローカルディスク保存。

クローズドβはゼロコスト方針のため外部オブジェクトストレージを使わず、
presign → PUT /upload/{key} → GET /files/{key} の 3 段で完結させる。
storage_key は UUID hex + 拡張子のみ許可（パストラバーサル防止）。
R2 / S3 へ移行する場合は presign_upload() の返却 URL を差し替えるだけでよい。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import get_settings

_KEY_RE = re.compile(r"^[a-f0-9]{32}\.(jpg|jpeg|png|webp)$")

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB


def new_storage_key(content_type: str) -> str:
    """content_type から安全な storage_key を生成する。"""
    ext = _EXT_BY_CONTENT_TYPE.get(content_type)
    if ext is None:
        raise ValueError(f"未対応の content_type です: {content_type}")
    return f"{uuid.uuid4().hex}.{ext}"


def is_valid_key(storage_key: str) -> bool:
    return bool(_KEY_RE.match(storage_key))


def _storage_root() -> Path:
    root = Path(get_settings().storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_bytes(storage_key: str, data: bytes) -> None:
    if not is_valid_key(storage_key):
        raise ValueError("storage_key が不正です")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("ファイルサイズが上限（10MB）を超えています")
    (_storage_root() / storage_key).write_bytes(data)


def file_path(storage_key: str) -> Path | None:
    """保存済みファイルの Path を返す。未保存・不正キーは None。"""
    if not is_valid_key(storage_key):
        return None
    path = _storage_root() / storage_key
    return path if path.is_file() else None


def public_url(storage_key: str) -> str:
    """クライアントが参照する URL（API 相対パス）。"""
    return f"/api/v1/files/{storage_key}"


def upload_url(storage_key: str) -> str:
    return f"/api/v1/upload/{storage_key}"
