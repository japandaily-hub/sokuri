"""notify.py の BREVO_API_KEY 未設定時の可視化（ADD-H2対応）のテスト。

未設定でも例外は投げず送信をスキップする（既存挙動を維持）が、最初のスキップ時に
logger.error と運営アラート（alerts.send_alert 経由）を1回だけ発火することを確認する。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.config import get_settings
from app.services import alerts, notify


@pytest.fixture(autouse=True)
def _reset_alert_state():
    """「未設定アラート発火済み」フラグをテスト間で独立させる。"""
    notify.reset_brevo_missing_key_alert_state_for_tests()
    alerts.reset_state_for_tests()
    yield
    notify.reset_brevo_missing_key_alert_state_for_tests()
    alerts.reset_state_for_tests()


class _FakeAlertTransportResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeAlertTransportClient:
    """alerts.py の実配送経路（httpx.AsyncClient）の代替。post 呼び出しを記録する。

    H1対応: 従来は alerts.send_alert 自体をモックしており「呼んだこと」しか
    検証できなかった（QA r4-review H1）。send_alert は本物のまま実行させ、
    その内部が最終的に叩く HTTP トランスポートだけを差し替えることで、
    「実際に配送関数まで到達したか」を検証できるようにする
    （tests/test_alerts.py の _FakeClient と同型の手法）。
    """

    calls: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAlertTransportClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(
        self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> _FakeAlertTransportResponse:
        _FakeAlertTransportClient.calls.append((url, json or {}))
        return _FakeAlertTransportResponse()


async def test_missing_brevo_key_logs_error_and_alerts_once(monkeypatch, caplog):
    """未設定時: 送信はスキップ(False)しつつ、最初の1回だけ運営アラートを発火する。

    2回目以降の呼び出しでも logger.error は毎回出る（可視化を絶やさない）が、
    alerts.send_alert の呼び出しは1回に抑える（同一プロセスで連打しない）。

    H1対応: alerts.send_alert はモックせず本物を実行させ、alerts.py の LINE
    配送トランスポート（httpx.AsyncClient）まで実際にリクエストが到達する
    ことを検証する（従来は send_alert 自体をモックしていたため、alerts.py側の
    実装が壊れて配送されなくなっていても検知できなかった）。
    """
    monkeypatch.setattr(get_settings(), "brevo_api_key", "")
    _FakeAlertTransportClient.calls = []
    monkeypatch.setattr(alerts.httpx, "AsyncClient", _FakeAlertTransportClient)
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_webhook_url", "")
    monkeypatch.setattr(settings, "alert_line_channel_access_token", "ops-token")
    monkeypatch.setattr(settings, "alert_line_user_ids_raw", "Uadmin1")

    with caplog.at_level(logging.ERROR):
        result1 = await notify.send_case_created("user@example.com", "case-1")
        result2 = await notify.send_bid_received(
            "user@example.com", "case-1", "業者A", 10000
        )
        await asyncio.sleep(0.05)  # fire_and_forget が create_task したアラート送信を進行させる

    assert result1 is False
    assert result2 is False
    assert caplog.text.count("BREVO_API_KEY 未設定") == 2  # ログは毎回出す

    # send_alert を経由し、実際に LINE 配送トランスポート（httpx）まで到達したことを検証する
    # （アラート発火は最初の1回のみ・クールダウンにより2回目は抑制される）。
    line_calls = [(u, p) for u, p in _FakeAlertTransportClient.calls if "api.line.me" in u]
    assert len(line_calls) == 1
    assert line_calls[0][1]["to"] == "Uadmin1"
    assert "BREVO_API_KEY" in line_calls[0][1]["messages"][0]["text"]


async def test_admin_bound_alert_is_also_visible_when_key_missing(monkeypatch, caplog):
    """admin宛の重要通知（業者申込アラート）が落ちた場合も同じ経路で可視化される。"""
    monkeypatch.setattr(get_settings(), "brevo_api_key", "")
    monkeypatch.setattr(alerts, "send_alert", AsyncMock(return_value=True))

    with caplog.at_level(logging.ERROR):
        result = await notify.send_operator_application_admin_alert(
            "admin@example.com", "テスト株式会社"
        )
        await asyncio.sleep(0)

    assert result is False
    assert "BREVO_API_KEY 未設定" in caplog.text
