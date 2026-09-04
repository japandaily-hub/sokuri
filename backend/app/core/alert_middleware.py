"""5xx バースト／未処理例外を検知して運営へアラートを送る ASGI ミドルウェア。

- 未処理例外: 1件でも発生したら即アラート（key は path 単位でクールダウン）。例外は再送出し、
  FastAPI 既定の 500 応答はそのまま。
- 5xx バースト: 直近 window 秒間の 5xx 応答（例外由来を含む）が threshold 件以上で 1 回アラート。
  再送はクールダウンに従う。
- /health・/readyz 自身の 503 は外形監視側で拾うため集計から除外する（監視の自己言及を避ける）。
"""
from __future__ import annotations

import logging
import time
from collections import deque

from app.config import get_settings
from app.services import alerts

logger = logging.getLogger(__name__)

_EXCLUDED_PATHS = {"/health", "/readyz"}


class ServerErrorAlertMiddleware:
    """Starlette の BaseHTTPMiddleware を使わない素の ASGI 実装（ストリーミング応答と相性が良い）。"""

    def __init__(self, app) -> None:  # noqa: ANN001 -- ASGI app
        self.app = app
        self._events: deque[float] = deque()

    def _record_5xx(self, path: str) -> None:
        if path in _EXCLUDED_PATHS:
            return
        settings = get_settings()
        now = time.monotonic()
        window = settings.alert_5xx_window_seconds
        self._events.append(now)
        while self._events and now - self._events[0] > window:
            self._events.popleft()
        count = len(self._events)
        if count >= settings.alert_5xx_threshold:
            alerts.fire_and_forget(
                alerts.send_alert(
                    "5xx 応答が急増しています",
                    f"直近 {window} 秒で {count} 件の 5xx 応答（最新: {path}）。"
                    "Render のログとDB到達性（/readyz）を確認してください。",
                    severity="critical",
                    key="5xx-burst",
                )
            )

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001 -- ASGI signature
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        status_holder: dict[str, int] = {}

        async def send_wrapper(message) -> None:  # noqa: ANN001
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001 -- 監視目的で全例外を捕捉し再送出する
            self._record_5xx(path)
            if path not in _EXCLUDED_PATHS:
                alerts.fire_and_forget(
                    alerts.send_alert(
                        "未処理の例外が発生しました",
                        f"{scope.get('method', '')} {path}\n{type(exc).__name__}: {str(exc)[:300]}",
                        severity="critical",
                        key=f"unhandled:{path}",
                    )
                )
            raise
        status = status_holder.get("status")
        if status is not None and status >= 500:
            self._record_5xx(path)

