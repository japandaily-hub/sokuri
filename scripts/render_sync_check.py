#!/usr/bin/env python3
"""Render Blueprint（render.yaml）の同期結果を確認し、失敗と復旧を運営へ通知する（標準ライブラリのみ）。

Render は同期失敗時に「Blueprint Sync Failed」メールを送るが、成功に戻っても何も送らない。
運営は「解消の連絡が来ない＝未解決」と扱うため、render.yaml を含む push のあとにこのスクリプトを
走らせて次を届ける（GitHub Actions「Render sync」・.github/workflows/render-sync.yml）:

    失敗    push したコミットの同期が error → 「[FAILED] Render Blueprint 同期が失敗」
    復旧    今回 success かつ 直前の同期が error → 「[RECOVERED] Render Blueprint 同期が正常に戻りました」
    正常    それ以外は何も送らない

状態は Render の同期履歴そのものを使う（キャッシュ不要）。同期エラーの本文は API に出ないため、
通知には dashboard の Blueprint ページと「render.yaml の宣言と実態（DB のプラン・名前など）の差」を
確認するよう添える。

環境変数:
  RENDER_API_KEY        必須（無ければスキップ・exit 0）
  RENDER_BLUEPRINT_ID   既定 exs-d8enisc2m8qs73947330（sokuri）
  HEAD_SHA              待つコミット。空なら最新の同期を評価する
  WAIT_SECONDS          同期が履歴に現れるまで待つ上限（既定 180）
  DRY_RUN               "1" なら判定だけ出力して送らない
  ALERT_*, BREVO_API_KEY   通知先（uptime_check.notify と同じ）

終了コード: 通知が必要だったのに全チャネルで送れなかったときだけ 1。
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

RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
BLUEPRINT_ID = os.environ.get("RENDER_BLUEPRINT_ID", "exs-d8enisc2m8qs73947330")
DASHBOARD_URL = f"https://dashboard.render.com/blueprint/{BLUEPRINT_ID}"
_FINAL = ("success", "error")


def fetch_syncs(limit: int = 10) -> list[dict]:
    """同期履歴を新しい順で返す（各要素は {"commit": {"id": ...}, "state": ...}）。失敗時は空。"""
    req = urllib.request.Request(
        f"https://api.render.com/v1/blueprints/{BLUEPRINT_ID}/syncs?limit={limit}",
        headers={"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json", "User-Agent": "kdz-ops"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return [x.get("sync") or x for x in json.loads(res.read())]
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"syncs unavailable: {type(e).__name__}: {e}", file=sys.stderr)
        return []


def decide(syncs: list[dict], sha: str | None) -> tuple[str, dict | None]:
    """(kind, target_sync) を返す。kind は failed / recovered / ok / pending。

    - sha 指定あり: そのコミットの同期を探す。無い・未完了なら pending。
    - sha 指定なし: 最新の同期を評価する。
    - recovered は「対象が success かつ その直前の同期が error」。
    """
    if not syncs:
        return "pending", None
    idx = 0
    if sha:
        idx = next((i for i, s in enumerate(syncs) if str((s.get("commit") or {}).get("id", "")).startswith(sha)), -1)
        if idx < 0:
            return "pending", None
    target = syncs[idx]
    state = target.get("state")
    if state not in _FINAL:
        return "pending", target
    if state == "error":
        return "failed", target
    prev = syncs[idx + 1] if idx + 1 < len(syncs) else None
    if prev and prev.get("state") == "error":
        return "recovered", target
    return "ok", target


def main() -> int:
    if not RENDER_API_KEY:
        print("⏭️ RENDER_API_KEY が未設定のためスキップ")
        return 0
    sha = (os.environ.get("HEAD_SHA") or "").strip() or None
    wait = int(os.environ.get("WAIT_SECONDS") or 180)
    dry = os.environ.get("DRY_RUN") == "1"

    deadline = time.time() + wait
    kind, target = "pending", None
    while True:
        kind, target = decide(fetch_syncs(), sha)
        if kind != "pending" or time.time() >= deadline:
            break
        time.sleep(15)

    commit = str((target or {}).get("commit", {}).get("id", sha or ""))[:7]
    print(f"sha={sha or '(latest)'} sync={commit or '-'} state={(target or {}).get('state')} → {kind}")
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    if kind == "pending":
        # render.yaml に変更があっても Render が同期不要と判断することがある。誤報を避けて静かに終える。
        print("⏭️ 対象コミットの同期が履歴に現れませんでした（同期不要と判断された可能性）。通知なし")
        return 0
    if kind == "failed":
        subject = "[カタヅケ運用][FAILED] Render Blueprint 同期が失敗しました"
        text = (
            f"❌ Render Blueprint（render.yaml）の同期が失敗しました（commit {commit}）\n"
            f"検知: {now}\n{DASHBOARD_URL}\n\n"
            "エラー本文は dashboard の Blueprint ページに表示されます。よくある原因は render.yaml の宣言と\n"
            "実態の差（DB のプラン・databaseName・リージョン）。直したら同じ経路で [RECOVERED] を送ります。"
        )
    elif kind == "recovered":
        subject = "[カタヅケ運用][RECOVERED] Render Blueprint 同期が正常に戻りました"
        text = (
            f"✅ Render Blueprint（render.yaml）の同期が正常に戻りました（commit {commit}）\n"
            f"復旧確認: {now}\n{DASHBOARD_URL}"
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
