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
from run_transition_notify import history_is_stale, load_history  # noqa: E402


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


# ── 履歴が古いときの誤判定の再発防止（2026-10-02: #239 が #159 を「直前」と取り違え [RECOVERED] が出なかった） ──


def _hist_run(number: int, conclusion: str | None) -> dict:
    return {"run_number": number, "conclusion": conclusion, "created_at": f"t{number}"}


def test_history_without_the_current_run_is_stale():
    assert history_is_stale(239, [_hist_run(159, "success"), _hist_run(158, "success")]) is True


def test_history_with_the_current_run_in_progress_is_fresh():
    assert history_is_stale(239, [_hist_run(239, None), _hist_run(238, "failure")]) is False


def test_empty_history_is_not_called_stale():
    # 取得失敗・初回は従来どおり（decide が prev=None → 正常扱い）。待っても変わらない。
    assert history_is_stale(239, []) is False


def test_load_history_retries_until_the_current_run_appears():
    responses = [
        [_hist_run(159, "success")],  # 古い一覧（今回の #239 も #238 も無い）
        [_hist_run(159, "success")],
        [_hist_run(239, None), _hist_run(238, "failure"), _hist_run(237, "success")],
    ]
    calls: list[int] = []
    sleeps: list[float] = []

    def fetch(*_args, **_kwargs):
        calls.append(1)
        return responses[len(calls) - 1]

    runs = load_history("o/r", "ci.yml", "main", "tok", 239, fetch=fetch, sleep=sleeps.append)
    assert len(calls) == 3 and len(sleeps) == 2
    kind, prev, _since = decide_run("success", 239, runs)
    assert (kind, prev["run_number"]) == ("recovered", 238)


def test_load_history_gives_up_after_attempts_and_returns_the_last_history():
    stale = [_hist_run(159, "success")]
    calls: list[int] = []

    def fetch(*_args, **_kwargs):
        calls.append(1)
        return stale

    runs = load_history(
        "o/r", "ci.yml", "main", "tok", 239, attempts=3, fetch=fetch, sleep=lambda _s: None
    )
    assert len(calls) == 3 and runs == stale


def test_fetch_url_does_not_filter_by_status(monkeypatch):
    import io
    import json as _json

    from run_transition_notify import fetch_previous_runs

    seen: list[str] = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(req, timeout=0):
        seen.append(req.full_url)
        return _Resp(_json.dumps({"workflow_runs": []}).encode())

    monkeypatch.setattr("run_transition_notify.urllib.request.urlopen", fake_urlopen)
    fetch_previous_runs("o/r", "ci.yml", "main", "tok", event="push")
    assert "status=completed" not in seen[0] and "event=push" in seen[0] and "per_page=50" in seen[0]
