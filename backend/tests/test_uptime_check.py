"""外形監視（scripts/uptime_check.py）のスリープ復帰待ちと状態遷移。

INC-2026-09-08-2 の再発防止: Render 無料枠のコールドスタート（復帰に 25 秒超）を「障害」と
誤判定しないこと、復帰後の正常応答で DOWN→UP の復旧通知が出ることを固定する。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import uptime_check  # noqa: E402

HEALTH = json.dumps({"status": "ok", "commit": "abc1234"}).encode()
READYZ = json.dumps({"status": "ready", "db": "ok", "schema": {"alembic_version": "0034", "expected_head": "0034"}, "degraded_config": []}).encode()
FRONT = b"<html><head><title>x</title></head></html>"


def _fake_fetch_factory(wake_ms: int):
    calls: list[tuple[str, int | None]] = []

    def fake(url: str, timeout: int | None = None):
        calls.append((url, timeout))
        if url.endswith("/health"):
            # 最初の /health（復帰待ち）だけ遅い。復帰後は速い。
            ms = wake_ms if len([c for c in calls if c[0].endswith("/health")]) == 1 else 120
            if timeout is not None and ms > timeout * 1000:
                raise TimeoutError("timed out")
            return 200, HEALTH, ms
        if url.endswith("/readyz"):
            return 200, READYZ, 300
        return 200, FRONT, 200

    return fake, calls


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(uptime_check, "STATE_FILE", str(tmp_path / "state.json"))
    sent: list[str] = []
    monkeypatch.setattr(uptime_check, "notify", lambda subject, text: sent.append(subject) or ["email"])
    monkeypatch.setattr(uptime_check, "write_summary", lambda lines: None)
    return sent


def test_cold_start_is_not_an_outage(isolated, monkeypatch):
    fake, calls = _fake_fetch_factory(wake_ms=32000)  # 32 秒の復帰 = 従来の 25 秒判定なら NG だった
    monkeypatch.setattr(uptime_check, "_fetch", fake)
    assert uptime_check.main() == 0
    assert isolated == []  # 通知なし（正常）
    # 最初の呼び出しは復帰待ち（長いタイムアウト）で /health
    assert calls[0][0].endswith("/health") and calls[0][1] == uptime_check.WAKE_TIMEOUT_S
    state = json.load(open(uptime_check.STATE_FILE, encoding="utf-8"))
    assert state["down"] is False


def test_down_then_recovered_sends_both_notices(isolated, monkeypatch):
    def broken(url: str, timeout: int | None = None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(uptime_check, "_fetch", broken)
    uptime_check.main()
    assert any("[CRITICAL]" in s for s in isolated)
    fake, _ = _fake_fetch_factory(wake_ms=100)
    monkeypatch.setattr(uptime_check, "_fetch", fake)
    uptime_check.main()
    assert any("[RECOVERED]" in s for s in isolated)


def test_wake_backend_reports_failure_without_raising(monkeypatch):
    def broken(url: str, timeout: int | None = None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(uptime_check, "_fetch", broken)
    ok, ms, detail = uptime_check.wake_backend()
    assert ok is False and ms == uptime_check.WAKE_TIMEOUT_S * 1000 and "TimeoutError" in detail
