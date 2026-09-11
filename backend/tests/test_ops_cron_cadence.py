"""Ops cron の欠測検知（scripts/ops_jobs.py `_check_hourly_runs`）。

INC-2026-09-11-1 の再発防止: 「直近24時間に失敗があった」を要対応に積むと、その報告自体が
daily を失敗させ、翌日がその失敗を検知してまた失敗する自己増殖ループになる（2026-09-08〜09-10 に
3 晩連続で発生）。過去の失敗だけでは要対応にしないこと、本来の目的（スケジュールが止まった＝
成功回数が下限未満）は従来どおり検知することを固定する。
"""

from __future__ import annotations

import os
import sys
import time

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import ops_jobs  # noqa: E402


def _run(conclusion: str, hours_ago: float) -> dict:
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours_ago * 3600))
    return {"created_at": created, "status": "completed", "conclusion": conclusion}


@pytest.fixture
def github(monkeypatch):
    """GitHub API の応答（schedule 実行の履歴）を差し替える。"""

    def _set(runs: list[dict]) -> None:
        monkeypatch.setattr(ops_jobs, "GITHUB_TOKEN", "test-token")
        monkeypatch.setattr(ops_jobs, "http", lambda *a, **kw: (200, {"workflow_runs": runs}))

    return _set


def test_past_failure_alone_is_not_actionable(github):
    """前日の失敗 1 回だけでは要対応にしない（これを積むと永久ループになる）。"""
    github([_run("failure", 23.0)] + [_run("success", h) for h in (1, 4, 8, 12, 16)])
    assert ops_jobs._check_hourly_runs() == []


def test_all_failures_still_not_actionable_but_stopped_schedule_is(github):
    """失敗が続いていても要対応にはしない（個々の失敗は発生時に通知済み）。"""
    github([_run("failure", h) for h in (1, 4, 8, 12, 16, 20)])
    problems = ops_jobs._check_hourly_runs()
    assert not any("失敗が" in p for p in problems)
    # 成功が下限未満なので「止まっている可能性」は出る（本来の目的は維持）
    assert any("成功が" in p for p in problems)


def test_stopped_schedule_is_detected(github):
    """成功が下限未満なら欠測として要対応（履歴は下限以上あること）。"""
    github([_run("success", 1)] + [_run("success", 30), _run("success", 40), _run("success", 50)])
    problems = ops_jobs._check_hourly_runs()
    assert any("下限" in p for p in problems)


def test_healthy_cadence_reports_nothing(github):
    github([_run("success", h) for h in (1, 4, 8, 12, 16, 20)])
    assert ops_jobs._check_hourly_runs() == []


def test_missing_token_is_reported(monkeypatch):
    monkeypatch.setattr(ops_jobs, "GITHUB_TOKEN", "")
    problems = ops_jobs._check_hourly_runs()
    assert problems and "GITHUB_TOKEN" in problems[0]
