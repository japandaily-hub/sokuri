"""Brevo 無料枠（300通/日）の監視（最終レビュー QA M-4）。

固定する契約:
- 250 通に達した時点で運営アラートを1回だけ出す（本文は件数だけ・宛先や件名を含まない）。
  同じ日に何通送っても2回目は出さない。日付が変われば数え直し、前日のアラートは復旧通知で閉じる。
- 280 通を超えたら新着チャット通知メール（send_message_received）だけ送らない。
  再設定・成約などのメールは送り続ける。
- 数はプロセス内の概数。
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.services import alerts, notify


@pytest.fixture(autouse=True)
def _reset_daily_state():
    notify.reset_daily_send_state_for_tests()
    yield
    notify.reset_daily_send_state_for_tests()


async def _drain_alert_tasks() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def test_alert_once_at_250_with_count_only():
    with patch.object(alerts, "send_alert", new=AsyncMock(return_value=True)) as alert_mock:
        for _ in range(249):
            notify._record_daily_send()
        await _drain_alert_tasks()
        alert_mock.assert_not_called()

        notify._record_daily_send()  # 250 通目
        await _drain_alert_tasks()
        assert alert_mock.await_count == 1
        title, body = alert_mock.await_args.args
        assert "250 通" in body
        assert "@" not in title + body
        assert alert_mock.await_args.kwargs["severity"] == "warning"

        for _ in range(60):  # 同じ日にこれ以上送ってもアラートは1回だけ
            notify._record_daily_send()
        await _drain_alert_tasks()
        assert alert_mock.await_count == 1


async def test_new_day_resets_count_and_resolves_previous_alert(monkeypatch):
    with patch.object(alerts, "send_alert", new=AsyncMock(return_value=True)):
        for _ in range(250):
            notify._record_daily_send()
        await _drain_alert_tasks()
    yesterday = date(2000, 1, 1)
    monkeypatch.setattr(notify, "_daily_send_date", yesterday)
    monkeypatch.setattr(notify, "_daily_quota_alerted_date", yesterday)
    previous_key = notify._daily_quota_alert_key(yesterday)
    with patch.object(alerts, "is_active", return_value=True) as is_active_mock, patch.object(
        alerts, "resolve_alert", new=AsyncMock(return_value=True)
    ) as resolve_mock:
        notify._record_daily_send()
        await _drain_alert_tasks()
    assert notify._daily_send_count == 1
    is_active_mock.assert_called_with(previous_key)
    resolve_mock.assert_awaited_once()
    assert resolve_mock.await_args.args[0] == previous_key


async def test_chat_mail_stops_above_280_but_other_mail_continues(monkeypatch):
    sent: list[str] = []

    async def fake_send(to_email: str, subject: str, html: str) -> bool:
        sent.append(subject)
        return True

    monkeypatch.setattr(notify, "_send", fake_send)
    monkeypatch.setattr(notify, "_daily_send_date", notify.datetime.now(notify.timezone.utc).date())

    monkeypatch.setattr(notify, "_daily_send_count", 280)
    assert await notify.send_message_received("u@example.com", "txn-1") is True
    assert len(sent) == 1

    monkeypatch.setattr(notify, "_daily_send_count", 281)
    assert await notify.send_message_received("u@example.com", "txn-1") is False
    assert len(sent) == 1  # チャット通知は送らない

    # 重要メール（パスワード変更・成約）は止めない。
    assert await notify.send_password_changed("u@example.com") is True
    assert await notify.send_bid_selected("op@example.com", "txn-1", 30000) is True
    assert len(sent) == 3


def test_chat_mail_stop_log_has_no_personal_data(monkeypatch, caplog):
    monkeypatch.setattr(notify, "_daily_send_date", notify.datetime.now(notify.timezone.utc).date())
    monkeypatch.setattr(notify, "_daily_send_count", 300)
    caplog.set_level("WARNING", logger="app.services.notify")
    assert notify.is_chat_mail_suppressed() is True
    assert notify.is_chat_mail_suppressed() is True
    stop_logs = [r for r in caplog.records if "新着チャット通知メール" in r.getMessage()]
    assert len(stop_logs) == 1  # 同じ日に1回
    assert "@" not in stop_logs[0].getMessage()
