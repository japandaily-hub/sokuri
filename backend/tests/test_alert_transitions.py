"""復旧通知の判定ロジック（scripts/run_transition_notify.py・scripts/render_sync_check.py）。

運営は「解消の連絡が来ない＝未解決」と扱うため、失敗のあとに正常へ戻ったら必ず
[RECOVERED] が1回だけ出ること、正常継続では何も出ないこと、cancelled を判定に使わないことを固定する。
"""

from __future__ import annotations

import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from render_sync_check import decide as decide_sync  # noqa: E402
from run_transition_notify import decide as decide_run  # noqa: E402


def _run(n: int, conclusion: str, created: str = "") -> dict:
    return {"run_number": n, "conclusion": conclusion, "created_at": created or f"2026-09-0{min(n, 9)}T00:00:00Z"}


# ──────────────────────────── GitHub ワークフロー ────────────────────────────


def test_run_failure_always_notifies():
    kind, prev, _ = decide_run("failure", 10, [_run(9, "success")])
    assert kind == "failed"
    assert prev["run_number"] == 9


def test_run_success_after_failure_is_recovered_with_streak_start():
    runs = [_run(9, "failure", "2026-09-05T13:00Z"), _run(8, "failure", "2026-09-05T08:00Z"), _run(7, "success")]
    kind, prev, since = decide_run("success", 10, runs)
    assert kind == "recovered"
    assert prev["run_number"] == 9
    assert since == "2026-09-05T08:00Z"  # 連続失敗の先頭


def test_run_success_after_success_is_silent():
    kind, _, _ = decide_run("success", 10, [_run(9, "success"), _run(8, "failure")])
    assert kind == "ok"


def test_run_ignores_cancelled_and_later_runs():
    runs = [_run(12, "success"), _run(11, "cancelled"), _run(9, "cancelled"), _run(8, "failure")]
    kind, prev, _ = decide_run("success", 10, runs)
    assert kind == "recovered"
    assert prev["run_number"] == 8


def test_run_without_history_is_silent_on_success():
    assert decide_run("success", 1, [])[0] == "ok"


# ──────────────────────────── Render Blueprint 同期 ────────────────────────────


def _sync(sha: str, state: str) -> dict:
    return {"commit": {"id": sha + "0" * 33}, "state": state}


def test_sync_error_is_failed():
    kind, target = decide_sync([_sync("aaaaaaa", "error"), _sync("bbbbbbb", "success")], "aaaaaaa")
    assert kind == "failed"
    assert target["state"] == "error"


def test_sync_success_after_error_is_recovered():
    kind, _ = decide_sync([_sync("ccccccc", "success"), _sync("aaaaaaa", "error"), _sync("bbbbbbb", "success")], "ccccccc")
    assert kind == "recovered"


def test_sync_success_after_success_is_silent():
    assert decide_sync([_sync("ccccccc", "success"), _sync("bbbbbbb", "success")], "ccccccc")[0] == "ok"


def test_sync_missing_or_incomplete_is_pending():
    assert decide_sync([_sync("bbbbbbb", "success")], "zzzzzzz")[0] == "pending"
    assert decide_sync([_sync("ccccccc", "running")], "ccccccc")[0] == "pending"
    assert decide_sync([], None)[0] == "pending"


def test_sync_without_sha_evaluates_latest():
    kind, target = decide_sync([_sync("ccccccc", "success"), _sync("aaaaaaa", "error")], None)
    assert kind == "recovered"
    assert target["commit"]["id"].startswith("ccccccc")
