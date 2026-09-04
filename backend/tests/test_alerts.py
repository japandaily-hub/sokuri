"""運営向けアラート（services/alerts.py・core/alert_middleware.py）のテスト。

外部送信（Brevo / LINE / Webhook）は httpx.AsyncClient を差し替えて記録するだけにする。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.core.alert_middleware import ServerErrorAlertMiddleware
from app.services import alerts


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
    assert "unhandled:/boom" in keys
    assert "5xx-burst" in keys
    assert not any(k and "/health" in k for k in keys)
