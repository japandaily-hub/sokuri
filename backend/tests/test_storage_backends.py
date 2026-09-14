"""app.services.storage_backends.r2 の単体テスト。

moto は使わず、dict を裏に持つ手書きフェイク client
（``storage_backends.r2._get_client`` を monkeypatch で差し替える）で検証する。
エラーは本物の ``botocore.exceptions.ClientError`` / ``EndpointConnectionError``
を送出させ、R2Backend 側の翻訳ロジック（ObjectExistsError /
StorageUnavailableError への変換）が正しく動くことを確認する。
"""

from __future__ import annotations

import io

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.services import storage
from app.services.storage_backends import r2 as r2_module
from app.services.storage_backends.base import ObjectExistsError, StorageUnavailableError
from app.services.storage_backends.r2 import R2Backend


def _client_error(code: str, status_code: int, operation: str = "Operation") -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status_code}},
        operation,
    )


class FakeR2Client:
    """boto3 S3 クライアントの最小フェイク（dict を裏に持つ）。"""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.if_none_match_unsupported = False
        self.delete_raises: Exception | None = None
        self.connection_unavailable = False
        # 特定のエラー（NoSuchBucket/AccessDenied 等）を強制的に送出させ、
        # R2Backend 側の「not found ではない」判定（_is_not_found）の分岐を
        # 検証するためのフック。None のときは通常の存在有無ロジックを使う。
        self.get_object_raises: ClientError | None = None
        self.head_object_raises: ClientError | None = None

    def _maybe_raise_connection_error(self) -> None:
        if self.connection_unavailable:
            raise EndpointConnectionError(endpoint_url="https://example.r2.cloudflarestorage.com")

    def put_object(self, *, Bucket, Key, Body, ContentType, IfNoneMatch=None, **_kw):  # noqa: N803
        self._maybe_raise_connection_error()
        if IfNoneMatch == "*":
            if self.if_none_match_unsupported:
                raise _client_error("NotImplemented", 501, "PutObject")
            if Key in self.objects:
                raise _client_error("PreconditionFailed", 412, "PutObject")
        self.objects[Key] = {"Body": Body, "ContentType": ContentType}

    def get_object(self, *, Bucket, Key, **_kw):  # noqa: N803
        self._maybe_raise_connection_error()
        if self.get_object_raises is not None:
            raise self.get_object_raises
        obj = self.objects.get(Key)
        if obj is None:
            raise _client_error("NoSuchKey", 404, "GetObject")
        return {"Body": io.BytesIO(obj["Body"]), "ContentType": obj["ContentType"]}

    def head_object(self, *, Bucket, Key, **_kw):  # noqa: N803
        self._maybe_raise_connection_error()
        if self.head_object_raises is not None:
            raise self.head_object_raises
        if Key not in self.objects:
            raise _client_error("404", 404, "HeadObject")
        return {}

    def delete_object(self, *, Bucket, Key, **_kw):  # noqa: N803
        self._maybe_raise_connection_error()
        if self.delete_raises is not None:
            raise self.delete_raises
        self.objects.pop(Key, None)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeR2Client:
    client = FakeR2Client()
    monkeypatch.setattr(r2_module, "_get_client", lambda: client)
    return client


