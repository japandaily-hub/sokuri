"""定型の HTTPException を「raise のたびに新しいインスタンスで」生成するファクトリ。

モジュールレベルで 1 回だけ生成した ``HTTPException`` を ``raise _XXX`` で使い回すと、
CPython は raise のたびに新しいトレースバックを既存の ``__traceback__`` の前へ連結する。
共有インスタンスはモジュールが生き続ける限り解放されないため、連結されたフレーム
（とそのローカル変数が参照する request・DB セッション・ORM オブジェクト）も
プロセス終了まで残り、401/404 を返すだけの通常トラフィックや未認証の攻撃者の
リクエストでメモリが単調に増える（2026-09-25 実測: 不正トークン 100 回で
``deps._CRED_EXC`` に 1000 フレーム、``GET /files/<不正キー>`` 100 回で 500 フレーム）。
``raise ... from exc`` の ``__cause__`` も同様に元例外とそのフレームを保持し続ける。
``except HTTPException`` で内部捕捉される経路でも蓄積するため、例外ハンドラ側で
``__traceback__`` を消すだけでは防げない。

本モジュールは定数の代わりに「呼ぶたびに新しい HTTPException を返す関数」を作る::

    _NOT_FOUND = http_exception_factory(status.HTTP_404_NOT_FOUND, "見つかりません。")
    ...
    raise _NOT_FOUND()

status_code・detail・headers は定義時に固定されるため、応答の契約は従来の定数と
完全に同一になる。回帰防止として ``tests/test_http_exception_not_shared.py`` が
モジュールレベル・クラスレベルの例外インスタンス定義と、モジュールレベルで代入した
名前の ``raise`` を静的に禁止している。

注意: 例外を返す関数に ``functools.lru_cache`` 等のキャッシュを付けないこと。初回の
インスタンスが使い回され、同じ蓄積が再発する（キャッシュされた値はモジュールの
グローバルに現れないため、上記の検査でも検出できない）。
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import HTTPException


def http_exception_factory(
    status_code: int,
    detail: Any = None,
    headers: Mapping[str, str] | None = None,
) -> Callable[[], HTTPException]:
    """呼ぶたびに同一内容の新しい ``HTTPException`` を返す関数を作る。

    Args:
        status_code: HTTP ステータスコード。
        detail: 応答本文の ``detail``。dict 等の可変値が渡されても応答間で共有しない
            よう、定義時と生成ごとに深いコピーを取る（str はコピーされず同一のまま）。
        headers: 応答ヘッダ（``WWW-Authenticate`` 等）。定義時にコピーして固定し、
            生成ごとにも新しい dict を渡す（呼び出し側や下流が dict を変更しても
            次の応答へ波及しないようにするため）。

    Returns:
        引数なしで呼ぶと新しい ``HTTPException`` を返す関数。
    """
    frozen_detail = copy.deepcopy(detail)
    frozen_headers = dict(headers) if headers is not None else None

    def _new_exception() -> HTTPException:
        return HTTPException(
            status_code=status_code,
            detail=copy.deepcopy(frozen_detail),
            headers=dict(frozen_headers) if frozen_headers is not None else None,
        )

    return _new_exception
