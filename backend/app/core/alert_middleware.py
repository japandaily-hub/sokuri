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


def _now() -> float:
    """単調時計。テストで差し替えられるよう関数で間接化する（time.monotonic を直接パッチすると asyncio が止まる）。"""
    return time.monotonic()


class ServerErrorAlertMiddleware:
    """Starlette の BaseHTTPMiddleware を使わない素の ASGI 実装（ストリーミング応答と相性が良い）。"""

    def __init__(self, app) -> None:  # noqa: ANN001 -- ASGI app
        self.app = app
        self._events: deque[float] = deque()
        #: 5xx バーストを通知済みで、まだ「収まった」通知を送っていない間 True。
        self._burst_active = False
        self._burst_started_at: float | None = None
        self._last_5xx_at: float | None = None

    def _record_5xx(self, path: str) -> None:
        if path in _EXCLUDED_PATHS:
            return
        settings = get_settings()
        now = _now()
        window = settings.alert_5xx_window_seconds
        self._events.append(now)
        self._last_5xx_at = now
        while self._events and now - self._events[0] > window:
            self._events.popleft()
        count = len(self._events)
        if count >= settings.alert_5xx_threshold:
            if not self._burst_active:
                self._burst_active = True
                self._burst_started_at = now
            alerts.fire_and_forget(
                alerts.send_alert(
                    "5xx 応答が急増しています",
                    f"直近 {window} 秒で {count} 件の 5xx 応答（最新: {path}）。"
                    "Render のログとDB到達性（/readyz）を確認してください。",
                    severity="critical",
                    key="5xx-burst",
                )
            )

    def _check_burst_recovered(self) -> None:
        """バースト通知後、window 秒間 5xx が 1 件も無ければ「収まった」を 1 回だけ通知する。

        リクエストが来た時にしか評価しないが、外形監視が /health を 5 分毎に叩くので
        トラフィックが無くても復旧通知は遅くとも次の監視ピングで出る。
        """
        if not self._burst_active or self._last_5xx_at is None:
            return
        settings = get_settings()
        now = _now()
        window = settings.alert_5xx_window_seconds
        if now - self._last_5xx_at < window:
            return
        quiet_for = int(now - self._last_5xx_at)
        lasted = int(self._last_5xx_at - (self._burst_started_at or self._last_5xx_at))
        self._burst_active = False
        self._burst_started_at = None
        self._events.clear()
        alerts.fire_and_forget(
            alerts.send_alert(
                "5xx 応答の急増が収まりました",
                f"直近 {quiet_for} 秒間、5xx 応答はありません（急増は約 {lasted} 秒続きました）。",
                severity="info",
                key="5xx-burst-recovered",
            )
        )

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001 -- ASGI signature
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        # 復旧判定は監視用パス（/health 等）を含む全リクエストで行う（5xx の集計だけ除外する）。
        self._check_burst_recovered()
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

