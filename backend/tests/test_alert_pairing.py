"""メタガード: 失敗を通知する経路には必ず復旧通知が対になっていること（docs/ops/incidents.md の原則）。

運営は「復旧の連絡が来ない＝未解決」と扱う。新しい失敗通知を足したときに復旧側を忘れると
このテストが落ちる＝仕組みとして学習させる。

判定:
1. .github/workflows/*.yml は、通知 Secrets（ALERT_LINE_CHANNEL_ACCESS_TOKEN）を使うなら、
   復旧を担う仕組みのいずれかを含む: run_transition_notify.py / render_sync_check.py（自前で対にしている）/
   uptime_check.py（down→up）/ ops_jobs.py（_track_recovery）。
2. scripts/*.py で notify( を呼ぶファイルは、「失敗」系の件名（❌ または [FAILED] または「失敗」）を出すなら
   同じファイルに RECOVERED も出す（対になっていない片側通知を禁止）。
3. ops-cron.yml の notify-failure は失敗状態（.ops_state.json）を保存する（到達前失敗でも次回成功で復旧が出る）。
"""

from __future__ import annotations

import glob
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKFLOWS = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
SCRIPTS = sorted(glob.glob(os.path.join(ROOT, "scripts", "*.py")))
RECOVERY_MECHANISMS = ("run_transition_notify.py", "render_sync_check.py", "uptime_check.py", "ops_jobs.py")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_workflows_exist():
    assert WORKFLOWS, "ワークフローが見つかりません"


def test_every_alerting_workflow_has_a_recovery_mechanism():
    missing = []
    for wf in WORKFLOWS:
        text = _read(wf)
        if "ALERT_LINE_CHANNEL_ACCESS_TOKEN" not in text:
            continue  # 通知しないワークフロー
        if not any(m in text for m in RECOVERY_MECHANISMS):
            missing.append(os.path.basename(wf))
    assert not missing, f"失敗通知はあるのに復旧の仕組みが無いワークフロー: {missing}（docs/ops/incidents.md 原則1）"


def test_scripts_that_notify_failures_also_notify_recovery():
    one_sided = []
    for path in SCRIPTS:
        text = _read(path)
        if "notify(" not in text or os.path.basename(path) in ("uptime_check.py",):
            # uptime_check は notify の定義元。自身の down/up は下で別途確認する。
            continue
        if re.search(r"❌|\[FAILED\]|失敗しました", text) and "RECOVERED" not in text:
            one_sided.append(os.path.basename(path))
    assert not one_sided, f"失敗を通知するのに RECOVERED を持たないスクリプト: {one_sided}"


def test_uptime_check_pairs_down_with_recovered():
    text = _read(os.path.join(ROOT, "scripts", "uptime_check.py"))
    assert "障害検知" in text and "[RECOVERED]" in text


def test_ops_cron_pre_script_failure_is_recorded_for_recovery():
    text = _read(os.path.join(ROOT, ".github", "workflows", "ops-cron.yml"))
    nf = text.split("notify-failure:", 1)[1]
    assert ".ops_state.json" in nf and "'failed': True" in nf, "notify-failure が失敗状態を保存していない（次回成功で復旧が出ない）"


def test_ci_notify_job_uses_transition_script_on_main_push():
    text = _read(os.path.join(ROOT, ".github", "workflows", "ci.yml"))
    assert "run_transition_notify.py" in text
    assert "actions: read" in text, "notify が直前の実行結果を読むには permissions.actions: read が必要"
