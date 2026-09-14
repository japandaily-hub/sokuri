"""写真ストレージバックエンドの解決（``local`` | ``r2``）。

``app.services.storage``（公開ファサード）は本モジュールの ``get_backend()``
のみを経由してバックエンド実装へアクセスする。
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.storage_backends.base import (
    ObjectExistsError,
    PhotoStorageBackend,
    StorageUnavailableError,
)

__all__ = [
    "ObjectExistsError",
    "PhotoStorageBackend",
    "StorageUnavailableError",
    "get_backend",
]


@lru_cache(maxsize=1)
def get_backend() -> PhotoStorageBackend:
    """設定 (``settings.resolved_storage_backend``) からバックエンドを1回だけ解決する。

    プロセス起動後に ``STORAGE_BACKEND``（や R2 認証情報）を動的に変更する運用は
    想定していない。テストで切り替えが必要な場合は
    ``app.services.storage.reset_backend_cache()`` で本キャッシュを破棄すること。
    """
    resolved = get_settings().resolved_storage_backend
    if resolved == "r2":
        from app.services.storage_backends.r2 import R2Backend

        return R2Backend()
    from app.services.storage_backends.local_disk import LocalDiskBackend

    return LocalDiskBackend()
