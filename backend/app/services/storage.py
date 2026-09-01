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


class StorageKeyConflictError(Exception):
    """既に存在する storage_key への上書きアップロードを示す例外。

    presign が発行する storage_key は毎回新規の UUID hex のため、正規の
    フローでは同一キーへの2回目の PUT は本来発生しない。発生した場合は
    レースコンディション（同一キーの推測・使い回し）の可能性があるため、
    上書きを許さず 409 Conflict として拒否する（security review 指摘対応）。
    """


def new_storage_key(content_type: str) -> str:
    """content_type から安全な storage_key を生成する。"""
    ext = _EXT_BY_CONTENT_TYPE.get(content_type)
    if ext is None:
        raise ValueError(f"未対応の content_type です: {content_type}")
    return f"{uuid.uuid4().hex}.{ext}"


def is_valid_key(storage_key: str) -> bool:
    # fullmatch を使う（match + $ 終端だと末尾に改行(\n)が付与された文字列も
    # マッチしてしまう。$ は文字列末尾の改行の直前にもマッチするため。
    # security review 指摘対応・Low）。
    return bool(_KEY_RE.fullmatch(storage_key))


def _storage_root() -> Path:
    root = Path(get_settings().storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_bytes(storage_key: str, data: bytes) -> None:
    if not is_valid_key(storage_key):
        raise ValueError("storage_key が不正です")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("ファイルサイズが上限（10MB）を超えています")
    path = _storage_root() / storage_key
    # 既存ファイルへの上書きを禁止する（security review 指摘対応）。presign が
    # 都度新規UUIDを発行する設計上、正規フローでは同一キーへの2回目のPUTは
    # 発生しない。発生した場合は先行アップロード済みファイルの意図しない
    # 差し替え（レースコンディション・キーの使い回し）の可能性があるため、
    # 409 Conflict として拒否する（呼び出し元でHTTPExceptionへ変換すること）。
    if path.exists():
        raise StorageKeyConflictError(
            "この storage_key は既にアップロード済みです。presign からやり直してください。"
        )
    path.write_bytes(data)


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


# ──────────────────────────── マジックバイト判定 ────────────────────────────
# Content-Type ヘッダ・ファイル拡張子はクライアントが自由に詐称できるため、
# 審査書類（許可証画像）等の機微度が高いアップロードでは実バイト列の先頭
# シグネチャで形式を判定する（storage_key ベースの presign 方式とは別関心）。

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_RIFF_MAGIC = b"RIFF"
_WEBP_MAGIC = b"WEBP"


def sniff_image_ext(data: bytes) -> str | None:
    """実バイト列の先頭シグネチャから画像形式を判定する（jpeg/png/webpのみ許可）。

    Content-Type・拡張子は一切信用しない。判定できない場合は None を返し、
    呼び出し元で 415 Unsupported Media Type とすること。
    """
    if data.startswith(_JPEG_MAGIC):
        return "jpeg"
    if data.startswith(_PNG_MAGIC):
        return "png"
    if len(data) >= 12 and data[0:4] == _RIFF_MAGIC and data[8:12] == _WEBP_MAGIC:
        return "webp"
    return None
