"""運営向けアラート（services/alerts.py・core/alert_middleware.py）のテスト。

外部送信（Brevo / LINE / Webhook）は httpx.AsyncClient を差し替えて記録するだけにする。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.core import alert_middleware
from app.core.alert_middleware import ServerErrorAlertMiddleware
from app.services import alerts

#: 形式どおりの写真の storage_key（32桁 hex＋拡張子）。GET /files/{storage_key} は無認証の capability URL。
_STORAGE_KEY = "0123abcd" + "4567" * 6 + ".jpg"
_MASKED_KEY = "0123abcd..."


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """httpx.AsyncClient の代替。post 呼び出しを記録する。"""

    calls: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> _FakeResponse:
        _FakeClient.calls.append((url, json or {}))
        return _FakeResponse()


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    alerts.reset_state_for_tests()
    _FakeClient.calls = []
    monkeypatch.setattr(alerts.httpx, "AsyncClient", _FakeClient)
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.test/abc")
    monkeypatch.setattr(settings, "alert_cooldown_seconds", 600)
    monkeypatch.setattr(settings, "alert_5xx_threshold", 3)
    monkeypatch.setattr(settings, "alert_5xx_window_seconds", 300)
    yield
    alerts.reset_state_for_tests()


async def test_send_alert_posts_to_webhook_and_dedupes():
    ok = await alerts.send_alert("テスト障害", "本文", severity="critical", key="k1")
    assert ok is True
    urls = [u for u, _ in _FakeClient.calls]
    assert urls == ["https://hooks.example.test/abc"]
    payload = _FakeClient.calls[0][1]
    assert "テスト障害" in payload["text"] and "🚨" in payload["text"]

    # 同一 key はクールダウン中は抑制される
    again = await alerts.send_alert("テスト障害", "本文", severity="critical", key="k1")
    assert again is False
    assert len(_FakeClient.calls) == 1

    # 別 key は送られる
    other = await alerts.send_alert("別の障害", "本文", severity="warning", key="k2")
    assert other is True
    assert len(_FakeClient.calls) == 2
    assert "⚠️" in _FakeClient.calls[1][1]["text"]


async def test_send_alert_skips_when_nothing_configured(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_webhook_url", "")
    ok = await alerts.send_alert("誰にも届かない", "本文", key="k3")
    assert ok is False
    assert _FakeClient.calls == []


async def test_send_alert_uses_separate_line_channel(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_webhook_url", "")
    monkeypatch.setattr(settings, "alert_line_channel_access_token", "ops-token")
    monkeypatch.setattr(settings, "alert_line_user_ids_raw", "U111,U222")
    monkeypatch.setattr(settings, "line_channel_access_token", "customer-token")  # 顧客向けは使わない
    ok = await alerts.send_alert("LINE経路", "本文", key="k4")
    assert ok is True
    line_calls = [(u, p) for u, p in _FakeClient.calls if "api.line.me" in u]
    assert [p["to"] for _, p in line_calls] == ["U111", "U222"]


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    @app.get("/fine")
    async def fine() -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        raise RuntimeError("health-noise")

    app.add_middleware(ServerErrorAlertMiddleware)
    return app


async def test_middleware_alerts_on_unhandled_exception_and_burst(monkeypatch: pytest.MonkeyPatch):
    sent: list[tuple[str, str | None]] = []

    async def fake_send_alert(title: str, body: str, *, severity: str = "critical", key: str | None = None) -> bool:
        sent.append((title, key))
        return True

    monkeypatch.setattr(alerts, "send_alert", fake_send_alert)

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        r = await client.get("/fine")
        assert r.status_code == 200
        for _ in range(3):
            r = await client.get("/boom")
            assert r.status_code == 500
        # /health 自身の失敗は集計・通知しない
        r = await client.get("/health")
        assert r.status_code == 500
        await asyncio.sleep(0.05)  # fire_and_forget のタスクを消化

    keys = [k for _, k in sent]
    assert "unhandled:GET /boom" in keys
    assert "5xx-burst" in keys
    assert not any(k and "/health" in k for k in keys)
    # バーストが続いている間は「収まった」通知は出ない
    assert "5xx-burst-recovered" not in keys


async def test_middleware_notifies_once_when_burst_recovers(monkeypatch: pytest.MonkeyPatch):
    """バースト通知後、window 秒間 5xx が無ければ復旧通知を 1 回だけ送る。"""
    sent: list[tuple[str, str | None, str]] = []

    async def fake_send_alert(title: str, body: str, *, severity: str = "critical", key: str | None = None) -> bool:
        sent.append((title, key, severity))
        return True

    monkeypatch.setattr(alerts, "send_alert", fake_send_alert)

    from app.core import alert_middleware as mw

    clock = {"now": 1_000.0}
    monkeypatch.setattr(mw, "_now", lambda: clock["now"])

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        for _ in range(3):
            await client.get("/boom")
        await asyncio.sleep(0.05)
        assert [k for _, k, _ in sent].count("5xx-burst") == 1

        # window（300秒）未満しか経っていない → まだ復旧扱いにしない（/health のピングでも同じ）
        clock["now"] += 100
        await client.get("/health")
        await asyncio.sleep(0.05)
        assert "5xx-burst-recovered" not in [k for _, k, _ in sent]

        # window を超えて 5xx が無い → 復旧通知（severity=info）を 1 回
        clock["now"] += 250
        await client.get("/health")
        await asyncio.sleep(0.05)
        recovered = [s for s in sent if s[1] == "5xx-burst-recovered"]
        assert len(recovered) == 1
        assert recovered[0][2] == "info"

        # その後の正常リクエストでは再送しない
        clock["now"] += 1000
        await client.get("/fine")
        await asyncio.sleep(0.05)
        assert [k for _, k, _ in sent].count("5xx-burst-recovered") == 1


async def test_send_alert_info_severity_uses_recovered_tag():
    """severity=info は件名 [RECOVERED]・本文 ✅ タグになる。"""
    ok = await alerts.send_alert("復旧テスト", "本文", severity="info", key="t")
    assert ok
    payloads = [body for _, body in _FakeClient.calls]
    assert any("✅【Recovered】" in (p.get("text") or "") for p in payloads)


async def test_alert_log_masks_email_but_delivery_keeps_it(caplog: pytest.LogCaptureFixture):
    """ログ（第三者の基盤に7日残る）にはマスクした形だけ。運営の通知先には照合用に平文で届ける。"""
    with caplog.at_level(logging.WARNING, logger=alerts.__name__):
        ok = await alerts.send_alert(
            "admin 権限が付与されました",
            "email=grant-me@example.com\nvia=signup\nuser_id=1",
            key="admin-grant:grant-me@example.com",
        )
    assert ok is True
    assert "grant-me@example.com" not in caplog.text
    assert "email=g***@example.com | via=signup | user_id=1" in caplog.text
    assert any("email=grant-me@example.com" in (body.get("text") or "") for _, body in _FakeClient.calls)


async def test_cooldown_log_masks_email_in_key(caplog: pytest.LogCaptureFixture):
    await alerts.send_alert("admin 権限が付与されました", "本文", key="admin-grant:grant-me@example.com")
    with caplog.at_level(logging.INFO, logger=alerts.__name__):
        again = await alerts.send_alert("admin 権限が付与されました", "本文", key="admin-grant:grant-me@example.com")
    assert again is False
    assert "grant-me@example.com" not in caplog.text
    assert "key=admin-grant:g***@example.com" in caplog.text


async def test_webhook_failure_log_does_not_contain_webhook_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """httpx の例外文には送信先 URL が入る。Webhook の URL は投稿権限そのものなのでログに出さない。"""
    secret_url = "https://hooks.example.test/services/T000/B000/SECRET-WEBHOOK-TOKEN"
    monkeypatch.setattr(get_settings(), "alert_webhook_url", secret_url)

    class _RejectingClient(_FakeClient):
        async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
            request = httpx.Request("POST", url)
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError(
                f"Client error '404 Not Found' for url '{url}'", request=request, response=response
            )

    monkeypatch.setattr(alerts.httpx, "AsyncClient", _RejectingClient)
    with caplog.at_level(logging.ERROR, logger=alerts.__name__):
        ok = await alerts._send_webhook("本文")
    assert ok is False
    assert "SECRET-WEBHOOK-TOKEN" not in caplog.text
    assert "alerts: Webhook送信失敗（処理は継続） - HTTPStatusError status=404" in caplog.text


# ──────────────── 本文と key に実パス（写真の storage_key）を入れない ────────────────


async def _drain_alert_tasks() -> None:
    """fire_and_forget で積まれた送信タスクがすべて終わるまで待つ。"""
    for _ in range(200):
        if not alerts._inflight_tasks:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("アラート送信のタスクが終わりません")


def _client(app, *, raise_app_exceptions: bool = True) -> AsyncClient:  # noqa: ANN001
    transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return AsyncClient(transport=transport, base_url="http://test")


def _record_sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    """alerts.send_alert を差し替え、(件名, 本文, key) を記録する。"""
    sent: list[tuple[str, str, str | None]] = []

    async def fake_send_alert(
        title: str, body: str, *, severity: str = "critical", key: str | None = None
    ) -> bool:
        sent.append((title, body, key))
        return True

    monkeypatch.setattr(alerts, "send_alert", fake_send_alert)
    return sent


async def test_unhandled_alert_names_route_template_and_hides_storage_key(monkeypatch: pytest.MonkeyPatch):
    """本文・key はルートの型。実パスの storage_key もクエリも、例外文に入った鍵・メールも出さない。"""
    sent = _record_sent(monkeypatch)
    app = FastAPI()

    @app.get("/api/v1/files/{storage_key}")
    async def serve(storage_key: str) -> dict[str, str]:
        raise RuntimeError(f"cannot read {storage_key} for taro@example.com")

    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app, raise_app_exceptions=False) as client:
        r = await client.get(f"/api/v1/files/{_STORAGE_KEY}", params={"token": "SECRET-QUERY-TOKEN"})
        assert r.status_code == 500
        await asyncio.sleep(0.05)

    unhandled = [(body, key) for title, body, key in sent if title == "未処理の例外が発生しました"]
    assert unhandled == [
        (
            f"GET /api/v1/files/{{storage_key}}\nRuntimeError: cannot read {_MASKED_KEY} for t***@example.com",
            "unhandled:GET /api/v1/files/{storage_key}",
        )
    ]
    for _, body, key in sent:
        assert _STORAGE_KEY not in body and _STORAGE_KEY not in (key or "")
        assert "SECRET-QUERY-TOKEN" not in body


async def test_unhandled_alert_key_is_per_route_so_changing_the_path_cannot_bypass_cooldown():
    """実パスを key にしていた頃は、パスを変えるたびに別 key＝クールダウン無視で通知でき、状態も増え続けた。"""
    app = FastAPI()

    @app.get("/api/v1/cases/{case_id}")
    async def boom(case_id: str) -> dict[str, str]:
        raise RuntimeError("kaboom")

    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app, raise_app_exceptions=False) as client:
        for index in range(30):
            r = await client.get(f"/api/v1/cases/{index}-{'x' * index}")
            assert r.status_code == 500
        await _drain_alert_tasks()

    expected_keys = ["unhandled:GET /api/v1/cases/{case_id}"]
    assert [k for k in alerts._state.last_sent_at if k.startswith("unhandled:")] == expected_keys
    assert [k for k in alerts._state.active if k.startswith("unhandled:")] == expected_keys
    texts = [payload["text"] for _, payload in _FakeClient.calls]
    # 未処理例外の通知は1回（残り29回はクールダウンで抑制）。5xx バースト（別 key）も1回。
    assert sum("未処理の例外が発生しました" in text for text in texts) == 1
    assert sum("5xx 応答が急増しています" in text for text in texts) == 1


async def test_unrouted_exception_uses_fixed_key_and_quoted_masked_path(monkeypatch: pytest.MonkeyPatch):
    """ルートに当たる前の例外（scope["route"] が無い）は key を固定し、本文のパスは quote＋伏せ字にする。"""
    sent = _record_sent(monkeypatch)

    async def failing_before_routing(scope, receive, send) -> None:  # noqa: ANN001 -- ASGI
        raise RuntimeError("middleware failure")

    app = ServerErrorAlertMiddleware(failing_before_routing)
    async with _client(app, raise_app_exceptions=False) as client:
        # デコード後のパスに改行・表示順を入れ替える文字（U+202E）・鍵が入る。
        await client.get(f"/api/v1/files/{_STORAGE_KEY}%0Aforged?token=SECRET-QUERY-TOKEN")
        await client.get("/x%E2%80%AEy%0AINFO%20forged")
        await client.get("/other/1")
        await asyncio.sleep(0.05)

    unhandled = [(body, key) for title, body, key in sent if title == "未処理の例外が発生しました"]
    assert [key for _, key in unhandled] == ["unhandled:(ルート外)"] * 3
    assert [body.split("\n")[0] for body, _ in unhandled] == [
        f"GET /api/v1/files/{_MASKED_KEY} (ルート外)",
        "GET /x%E2%80%AEy%0AINFO%20forged (ルート外)",
        "GET /other/1 (ルート外)",
    ]
    for body, _ in unhandled:
        assert _STORAGE_KEY not in body and "SECRET-QUERY-TOKEN" not in body
        assert chr(0x202E) not in body and "\nforged" not in body and "\nINFO" not in body


async def test_unrouted_path_in_body_is_capped(monkeypatch: pytest.MonkeyPatch):
    sent = _record_sent(monkeypatch)

    async def failing_before_routing(scope, receive, send) -> None:  # noqa: ANN001 -- ASGI
        raise RuntimeError("middleware failure")

    app = ServerErrorAlertMiddleware(failing_before_routing)
    async with _client(app, raise_app_exceptions=False) as client:
        await client.get("/" + "a" * 5000)
        await asyncio.sleep(0.05)

    first_line = sent[0][1].split("\n")[0]
    path_part = first_line.removeprefix("GET ").removesuffix(" (ルート外)")
    assert len(path_part) == alert_middleware._UNROUTED_PATH_MAX_CHARS
    assert path_part.endswith("…")


async def test_burst_alert_names_route_template_not_real_path(monkeypatch: pytest.MonkeyPatch):
    sent = _record_sent(monkeypatch)
    app = FastAPI()

    @app.get("/api/v1/files/{storage_key}")
    async def unavailable(storage_key: str) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "写真を取得できませんでした。"})

    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app) as client:
        for _ in range(3):
            r = await client.get(f"/api/v1/files/{_STORAGE_KEY}", params={"token": "SECRET-QUERY-TOKEN"})
            assert r.status_code == 503
        await asyncio.sleep(0.05)

    burst = [body for _, body, key in sent if key == "5xx-burst"]
    assert burst and "（最新: GET /api/v1/files/{storage_key}）" in burst[-1]
    assert all(_STORAGE_KEY not in body and "SECRET-QUERY-TOKEN" not in body for _, body, _ in sent)


async def test_real_app_stack_exposes_route_template_to_the_middleware(monkeypatch: pytest.MonkeyPatch):
    """本番の create_app()（CORS 等を含む実際の積み順）でも、外側のミドルウェアから scope["route"] が読める。"""
    from app import main as main_module
    from app.services import storage

    sent = _record_sent(monkeypatch)

    async def exploding_read(storage_key: str) -> None:
        raise RuntimeError(f"storage exploded for {storage_key}")

    monkeypatch.setattr(storage, "read_bytes", exploding_read)
    app = main_module.create_app(get_settings())
    async with _client(app, raise_app_exceptions=False) as client:
        r = await client.get(f"/api/v1/files/{_STORAGE_KEY}", params={"token": "SECRET-QUERY-TOKEN"})
        assert r.status_code == 500
        await asyncio.sleep(0.05)

    unhandled = [(body, key) for title, body, key in sent if title == "未処理の例外が発生しました"]
    assert unhandled == [
        (
            f"GET /api/v1/files/{{storage_key}}\nRuntimeError: storage exploded for {_MASKED_KEY}",
            "unhandled:GET /api/v1/files/{storage_key}",
        )
    ]


async def test_nested_router_prefixes_stay_in_the_route_template(monkeypatch: pytest.MonkeyPatch):
    """入れ子の include_router（prefix にパス変数を含む）でも、key・本文は prefix 込みのルートの型。

    FastAPI 0.14x は include_router でルートを複製せず、scope["route"].path が prefix 無しになる
    （0.136 までは prefix 込み）。どちらの版でも prefix 込みの型になり、実パスの値は入らない。
    """
    from fastapi import APIRouter

    sent = _record_sent(monkeypatch)
    files = APIRouter()

    @files.get("/files/{storage_key}")
    async def boom(storage_key: str) -> dict[str, str]:
        raise RuntimeError("boom")

    cases = APIRouter(prefix="/cases/{case_id}")
    cases.include_router(files)
    app = FastAPI()
    app.include_router(cases, prefix="/api/v1")
    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app, raise_app_exceptions=False) as client:
        r = await client.get(f"/api/v1/cases/CASE-VALUE-42/files/{_STORAGE_KEY}")
        assert r.status_code == 500
        await asyncio.sleep(0.05)

    unhandled = [(body, key) for title, body, key in sent if title == "未処理の例外が発生しました"]
    assert unhandled == [
        (
            "GET /api/v1/cases/{case_id}/files/{storage_key}\nRuntimeError: boom",
            "unhandled:GET /api/v1/cases/{case_id}/files/{storage_key}",
        )
    ]


async def test_unhandled_alert_is_sent_even_if_the_exception_cannot_be_stringified(monkeypatch: pytest.MonkeyPatch):
    """例外の __str__ 自体が失敗しても、通知は代わりの文言で送り、元の例外で 500 を返す。"""
    sent = _record_sent(monkeypatch)

    class _UnprintableError(Exception):
        def __str__(self) -> str:
            raise ValueError("str failed")

    app = FastAPI()

    @app.get("/api/v1/cases/{case_id}")
    async def boom(case_id: str) -> dict[str, str]:
        raise _UnprintableError()

    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app, raise_app_exceptions=False) as client:
        r = await client.get("/api/v1/cases/1")
        assert r.status_code == 500
        await asyncio.sleep(0.05)

    unhandled = [(body, key) for title, body, key in sent if title == "未処理の例外が発生しました"]
    assert unhandled == [
        (
            "GET /api/v1/cases/{case_id}\n_UnprintableError: （例外の文字列を取得できませんでした）",
            "unhandled:GET /api/v1/cases/{case_id}",
        )
    ]


async def test_unhandled_alert_key_separates_methods_of_the_same_route(monkeypatch: pytest.MonkeyPatch):
    """同じルートの型の GET と POST は別の異常として扱う（片方のクールダウンでもう片方を隠さない）。"""
    sent = _record_sent(monkeypatch)
    app = FastAPI()

    @app.get("/api/v1/cases/{case_id}/bids")
    async def list_bids(case_id: str) -> dict[str, str]:
        raise RuntimeError("list failed")

    @app.post("/api/v1/cases/{case_id}/bids")
    async def create_bid(case_id: str) -> dict[str, str]:
        raise RuntimeError("create failed")

    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app, raise_app_exceptions=False) as client:
        await client.get("/api/v1/cases/1/bids")
        await client.post("/api/v1/cases/2/bids")
        await client.get("/api/v1/cases/3/bids")
        await asyncio.sleep(0.05)

    keys = [key for title, _, key in sent if title == "未処理の例外が発生しました"]
    assert keys == [
        "unhandled:GET /api/v1/cases/{case_id}/bids",
        "unhandled:POST /api/v1/cases/{case_id}/bids",
        "unhandled:GET /api/v1/cases/{case_id}/bids",
    ]


async def test_unhandled_alert_puts_the_exception_message_on_one_escaped_line(monkeypatch: pytest.MonkeyPatch):
    """例外文に入った入力で偽の行（「✅【Recovered】」等）や表示順の入れ替えを作らせない。"""
    sent = _record_sent(monkeypatch)
    app = FastAPI()
    forged = "bad input\n✅【Recovered】 復旧しました https://evil.example/login" + chr(0x202E) + "gpj.exe"

    @app.get("/api/v1/cases/{case_id}")
    async def boom(case_id: str) -> dict[str, str]:
        raise ValueError(forged)

    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app, raise_app_exceptions=False) as client:
        await client.get("/api/v1/cases/1")
        await asyncio.sleep(0.05)

    body = next(body for title, body, _ in sent if title == "未処理の例外が発生しました")
    request_line, exception_line = body.split("\n")  # 区切りの改行は1つだけ
    assert request_line == "GET /api/v1/cases/{case_id}"
    assert exception_line == (
        "ValueError: bad input\\n✅【Recovered】 復旧しました https://evil.example/login\\u202egpj.exe"
    )
    assert chr(0x202E) not in body


async def test_unhandled_alert_bounds_work_on_huge_exception_messages(monkeypatch: pytest.MonkeyPatch):
    sent = _record_sent(monkeypatch)
    app = FastAPI()

    @app.get("/api/v1/files/{storage_key}")
    async def boom(storage_key: str) -> dict[str, str]:
        raise RuntimeError(f"{storage_key} " + "x" * 2_000_000)

    app.add_middleware(ServerErrorAlertMiddleware)
    async with _client(app, raise_app_exceptions=False) as client:
        await client.get(f"/api/v1/files/{_STORAGE_KEY}")
        await asyncio.sleep(0.05)

    body = next(body for title, body, _ in sent if title == "未処理の例外が発生しました")
    exception_line = body.split("\n")[1]
    assert exception_line.startswith(f"RuntimeError: {_MASKED_KEY} xxx")
    assert len(exception_line) == len("RuntimeError: ") + alert_middleware._EXCEPTION_MESSAGE_MAX_CHARS
    assert _STORAGE_KEY not in body


async def test_burst_recovery_check_failure_does_not_fail_the_request(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """通知の都合でリクエストを失敗させない（復旧判定が例外を出しても応答は通常どおり）。"""

    def broken_check(self: ServerErrorAlertMiddleware) -> None:
        raise ValueError("recovery check failed")

    monkeypatch.setattr(ServerErrorAlertMiddleware, "_check_burst_recovered", broken_check)
    app = _build_app()
    with caplog.at_level(logging.WARNING, logger=alert_middleware.__name__):
        async with _client(app) as client:
            r = await client.get("/fine")
    assert r.status_code == 200
    assert "alert_middleware: 5xx 急増の復旧判定に失敗しました" in caplog.text


async def test_alert_preparation_failure_never_replaces_the_original_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """通知の準備で失敗しても、アプリ本来の例外をそのまま再送出する（例外を差し替えない）。"""

    def broken_describe(scope) -> tuple[str, str]:  # noqa: ANN001 -- ASGI scope
        raise ValueError("describe failed")

    monkeypatch.setattr(alert_middleware, "_describe_request", broken_describe)
    monkeypatch.setattr(get_settings(), "alert_5xx_threshold", 1)

    async def failing_app(scope, receive, send) -> None:  # noqa: ANN001 -- ASGI
        raise RuntimeError("original failure")

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        return None

    middleware = ServerErrorAlertMiddleware(failing_app)
    scope = {"type": "http", "method": "GET", "path": "/boom", "headers": []}
    with caplog.at_level(logging.WARNING, logger=alert_middleware.__name__):
        with pytest.raises(RuntimeError, match="original failure"):
            await middleware(scope, receive, send)
    assert "alert_middleware: 未処理例外の通知を準備できませんでした" in caplog.text


# ──────────────── プロセス内の状態の上限 ────────────────


async def test_tracked_keys_are_capped_and_the_oldest_are_forgotten_first(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(alerts, "_MAX_TRACKED_KEYS", 3)
    with caplog.at_level(logging.WARNING, logger=alerts.__name__):
        for index in range(5):
            assert await alerts.send_alert("障害", "本文", key=f"k{index}") is True
    assert list(alerts._state.last_sent_at) == ["k2", "k3", "k4"]
    assert list(alerts._state.active) == ["k2", "k3", "k4"]
    assert "覚えておく key が上限 3 件を超えたため古いものから忘れました" in caplog.text
    # 警告は間引く（最初の1件で1行）。累計は last_sent_at・active の両方で k0・k1 を忘れた 4 件。
    assert "プロセス内累計 1 件" in caplog.text
    assert alerts._evicted_key_count == 4

    # 覚えている key は従来どおり抑制され、再発報で active の末尾（最新）へ移る。
    assert await alerts.send_alert("障害", "本文", key="k2") is False
    assert list(alerts._state.active) == ["k3", "k4", "k2"]
    # 忘れた key は抑制できない（多めに届く側）。復旧の追跡も外れる。
    assert alerts.is_active("k0") is False
    assert await alerts.resolve_alert("k4", "復旧", "本文") is True
    assert alerts.is_active("k4") is False


async def test_key_cap_warning_is_throttled(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    """key を作る側の誤りで上限に張り付いても、警告は間引いて出す（ログを埋めない）。"""
    monkeypatch.setattr(alerts, "_MAX_TRACKED_KEYS", 2)
    with caplog.at_level(logging.WARNING, logger=alerts.__name__):
        for index in range(20):
            await alerts.send_alert("障害", "本文", key=f"flood-{index}")
    warnings = [r for r in caplog.records if "覚えておく key が上限" in r.getMessage()]
    assert len(warnings) == 1
    assert len(alerts._state.last_sent_at) == 2


def test_key_cap_leaves_room_for_every_route_template():
    """ルートごとの key（unhandled:<メソッド> <型>）が互いを追い出さない大きさであること。"""
    from app.main import app

    route_count = sum(1 for route in app.routes if isinstance(route, APIRoute))
    assert route_count * 2 < alerts._MAX_TRACKED_KEYS