@pytest.fixture
def r2_settings(monkeypatch: pytest.MonkeyPatch):
    """R2 用の設定値（バケット・キープレフィックス）をテスト用に固定する。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "r2_bucket", "test-bucket")
    monkeypatch.setattr(settings, "r2_key_prefix", "case-photos/")
    return settings


@pytest.fixture
def backend(fake_client: FakeR2Client, r2_settings) -> R2Backend:
    return R2Backend()


# ──────────────────────────── put/get ラウンドトリップ ────────────────────────────


async def test_put_get_roundtrip_bytes_and_content_type_match(
    backend: R2Backend, fake_client: FakeR2Client
):
    await backend.put("abc123.jpg", b"hello-bytes", "image/jpeg")
    result = await backend.get("abc123.jpg")
    assert result is not None
    data, content_type = result
    assert data == b"hello-bytes"
    assert content_type == "image/jpeg"


async def test_put_prefixes_key_with_r2_key_prefix(
    backend: R2Backend, fake_client: FakeR2Client
):
    await backend.put("abc123.jpg", b"hello-bytes", "image/jpeg")
    assert "case-photos/abc123.jpg" in fake_client.objects
    assert "abc123.jpg" not in fake_client.objects


async def test_put_duplicate_key_raises_conflict(backend: R2Backend):
    await backend.put("dup.jpg", b"first", "image/jpeg")
    with pytest.raises(ObjectExistsError):
        await backend.put("dup.jpg", b"second", "image/jpeg")


async def test_put_falls_back_to_head_object_when_if_none_match_not_implemented(
    backend: R2Backend, fake_client: FakeR2Client
):
    fake_client.if_none_match_unsupported = True
    # 新規キーへの put は head_object 事前確認 → 通常 put_object で成功する。
    await backend.put("legacy.jpg", b"data", "image/jpeg")
    result = await backend.get("legacy.jpg")
    assert result is not None
    assert result[0] == b"data"

    # 既存キーへの再 put は head_object が存在確認するため ObjectExistsError になる。
    with pytest.raises(ObjectExistsError):
        await backend.put("legacy.jpg", b"other", "image/jpeg")


async def test_get_missing_key_returns_none(backend: R2Backend):
    assert await backend.get("does-not-exist.jpg") is None


async def test_head_true_and_false(backend: R2Backend):
    assert await backend.head("nope.jpg") is False
    await backend.put("present.jpg", b"data", "image/jpeg")
    assert await backend.head("present.jpg") is True


async def test_delete_missing_key_does_not_raise(backend: R2Backend):
    await backend.delete("nope.jpg")  # 例外を投げない


async def test_delete_swallows_client_error(backend: R2Backend, fake_client: FakeR2Client):
    fake_client.delete_raises = _client_error("InternalError", 500, "DeleteObject")
    await backend.delete("whatever.jpg")  # 例外が漏れない


# ──────────────────────────── 接続不能 ────────────────────────────


async def test_put_raises_storage_unavailable_on_connection_error(
    backend: R2Backend, fake_client: FakeR2Client
):
    fake_client.connection_unavailable = True
    with pytest.raises(StorageUnavailableError):
        await backend.put("abc.jpg", b"data", "image/jpeg")


async def test_get_raises_storage_unavailable_on_connection_error(
    backend: R2Backend, fake_client: FakeR2Client
):
    fake_client.connection_unavailable = True
    with pytest.raises(StorageUnavailableError):
        await backend.get("abc.jpg")


# ──────────────────────────── storage façade 経由の検証 ────────────────────────────
#
# app.services.storage は import 時に ``from app.services.storage_backends import
# get_backend`` でシンボルを束縛しているため、バックエンド差し替えは
# ``storage.get_backend`` を直接 monkeypatch する（storage_backends 側の
# get_backend を差し替えても storage.py 側の束縛済み参照には反映されない）。


@pytest.fixture
def patched_r2_backend(
    backend: R2Backend, monkeypatch: pytest.MonkeyPatch
) -> R2Backend:
    monkeypatch.setattr(storage, "get_backend", lambda: backend)
    return backend


async def test_storage_save_bytes_and_read_bytes_via_r2_backend(
    patched_r2_backend: R2Backend, fake_client: FakeR2Client
):
    """storage.py のファサード経由でも R2Backend が使われれば同じ契約で動く。"""
    key = "0123456789abcdef0123456789abcdef.jpg"
    await storage.save_bytes(key, b"\xff\xd8\xff\xe0fakejpegbytes")
    obj = await storage.read_bytes(key)
    assert obj is not None
    assert obj.data == b"\xff\xd8\xff\xe0fakejpegbytes"
    assert obj.content_type == "image/jpeg"
    assert await storage.exists(key) is True

    await storage.delete_bytes(key)
    assert await storage.exists(key) is False


async def test_storage_read_bytes_falls_back_when_stored_content_type_is_unsafe(
    patched_r2_backend: R2Backend, fake_client: FakeR2Client
):
    """R2 オブジェクトメタデータの ContentType が image/* 以外（例: text/html）
    でも、storage.read_bytes は許可リスト外を content_type_for_key() の
    フォールバックへ倒す（XSS 回帰テスト）。
    """
    key = f"{'c' * 32}.jpg"
    fake_client.objects[f"case-photos/{key}"] = {
        "Body": b"<script>alert(1)</script>",
        "ContentType": "text/html",
    }
    obj = await storage.read_bytes(key)
    assert obj is not None
    assert obj.content_type == "image/jpeg"
    assert obj.data == b"<script>alert(1)</script>"


async def test_storage_save_bytes_invalid_key_never_reaches_backend(
    patched_r2_backend: R2Backend, fake_client: FakeR2Client
):
    with pytest.raises(ValueError):
        await storage.save_bytes("../../etc/passwd", b"data")
    with pytest.raises(ValueError):
        await storage.save_bytes("has\nnewline.jpg", b"data")
    assert fake_client.objects == {}


async def test_storage_save_bytes_rejects_over_max_upload_bytes(
    patched_r2_backend: R2Backend, fake_client: FakeR2Client
):
    key = "fedcba9876543210fedcba9876543210.jpg"
    too_large = b"a" * (storage.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ValueError):
        await storage.save_bytes(key, too_large)
    assert fake_client.objects == {}


async def test_storage_save_bytes_via_r2_raises_storage_unavailable(
    patched_r2_backend: R2Backend, fake_client: FakeR2Client
):
    fake_client.connection_unavailable = True
    key = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg"
    with pytest.raises(StorageUnavailableError):
        await storage.save_bytes(key, b"data")


async def test_storage_read_bytes_via_r2_raises_storage_unavailable(
    patched_r2_backend: R2Backend, fake_client: FakeR2Client
):
    fake_client.connection_unavailable = True
    key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg"
    with pytest.raises(StorageUnavailableError):
        await storage.read_bytes(key)


# ──────────────────────────── バケット誤設定・認証エラーの誤分類防止 ────────────────────────────
#
# security review 2回目レビュー指摘対応（Low）: NoSuchBucket / AccessDenied は
# HTTPStatusCode こそ 404 相当だが「存在しない」ではなく「そもそも到達・認可
# できていない」障害であり、_is_not_found() は Error.Code ベースで
# 明示的に除外している（_NOT_NOT_FOUND_CODES）。この分岐がリグレッションで
# 壊れると R2 の設定ミス・認証切れが静かに「写真無し（False/None）」へ
# 縮退してしまうため、専用テストで固定する。


async def test_head_raises_storage_unavailable_on_no_such_bucket(
    backend: R2Backend, fake_client: FakeR2Client
):
    fake_client.head_object_raises = _client_error("NoSuchBucket", 404, "HeadObject")
    with pytest.raises(StorageUnavailableError):
        await backend.head("whatever.jpg")


async def test_get_raises_storage_unavailable_on_access_denied(
    backend: R2Backend, fake_client: FakeR2Client
):
    fake_client.get_object_raises = _client_error("AccessDenied", 404, "GetObject")
    with pytest.raises(StorageUnavailableError):
        await backend.get("whatever.jpg")


async def test_get_missing_key_no_such_key_returns_none_explicit(
    backend: R2Backend, fake_client: FakeR2Client
):
    """get_object が明示的に NoSuchKey を返す場合、get() は None を返す
    （バケット誤設定・認証エラー系との区別を明確にするための回帰テスト）。
    """
    fake_client.get_object_raises = _client_error("NoSuchKey", 404, "GetObject")
    assert await backend.get("whatever.jpg") is None


async def test_put_fallback_head_object_no_such_bucket_raises_storage_unavailable(
    backend: R2Backend, fake_client: FakeR2Client
):
    """IfNoneMatch 未対応（NotImplemented）フォールバック中の head_object が
    NoSuchBucket を返す場合、「存在しない（ObjectExistsError を送出しない）」
    ではなく StorageUnavailableError として伝播すること。
    """
    fake_client.if_none_match_unsupported = True
    fake_client.head_object_raises = _client_error("NoSuchBucket", 404, "HeadObject")
    with pytest.raises(StorageUnavailableError):
        await backend.put("legacy.jpg", b"data", "image/jpeg")
