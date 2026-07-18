"""ログ抑制ヘルパー（プロセス内スロットリング、フレームワーク非依存）。

「プロセス内で1回だけ出す」という抑制方式は、攻撃者が起動直後に不正な
リクエストを1回送るだけで永久に消費でき、以後本物の異常が起きても
二度と警告が出なくなる（security review Medium-2）。本モジュールは
「直近の出力から一定秒数未満は抑制し、それ以降は再び出す」という
時間ベースのスロットリングに統一し、``client_ip.py`` / ``rate_limit_deps.py``
の複数箇所にあった「1回きり」の重複実装を共通化する。
"""

from __future__ import annotations

import threading
import time
from typing import Callable

# 60秒間隔（毎分最大1行）を既定の間隔とする。ログ量は無害だが、異常の
# 継続を見失わない程度に頻度を保つ。
DEFAULT_THROTTLE_INTERVAL_SEC = 60.0


class ThrottledLogger:
    """直近の発火から ``interval_seconds`` 未満の呼び出しを抑制するラッパー。

    インスタンス毎に独立した状態（最終発火時刻）を持つため、警告の種類ごとに
    別インスタンスを用意すること（1つのインスタンスを複数の警告種別で共有すると
    互いのスロットリングに干渉してしまう）。

    ``clock`` は ``Callable[[], float]``（既定 ``time.monotonic``）。ストアの
    偽クロックと足並みを揃えたい場合はここに同じ clock を注入できる。
    """

    def __init__(
        self,
        interval_seconds: float = DEFAULT_THROTTLE_INTERVAL_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._last_emit = float("-inf")

    def emit(self, log_fn: Callable[[], None]) -> None:
        """許可されていれば ``log_fn()`` を呼ぶ（副作用のみを持つ引数無し callable）。"""
        now = self._clock()
        with self._lock:
            if now - self._last_emit < self._interval:
                return
            self._last_emit = now
        log_fn()

    def reset(self) -> None:
        """テスト専用: スロットリング状態を初期化する。"""
        with self._lock:
            self._last_emit = float("-inf")
