#!/usr/bin/env python3
"""GitHub Actions ワークフローの「失敗 → 復旧」を運営へ通知する（標準ライブラリのみ）。

GitHub は失敗時に「Run failed」メールを送るが、復旧時には何も送らない。運営は
「解消の連絡が来ない＝未解決」と扱うため、ワークフローの最後にこのスクリプトを走らせて
次の2つを運営の LINE／メールへ届ける:

    失敗    今回の実行が失敗 → 「[FAILED] {表示名} が失敗しました」（GitHub のメールと重複するが、
            LINE には GitHub から届かないので送る。欠測より重複を選ぶ）
    復旧    今回成功 かつ 直前の完了実行（cancelled / skipped を除く）が失敗
            → 「[RECOVERED] {表示名} が正常に戻りました」を1回だけ送る
    正常    それ以外は何も送らない

状態はキャッシュに持たず、GitHub API の実行履歴（同じワークフロー・同じブランチ・push。今回の実行が載るまで取り直す）から
直前の結論を引く＝ワークフロー側に restore/save の手順が要らない。

環境変数:
  GITHUB_TOKEN / GITHUB_REPOSITORY   Actions が自動付与（permissions: actions: read が必要）
  WORKFLOW_FILE   例 ci.yml
  BRANCH          例 main
  EVENT           直前の実行を同じ種別に絞る（例 push）。空なら schedule / workflow_dispatch / push を区別しない
  RUN_ID / RUN_NUMBER / RUN_URL / HEAD_SHA
  RESULT          success | failure（needs.*.result から決める）
  LABEL           通知に出す表示名（例「CI（テスト・ビルド）」）
  DRY_RUN         "1" なら判定だけ出力して送らない（ローカル検証用）
  ALERT_*, BREVO_API_KEY   通知先（uptime_check.notify と同じ）

終了コード: 通知が必要だったのに全チャネルで送れなかったときだけ 1（外形監視と同じ「通知全滅」扱い）。
判定の本体は decide() に分離してテストする（backend/tests/test_alert_transitions.py）。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uptime_check import notify  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

#: 「直前の結論」として採用する結論。cancelled（concurrency の打ち切り）・skipped は判定に使わない。
_DECISIVE = ("success", "failure")


def fetch_previous_runs(repo: str, workflow_file: str, branch: str, token: str, *, per_page: int = 50, event: str = "") -> list[dict]:
    """同じワークフロー・ブランチの実行を新しい順で返す（event 指定時はその種別だけ。失敗時は空）。

    ``status=completed`` では絞らない。2026-10-02 に、この絞り込みの一覧が直近の完了実行を返さず
    （#238 の判定で #237 が、#239 の判定で #160〜#238 が欠けた）、復旧を「正常」と誤判定して
    [RECOVERED] が出なかった。完了かどうかは ``decide`` が conclusion（success / failure）で見る。
    """
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/runs"
        f"?branch={branch}&per_page={per_page}" + (f"&event={event}" if event else "")
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "kdz-ops"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read()).get("workflow_runs", [])
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"previous runs unavailable: {type(e).__name__}: {e}", file=sys.stderr)
        return []


def history_is_stale(run_number: int, runs: list[dict]) -> bool:
    """取得した履歴が古い（今回の実行自身が載っていない）か。

    絞り込みなしの一覧には、実行中の今回の実行も必ず載る。載っていなければ、一覧が最新でなく、
    直前の結論を取り違える恐れがある（上記の誤判定の再発検知）。履歴が空のときは別扱い
    （取得失敗・初回。呼び出し側が従来どおり扱う）。
    """
    if not runs or run_number <= 0:
        return False
    return not any(int(r.get("run_number") or 0) == run_number for r in runs)


def load_history(
    repo: str,
    workflow_file: str,
    branch: str,
    token: str,
    run_number: int,
    *,
    event: str = "",
    attempts: int = 4,
    wait_seconds: float = 15.0,
    fetch=None,
    sleep=time.sleep,
) -> list[dict]:
    """履歴を取得し、古い（今回の実行が載っていない）間は ``wait_seconds`` 待って取り直す。

    それでも古いままなら、最後に取得した履歴を返して警告を出す（通知を止めるより、
    欠測を警告つきで判定する方が「障害の連絡が来ない」より安全）。
    """
    fetch = fetch or fetch_previous_runs
    runs: list[dict] = []
    for attempt in range(1, max(attempts, 1) + 1):
        runs = fetch(repo, workflow_file, branch, token, event=event)
        if not history_is_stale(run_number, runs):
            return runs
        print(
            f"warning: 履歴に今回の実行 #{run_number} が載っていません（取得 {attempt}/{attempts}）。",
            file=sys.stderr,
        )
        if attempt < attempts:
            sleep(wait_seconds)
    print("warning: 履歴が古いまま判定します（直前の結論が不正確な可能性）", file=sys.stderr)
    return runs


def decide(result: str, run_number: int, runs: list[dict]) -> tuple[str, dict | None, str | None]:
    """(kind, previous_run, failure_since) を返す。kind は failed / recovered / ok。

    - previous_run: 今回より前の実行のうち結論が success/failure の最新
    - failure_since: 復旧時、連続していた失敗の先頭の created_at（通知本文用）
    """
    earlier = [r for r in runs if int(r.get("run_number") or 0) < run_number and r.get("conclusion") in _DECISIVE]
    earlier.sort(key=lambda r: int(r.get("run_number") or 0), reverse=True)
    prev = earlier[0] if earlier else None
    if result != "success":
        return "failed", prev, None
    if prev is None or prev.get("conclusion") != "failure":
        return "ok", prev, None
    since = prev.get("created_at")
    for r in earlier[1:]:
        if r.get("conclusion") != "failure":
            break
        since = r.get("created_at") or since
    return "recovered", prev, since


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "japandaily-hub/sokuri")
    token = os.environ.get("GITHUB_TOKEN", "")
    workflow_file = os.environ.get("WORKFLOW_FILE", "ci.yml")
    branch = os.environ.get("BRANCH", "main")
    event = os.environ.get("EVENT", "")
    result = os.environ.get("RESULT", "success")
    run_number = int(os.environ.get("RUN_NUMBER") or 0)
    run_url = os.environ.get("RUN_URL", "")
    sha = (os.environ.get("HEAD_SHA") or "")[:7]
    label = os.environ.get("LABEL") or workflow_file
    dry = os.environ.get("DRY_RUN") == "1"

    runs = load_history(repo, workflow_file, branch, token, run_number, event=event) if token else []
    kind, prev, since = decide(result, run_number, runs)
    prev_desc = f"#{prev.get('run_number')} {prev.get('conclusion')}" if prev else "なし"
    print(f"result={result} run#{run_number} prev={prev_desc} → {kind}")
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    if kind == "failed":
        subject = f"[カタヅケCI][FAILED] {label} が失敗しました"
        text = (
            f"❌ {label} が失敗しました（{branch} {sha}）\n"
            f"検知: {now}\n{run_url}\n\n"
            "直ったら同じ経路で [RECOVERED] を送ります。届かない間は未解決です。"
        )
    elif kind == "recovered":
        subject = f"[カタヅケCI][RECOVERED] {label} が正常に戻りました"
        text = (
            f"✅ {label} が正常に戻りました（{branch} {sha}）\n"
            f"失敗開始: {since} → 復旧確認: {now}\n{run_url}"
        )
    else:
        print("✅ 正常（通知なし）")
        return 0

    if dry:
        print(f"[DRY_RUN] {subject}\n{text}")
        return 0
    sent = notify(subject, text)
    print(f"notified: {sent or 'none'}")
    if not sent:
        print("通知全滅: 全チャネルで送信に失敗しました（Secrets と各サービスを確認）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
