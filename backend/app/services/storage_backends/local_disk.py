"""ローカルディスクへの写真保存（R2 未設定時のフォールバック実装）。

Render Free 等のエフェメラルディスク上で運用される前提のため、永続性は
保証しない（従来からの既知の制約。R2 設定完了後は自動的に使われなくなる）。

qa review 指摘対応: ``Path.write_bytes``/``read_bytes``/``is_file``/``unlink`` は
同期（ブロッキング）I/O のため、``R2Backend`` と同じパターンで
``asyncio.to_thread`` に逃がす（イベントループを塞がない）。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import get_settings
from app.services.storage_backends.base import ObjectExistsError

logger = logging.getLogger(__name__)


class LocalDiskBackend:
    """``settings.storage_dir`` 配下にファイルとして保存するバックエンド。

    保存ルートは呼び出しの都度 ``get_settings().storage_dir`` から解決する
    （コンストラクタで固定しない）。テストが
    ``monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)`` で
    差し替える既存方式を壊さないための必須要件。
    """

    name = "local"

    @staticmethod
    def _root() -> Path:
        root = Path(get_settings().storage_dir)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _sync_put(self, key: str, data: bytes) -> None:
        # content_type はローカル保存では使わない（ファイル拡張子＝キー自体が
        # 形式を表しており、都度 content_type_for_key() で導出できるため
        # メタデータとして別途永続化する必要が無い）。
        path = self._root() / key
        if path.exists():
            raise ObjectExistsError(f"storage_key は既にアップロード済みです: {key}")
        path.write_bytes(data)

    def _sync_get(self, key: str) -> tuple[bytes, str | None] | None:
        path = self._root() / key
        if not path.is_file():
            return None
        # content_type は保存時に永続化していないため常に None を返す。
        # 呼び出し元（storage.read_bytes）は None の場合 content_type_for_key()
        # にフォールバックする設計のため、ローカルバックエンドは常にキーの
        # 拡張子ベースの content_type になる（設計書どおりの挙動）。
        return path.read_bytes(), None

    def _sync_head(self, key: str) -> bool:
        return (self._root() / key).is_file()

    def _sync_delete(self, key: str) -> None:
        path = self._root() / key
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "LocalDiskBackend.delete: ファイル削除に失敗（無視して続行） - error=%s",
                exc,
            )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._sync_put, key, data)

    async def get(self, key: str) -> tuple[bytes, str | None] | None:
        return await asyncio.to_thread(self._sync_get, key)

    async def head(self, key: str) -> bool:
        return await asyncio.to_thread(self._sync_head, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._sync_delete, key)
