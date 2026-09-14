"""Cloudflare R2（S3 互換 API）への写真保存バックエンド。

boto3 は同期クライアントのため、全メソッドを ``asyncio.to_thread`` でスレッドへ
逃がして呼び出す。R2 未設定（クレデンシャル無し）の環境では
``storage_backends.get_backend()`` がそもそも本バックエンドを選ばないため、
本モジュールが import されるだけでは失敗しない（``boto3`` の import 自体は
必須依存として requirements に含める）。
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.services.storage_backends.base import ObjectExistsError, StorageUnavailableError

logger = logging.getLogger(__name__)

# put_object の条件付き書き込み（If-None-Match）が未対応のプロバイダを検出した
# 場合に翻訳するエラーコード（S3 互換実装により表現がまちまちなため複数許容）。
_PRECONDITION_FAILED_CODES = {"PreconditionFailed"}
_PRECONDITION_FAILED_STATUSES = {412, 409}
_NOT_IMPLEMENTED_CODES = {"NotImplemented"}
# ``NotFound`` は head_object の404がボディ無しのため Code が "404" 文字列で
# 返ってくる実装がある（get_object/head_object の両経路をこれでカバーする）。
_NOT_FOUND_CODES = frozenset({"NoSuchKey", "404", "NotFound"})
# security review 指摘対応: バケット誤設定・認証エラーは HTTP ステータスとの
# OR 判定にすると 404 系ステータスと衝突し「存在しない」に誤分類されうる
# （例: 一部プロキシ・WAF が認証エラーを 404 として転送するケース）。これらは
# 明示的に「not found ではない」として除外し、それ以外は Error.Code ベースの
# みで判定する（HTTP ステータスとの OR 判定はしない）。
_NOT_NOT_FOUND_CODES = frozenset(
    {"NoSuchBucket", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}
)

_ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def _status_code(exc: ClientError) -> int | None:
    return exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


def _error_code(exc: ClientError) -> str | None:
    return exc.response.get("Error", {}).get("Code")


def _is_precondition_failed(exc: ClientError) -> bool:
    return (
        _error_code(exc) in _PRECONDITION_FAILED_CODES
        or _status_code(exc) in _PRECONDITION_FAILED_STATUSES
    )


def _is_not_implemented(exc: ClientError) -> bool:
    # security review 指摘対応: 中間プロキシ由来の 501 を条件付き書き込み未対応と
    # 誤判定しないよう、HTTP ステータスとの OR 判定をやめ Error.Code ベースのみで
    # 判定する。
    return _error_code(exc) in _NOT_IMPLEMENTED_CODES


def _is_not_found(exc: ClientError) -> bool:
    code = _error_code(exc)
    if code in _NOT_NOT_FOUND_CODES:
        return False
    return code in _NOT_FOUND_CODES


@lru_cache(maxsize=1)
def _get_client():  # noqa: ANN201 - boto3 client の型はスタブ非提供
    """boto3 S3 互換クライアントを1個だけ生成してキャッシュする。

    ``storage_backends.r2._get_client`` はテストから ``monkeypatch`` で
    直接差し替える前提の名前（設計書 §10 参照）。
    """
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        region_name="auto",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
        config=Config(
            connect_timeout=settings.r2_connect_timeout_seconds,
            read_timeout=settings.r2_read_timeout_seconds,
            retries={"max_attempts": settings.r2_max_attempts, "mode": "standard"},
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_supported",
        ),
    )


@lru_cache(maxsize=1)
def _get_read_semaphore() -> asyncio.Semaphore:
    """R2 からの同時 GET 数を絞るセマフォ（プロセス内で共有・1個のみ生成）。"""
    return asyncio.Semaphore(get_settings().storage_max_concurrent_reads)


class R2Backend:
    """Cloudflare R2（S3 互換 API）バックエンド。"""

    name = "r2"

    @staticmethod
    def _full_key(key: str) -> str:
        return f"{get_settings().r2_key_prefix}{key}"

    def _sync_put(self, key: str, data: bytes, content_type: str) -> None:
        """新規オブジェクトを保存する（``IfNoneMatch="*"`` による上書き禁止）。

        R2/S3 互換プロバイダが条件付き書き込み（If-None-Match）を未対応
        （``NotImplemented``/501）と返した場合は、``head_object`` による事前
        存在確認 → 非条件付き ``put_object`` の2段構成へ自動退避する
        （設計書 §2.6。厳密な原子性は失うが、正規フローで同一キーへの
        2回目の PUT は本来発生しない前提のため許容する）。
        """
        client = _get_client()
        bucket = get_settings().r2_bucket
        full_key = self._full_key(key)
        try:
            client.put_object(
                Bucket=bucket,
                Key=full_key,
                Body=data,
                ContentType=content_type,
                IfNoneMatch="*",
            )
            return
        except ClientError as exc:
            if _is_precondition_failed(exc):
                raise ObjectExistsError(f"storage_key は既にアップロード済みです: {key}") from exc
            if not _is_not_implemented(exc):
                raise StorageUnavailableError("R2 put_object に失敗しました") from exc
            logger.warning(
                "R2Backend.put: IfNoneMatch 条件付き書き込みが未対応のため "
                "head_object 事前確認方式へ退避します。"
            )
        except BotoCoreError as exc:
            raise StorageUnavailableError("R2 に接続できませんでした") from exc

        # ここに到達するのは IfNoneMatch 未対応（NotImplemented/501）の場合のみ。
        try:
            client.head_object(Bucket=bucket, Key=full_key)
        except ClientError as head_exc:
            if not _is_not_found(head_exc):
                raise StorageUnavailableError("R2 head_object に失敗しました") from head_exc
        except BotoCoreError as head_exc:
            raise StorageUnavailableError("R2 に接続できませんでした") from head_exc
        else:
            raise ObjectExistsError(f"storage_key は既にアップロード済みです: {key}")

        try:
            client.put_object(Bucket=bucket, Key=full_key, Body=data, ContentType=content_type)
        except ClientError as exc:
            raise StorageUnavailableError("R2 put_object に失敗しました") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError("R2 に接続できませんでした") from exc

    def _sync_get(self, key: str) -> tuple[bytes, str | None] | None:
        client = _get_client()
        full_key = self._full_key(key)
        try:
            response = client.get_object(Bucket=get_settings().r2_bucket, Key=full_key)
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise StorageUnavailableError("R2 get_object に失敗しました") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError("R2 に接続できませんでした") from exc
        body = response["Body"].read()
        content_type = response.get("ContentType")
        return body, content_type

    def _sync_head(self, key: str) -> bool:
        client = _get_client()
        try:
            client.head_object(Bucket=get_settings().r2_bucket, Key=self._full_key(key))
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise StorageUnavailableError("R2 head_object に失敗しました") from exc
        except BotoCoreError as exc:
            raise StorageUnavailableError("R2 に接続できませんでした") from exc
        return True

    def _sync_delete(self, key: str) -> None:
        client = _get_client()
        try:
            client.delete_object(Bucket=get_settings().r2_bucket, Key=self._full_key(key))
        except Exception:  # noqa: BLE001 - 冪等・ベストエフォート。呼び出し元へ伝播させない。
            logger.warning(
                "R2Backend.delete: オブジェクト削除に失敗（無視して続行）", exc_info=True
            )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._sync_put, key, data, content_type)

    async def get(self, key: str) -> tuple[bytes, str | None] | None:
        async with _get_read_semaphore():
            return await asyncio.to_thread(self._sync_get, key)

    async def head(self, key: str) -> bool:
        # get() と同じ読み出しセマフォを通す（security review 指摘対応・Low）。
        # head() は認証・レート制限の無い GET /files/{key} の 304 判定経路から
        # 呼ばれるため、get() 同様に同時実行数を絞らないとスレッドプール飽和の
        # 経路になり得る。
        async with _get_read_semaphore():
            return await asyncio.to_thread(self._sync_head, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._sync_delete, key)
