"""写真ストレージのバックエンド抽象（``Protocol``）。

``app.services.storage``（公開ファサード）は本モジュールの ``PhotoStorageBackend``
を介してローカルディスク（:mod:`.local_disk`）/ Cloudflare R2（:mod:`.r2`）を
差し替え可能にする。``Protocol`` を使うことで、テストでは継承なしのフェイクを
そのまま差し込める。
"""

from __future__ import annotations

from typing import Protocol


class ObjectExistsError(Exception):
    """既に存在するキーへの ``put`` を示す例外（上書き禁止・r12踏襲）。"""


class StorageUnavailableError(RuntimeError):
    """ストレージ側に接続できない（一時障害）ことを示す例外。

    「存在しない」（None）とは意味が異なるため区別する。R2 障害時に
    ``read_bytes`` が None を返すと、フロントで「写真無し」として描画され
    障害が見えなくなる事故につながるため、呼び出し元は本例外を専用に
    ハンドリングすること（503 へ翻訳する等）。
    """


class PhotoStorageBackend(Protocol):
    """写真ストレージの差し替え可能な実装が満たすべきインターフェース。"""

    name: str

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """新規オブジェクトを保存する。既存キーへの上書きは ``ObjectExistsError``。"""
        ...

    async def get(self, key: str) -> tuple[bytes, str | None] | None:
        """オブジェクト本体と、保存時に記録された content_type を返す。

        未保存キーは ``None``。接続不能等の一時障害は ``StorageUnavailableError``。
        """
        ...

    async def head(self, key: str) -> bool:
        """オブジェクトの存在有無のみを返す（本体は取得しない）。"""
        ...

    async def delete(self, key: str) -> None:
        """オブジェクトを削除する（冪等・ベストエフォート）。"""
        ...
