"""5xx バースト／未処理例外を検知して運営へアラートを送る ASGI ミドルウェア。

- 未処理例外: 1件でも発生したら即アラート（key はメソッドとルートの型の単位でクールダウン）。
  例外は再送出し、FastAPI 既定の 500 応答はそのまま。本文の例外文は伏せ字にして1行にする。
- 5xx バースト: 直近 window 秒間の 5xx 応答（例外由来を含む）が threshold 件以上で 1 回アラート。
  再送はクールダウンに従う。
- /health・/readyz 自身の 503 は外形監視側で拾うため集計から除外する（監視の自己言及を避ける）。
- 未処理例外のアラート本文は ``describe_exception``: DB 例外は型・SQLSTATE・制約名だけ（PostgreSQL の
  DETAIL＝一意制約違反のキーの値・CHECK 違反の行全体を LINE・メールへ送らない）、応答の検証エラーは
  項目と種類だけ、それ以外は従来どおり「型: 文言」（app/core/error_summary.py）。
- 本文と key には実パスではなくルートの型（``/api/v1/files/{storage_key}`` 等）を使う。実パスには
  写真の capability URL の storage_key が入る（本文は LINE・メールへ送られ、送信記録に残る）。
  key を実パスにすると、パスを変えるだけでクールダウンを回避して運営 LINE の配信枠を使い切れ、
  alerts のプロセス内の状態も際限なく増える。ルートの型は FastAPI がルーティング時に
  ``scope["route"]``（APIRoute）へ入れる（fastapi/routing.py の ``APIRoute.matches``・0.136 で確認）。
  Starlette の Router は同じ scope 辞書を ``scope.update(child_scope)`` で更新するので、外側にいる
  本ミドルウェアからも例外後・応答後に読める。ルートに当たる前（外側のミドルウェア等）で起きた
  例外には ``scope["route"]`` が無いので、key は固定の ``unhandled:(ルート外)`` にし、本文には
  伏せ字にしたパスを短く出す。
"""
from __future__ import annotations

import logging
import time
from collections import deque
from urllib.parse import quote

from app.config import get_settings
from app.core.app_logging import escape_control_characters
from app.core.error_summary import describe_exception, is_value_bearing_exception
from app.core.masking import mask_request_target_for_log, mask_sensitive_in_text
from app.services import alerts

logger = logging.getLogger(__name__)

_EXCLUDED_PATHS = {"/health", "/readyz"}

#: ルートに当たる前に起きた例外（``scope["route"]`` が無い）の表示と key に使う固定の名前。
_UNROUTED_LABEL = "(ルート外)"

#: ルート外のときに本文へ出すパスの上限（送信者が自由に作れる文字列のため短く切る）。
_UNROUTED_PATH_MAX_CHARS = 120

#: 本文へ出す例外メッセージの上限。
_EXCEPTION_MESSAGE_MAX_CHARS = 300

#: 伏せ字を掛ける前に例外メッセージを切る長さ（巨大な例外文で処理量が増えないように）。本文に残す
#: 300 字より十分長くし、ここで途中で切れた storage_key 等が本文に入らないようにする（伏せ字で
#: 文が縮んでも、切れ目が 300 字以内に来るには鍵が約 150 個前に並ぶ必要がある）。
_EXCEPTION_MESSAGE_SCAN_CHARS = 4096

#: 本文へ出す HTTP メソッド名の上限（h11 はトークン形式なら未知のメソッド名も受け付ける）。
_METHOD_MAX_CHARS = 16


def _now() -> float:
    """単調時計。テストで差し替えられるよう関数で間接化する（time.monotonic を直接パッチすると asyncio が止まる）。"""
    return time.monotonic()


def _route_template(scope) -> str | None:  # noqa: ANN001 -- ASGI scope
    """FastAPI が ``scope["route"]`` に入れた APIRoute のパスの型（例: ``/api/v1/files/{storage_key}``）。"""
    template = getattr(scope.get("route"), "path", None)
    if isinstance(template, str) and template:
        return template
    return None


def _describe_request(scope) -> tuple[str, str]:  # noqa: ANN001 -- ASGI scope
    """(重複抑止に使うルート名, 本文に出す「メソッド パス」) を返す。実パスはどちらにも入れない。

    ルート名は「メソッド ルートの型」（同じ型の GET と POST を別の異常として扱う）。メソッドは
    そのルートが受け付けるもの（``route.methods``）のときだけ入れる＝種類はルートの定義で有限。
    ルートに当たらなかった場合だけ、伏せ字にした実パスを本文に出す（key は固定の名前のまま）。
    デコード済みのパスは改行・双方向制御文字等を含みうるので、uvicorn のアクセスログと同じく
    ``quote`` して ``%XX`` にしてから伏せ字にする（``?`` も ``%3F`` になり、クエリの区切りと
    誤認しない）。伏せ字は切り詰めより先に掛ける（途中で切れた storage_key は照合に掛からない）。
    クエリ文字列（``scope["query_string"]``）はどちらの場合も本文に入れない（DIAG_TOKEN や検索語が
    入りうる。発生箇所の特定にはルートの型か伏せ字のパスで足りる）。
    """
    method = str(scope.get("method", ""))[:_METHOD_MAX_CHARS]
    template = _route_template(scope)
    if template is not None:
        route_methods = getattr(scope.get("route"), "methods", None) or ()
        route_name = f"{method} {template}" if method in route_methods else template
        return route_name, f"{method} {template}"
    quoted_path = quote(str(scope.get("path", "")), safe="/", errors="backslashreplace")
    masked_path = mask_request_target_for_log(quoted_path)
    if len(masked_path) > _UNROUTED_PATH_MAX_CHARS:
        masked_path = masked_path[: _UNROUTED_PATH_MAX_CHARS - 1] + "…"
    return _UNROUTED_LABEL, f"{method} {masked_path} {_UNROUTED_LABEL}"


