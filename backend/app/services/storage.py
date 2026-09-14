"""写真ストレージ — 公開ファサード（差し替え可能なバックエンド: ローカルディスク / R2）。

クローズドβはゼロコスト方針でローカルディスク保存から開始したが、Render の
エフェメラルディスクはデプロイの度に写真が消えるため、Cloudflare R2（S3 互換
オブジェクトストレージ）へ移行可能にする。presign → PUT /upload/{key} →
GET /files/{key} の 3 段構成という HTTP 契約は一切変えない。

storage_key は UUID hex + 拡張子のみ許可（パストラバーサル防止）。

本モジュールは「検証・キー生成・URL生成・ログマスク・content_type解決」を
担う純関数群と、I/O（保存・取得・削除）を実際に行うバックエンド
（:mod:`app.services.storage_backends`）への薄い委譲窓口の2層で構成される。
バックエンドの選択・実装詳細は ``storage_backends`` パッケージへ隠蔽し、
本モジュールの公開シグネチャ（呼び出し元からの import パス）は維持する。
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from app.services.storage_backends import (
    ObjectExistsError,
    StorageUnavailableError,
    get_backend,
)

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^[a-f0-9]{32}\.(jpg|jpeg|png|webp)$")

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

_CONTENT_TYPE_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

_ALLOWED_CONTENT_TYPES = frozenset(_CONTENT_TYPE_BY_EXT.values())

_DEFAULT_CONTENT_TYPE = "application/octet-stream"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB

# StorageUnavailableError を呼び出し元（case_photos.py 等）が個別に import
# せずに済むよう、façade からも再エクスポートする。
__all__ = [
    "MAX_UPLOAD_BYTES",
    "StorageKeyConflictError",
    "StorageUnavailableError",
    "StoredObject",
    "backend_name",
    "content_type_for_key",
    "delete_bytes",
    "exists",
    "is_valid_key",
    "mask_key_for_log",
    "new_storage_key",
    "public_url",
    "read_bytes",
    "reset_backend_cache",
    "save_bytes",
    "sniff_image_ext",
    "upload_url",
]


class StorageKeyConflictError(Exception):
    """既に存在する storage_key への上書きアップロードを示す例外。

    presign が発行する storage_key は毎回新規の UUID hex のため、正規の
    フローでは同一キーへの2回目の PUT は本来発生しない。発生した場合は
    レースコンディション（同一キーの推測・使い回し）の可能性があるため、
    上書きを許さず 409 Conflict として拒否する（security review 指摘対応）。
    """


@dataclass(frozen=True, slots=True)
class StoredObject:
    """取得済みの写真オブジェクト。"""

    data: bytes
    content_type: str  # 必ず image/jpeg|image/png|image/webp のいずれか


def new_storage_key(content_type: str) -> str:
    """content_type から安全な storage_key を生成する。"""
    ext = _EXT_BY_CONTENT_TYPE.get(content_type)
    if ext is None:
        # 呼び出し元（case_photos.presign）は本文言をそのまま 422 detail として
        # 返し、web が画面表示する。ユーザー入力（content_type）は反射せず、
        # 対応形式の提示のみを返す（r8-H4）。
        raise ValueError(
            "この形式の画像には対応していません。JPEG・PNG・WebP のいずれかを選択してください。"
        )
    return f"{uuid.uuid4().hex}.{ext}"


def is_valid_key(storage_key: str) -> bool:
    # fullmatch を使う（match + $ 終端だと末尾に改行(\n)が付与された文字列も
    # マッチしてしまう。$ は文字列末尾の改行の直前にもマッチするため。
    # security review 指摘対応・Low）。
    return bool(_KEY_RE.fullmatch(storage_key))


def content_type_for_key(storage_key: str) -> str:
    """storage_key の拡張子から MIME タイプを導出する。既定は application/octet-stream。"""
    ext = storage_key.rsplit(".", 1)[-1].lower() if "." in storage_key else ""
    return _CONTENT_TYPE_BY_EXT.get(ext, _DEFAULT_CONTENT_TYPE)


def backend_name() -> str:
    """現在有効なストレージバックエンド名（"local" | "r2"）。秘密値は含まない。"""
    return get_backend().name


def reset_backend_cache() -> None:
    """バックエンド解決キャッシュを破棄する（テスト専用）。"""
    get_backend.cache_clear()


async def save_bytes(storage_key: str, data: bytes) -> None:
    if not is_valid_key(storage_key):
        raise ValueError("storage_key が不正です")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("ファイルサイズが上限（10MB）を超えています。")
    try:
        await get_backend().put(storage_key, data, content_type_for_key(storage_key))
    except ObjectExistsError as exc:
        # 既存ファイルへの上書きを禁止する（security review 指摘対応）。presign が
        # 都度新規UUIDを発行する設計上、正規フローでは同一キーへの2回目のPUTは
        # 発生しない。発生した場合は先行アップロード済みファイルの意図しない
        # 差し替え（レースコンディション・キーの使い回し）の可能性があるため、
        # 409 Conflict として拒否する（呼び出し元でHTTPExceptionへ変換すること）。
        raise StorageKeyConflictError(
            "この storage_key は既にアップロード済みです。presign からやり直してください。"
        ) from exc


async def read_bytes(storage_key: str) -> StoredObject | None:
    """保存済みオブジェクトを返す。未保存・不正キーは None。

    ストレージ側の到達不能（接続不可等）は ``StorageUnavailableError`` を
    送出する（None にしない。理由: R2 障害を「写真が存在しない」と誤認させず、
    フロントで写真無し案件として描画されて障害が見えなくなる事故を防ぐため）。
    """
    if not is_valid_key(storage_key):
        return None
    result = await get_backend().get(storage_key)
    if result is None:
        return None
    data, stored_content_type = result
    # R2 オブジェクトメタデータ（content_type）をそのまま信用しない。将来の
    # 格納経路混入によるXSS対策として許可リストで照合し、外れたら
    # content_type_for_key() にフォールバックする（ローカルバックエンドは
    # 常にこちらのフォールバック経路を通る）。
    if stored_content_type in _ALLOWED_CONTENT_TYPES:
        content_type = stored_content_type
    else:
        content_type = content_type_for_key(storage_key)
    return StoredObject(data=data, content_type=content_type)


async def exists(storage_key: str) -> bool:
    """保存済みかどうかを返す（R2 では HEAD 相当。本体は取得しない）。"""
    if not is_valid_key(storage_key):
        return False
    return await get_backend().head(storage_key)


def mask_key_for_log(storage_key: str) -> str:
    """ログ出力用に storage_key を丸める（先頭8文字＋"..."）。

    security review 指摘対応（L-2）: ``GET /files/{storage_key}`` は無認証の
    capability URL（storage_key を知っていれば誰でも画像本体を取得できる）
    のため、storage_key を平文でログに残すと、本来アプリケーションの認可
    チェックを経ないと閲覧できないはずの写真へ、ログ閲覧権限者がそのまま
    アクセスできてしまう。先頭8文字（当該32文字hexの約1/4）のみを残すことで、
    ログ相関（同一キーの追跡）に必要な最低限の情報は保ちつつ、丸めた文字列
    単体からの総当たり再構成コストを引き上げる。
    """
    if not storage_key:
        return storage_key
    return f"{storage_key[:8]}..."


async def delete_bytes(storage_key: str) -> None:
    """保存済みファイルを削除する（冪等・ベストエフォート）。

    不正な storage_key（``is_valid_key`` に反する形式）は無視する
    （パストラバーサル等の危険な入力をそのままバックエンドへ渡さないため）。
    存在しないファイルはエラーにしない（既に削除済み・未アップロードの
    ケースも呼び出し元がエラーハンドリングなしで安全に呼べるようにする）。
    ストレージ側の例外は warning ログの記録に留め、送出しない（DB側の削除
    （コミット）は既に完了している前提で呼ばれるため、ストレージ削除の
    失敗で API レスポンス自体を失敗させない設計）。
    """
    if not is_valid_key(storage_key):
        logger.warning(
            "storage.delete_bytes: 不正な storage_key を無視 - %s",
            mask_key_for_log(storage_key),
        )
        return
    try:
        await get_backend().delete(storage_key)
    except Exception:  # noqa: BLE001 - ベストエフォート削除。呼び出し元へ伝播させない。
        logger.warning(
            "storage.delete_bytes: ファイル削除に失敗（無視して続行） - key=%s",
            mask_key_for_log(storage_key),
            exc_info=True,
        )


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