def _exception_text(exc: BaseException) -> str:
    """本文に出す例外の1行（``型: 文言``）。

    DB 例外（PostgreSQL の DETAIL＝一意制約違反のキーの値・CHECK 違反の行全体）と応答の検証エラーは、
    文言そのものが氏名・住所・電話番号を抱えるため、``describe_exception`` の要約（型・SQLSTATE・制約名・
    項目と種類）だけを出す。それ以外は従来どおり ``型: 文言``（文言は伏せ字・エスケープ・切り詰め済み）。
    """
    if is_value_bearing_exception(exc):
        try:
            described = describe_exception(exc)
        except Exception:  # noqa: BLE001 -- 要約の失敗で通知を止めない
            described = type(exc).__name__
        return escape_control_characters(mask_sensitive_in_text(described))[
            :_EXCEPTION_MESSAGE_MAX_CHARS
        ]
    return f"{type(exc).__name__}: {_summarize_exception(exc)}"


def _summarize_exception(exc: BaseException) -> str:
    """本文に出す例外メッセージ。storage_key・メール等を伏せ、制御文字をエスケープして1行にし、切り詰める。

    例外文には利用者の入力が入りうる（DB のエラー文の入力値等）。改行で偽の行（「✅【Recovered】」等）
    を足されたり、双方向制御文字で表示順を入れ替えられたりしないよう、app.* のログ本文と同じ表で
    エスケープする（マスクが先: エスケープ後の文字が鍵・メールの境界の判定を崩すため）。
    """
    try:
        message = str(exc)
    except Exception:  # noqa: BLE001 -- __str__ の失敗で通知を止めない
        message = "（例外の文字列を取得できませんでした）"
    masked = mask_sensitive_in_text(message[:_EXCEPTION_MESSAGE_SCAN_CHARS])
    return escape_control_characters(masked)[:_EXCEPTION_MESSAGE_MAX_CHARS]


class ServerErrorAlertMiddleware:
    """Starlette の BaseHTTPMiddleware を使わない素の ASGI 実装（ストリーミング応答と相性が良い）。"""

    def __init__(self, app) -> None:  # noqa: ANN001 -- ASGI app
        self.app = app
        self._events: deque[float] = deque()
        #: 5xx バーストを通知済みで、まだ「収まった」通知を送っていない間 True。
        self._burst_active = False
        self._burst_started_at: float | None = None
        self._last_5xx_at: float | None = None

    def _record_5xx(
        self, scope, request_label: str | None = None  # noqa: ANN001 -- ASGI scope
    ) -> None:
        """5xx を1件数え、閾値に達したらバーストを通知する。``request_label`` は計算済みなら渡す。"""
        if scope.get("path", "") in _EXCLUDED_PATHS:
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
            if request_label is None:
                _, request_label = _describe_request(scope)
            alerts.fire_and_forget(
                alerts.send_alert(
                    "5xx 応答が急増しています",
                    f"直近 {window} 秒で {count} 件の 5xx 応答（最新: {request_label}）。"
                    "Render のログとDB到達性（/readyz）を確認してください。",
                    severity="critical",
                    key="5xx-burst",
                )
            )

    def _alert_unhandled(self, scope, exc: BaseException) -> None:  # noqa: ANN001 -- ASGI scope
        if scope.get("path", "") in _EXCLUDED_PATHS:
            return  # 監視用パスは数えず通知もしない（外形監視が拾う）
        route_name, request_label = _describe_request(scope)
        self._record_5xx(scope, request_label)
        alerts.fire_and_forget(
            alerts.send_alert(
                "未処理の例外が発生しました",
                f"{request_label}\n{_exception_text(exc)}",
                severity="critical",
                key=f"unhandled:{route_name}",
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
        # 復旧判定は監視用パス（/health 等）を含む全リクエストで行う（5xx の集計だけ除外する）。
        # 通知の都合でリクエストを失敗させない（判定・通知の失敗はログに残して処理を続ける）。
        try:
            self._check_burst_recovered()
        except Exception:  # noqa: BLE001
            logger.warning("alert_middleware: 5xx 急増の復旧判定に失敗しました", exc_info=True)
        status_holder: dict[str, int] = {}

        async def send_wrapper(message) -> None:  # noqa: ANN001
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001 -- 監視目的で全例外を捕捉し再送出する
            # 通知の準備で失敗しても、アプリ本来の例外を置き換えない（必ず元の例外を再送出する）。
            try:
                self._alert_unhandled(scope, exc)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "alert_middleware: 未処理例外の通知を準備できませんでした", exc_info=True
                )
            raise
        status = status_holder.get("status")
        if status is not None and status >= 500:
            try:
                self._record_5xx(scope)
            except Exception:  # noqa: BLE001 -- 応答は送信済み。集計の失敗をアプリの例外にしない
                logger.warning(
                    "alert_middleware: 5xx 応答の集計・通知に失敗しました", exc_info=True
                )
