#!/usr/bin/env python3
"""外形監視（GitHub Actions の cron から実行）。標準ライブラリのみ。

チェック内容:
  1. BACKEND_URL/health  … 200 かつ {"status":"ok"}
  2. BACKEND_URL/readyz  … 200 かつ status=ready・db=ok・alembic_version == expected_head
  3. FRONTEND_URL/       … 200 かつ HTML に <title> がある（Vercel の 5xx / 空応答を検出）
  4. 応答時間が SLOW_MS（既定 8000ms）を超えたら Warning

状態遷移で通知する（毎回は送らない）:
  - 直前状態 up → 今回 down: Critical「障害検知」
  - 直前状態 down → 今回 up: 復旧通知
  - down が継続: ALERT_REPEAT_EVERY 回に 1 回だけ再通知（既定 12 回＝5分間隔なら約1時間ごと）
  - 応答遅延も遷移型: 遅くなった時に Warning を 1 回、通常速度に戻った時に解消通知を 1 回（遅い間は再送しない）
正常時は何も送らない。状態は STATE_FILE（既定 .uptime_state.json。Actions では actions/cache で持ち回す）に保存する。

通知先（環境変数。未設定のチャネルはスキップ）:
  BREVO_API_KEY + ALERT_EMAILS（カンマ区切り）+ ALERT_MAIL_FROM
  ALERT_LINE_CHANNEL_ACCESS_TOKEN + ALERT_LINE_USER_IDS（カンマ区切り。顧客向けとは別の公式アカウント）
  ALERT_WEBHOOK_URL（Slack / Discord Incoming Webhook）
終了コード: 常に 0（監視ジョブ自体を赤くしない。障害は通知で伝える）。GitHub の Step Summary に結果を書く。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# Windows の cp932 コンソールでも日本語・絵文字を出力できるようにする（Actions/Linux では無害）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

BACKEND_URL = os.environ.get("BACKEND_URL", "https://sokuri-backend.onrender.com").rstrip("/")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://sokuri.vercel.app").rstrip("/")
STATE_FILE = os.environ.get("STATE_FILE", ".uptime_state.json")
SLOW_MS = int(os.environ.get("SLOW_MS", "8000"))
TIMEOUT_S = int(os.environ.get("TIMEOUT_S", "25"))
REPEAT_EVERY = int(os.environ.get("ALERT_REPEAT_EVERY", "12"))


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    ms: int


def _fetch(url: str) -> tuple[int, bytes, int]:
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "katadzuke-uptime/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            body = res.read()
            return res.status, body, int((time.monotonic() - started) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", int((time.monotonic() - started) * 1000)


def check_health() -> CheckResult:
    try:
        status, body, ms = _fetch(f"{BACKEND_URL}/health")
        data = json.loads(body or b"{}")
        ok = status == 200 and data.get("status") == "ok"
        return CheckResult("backend /health", ok, f"HTTP {status} status={data.get('status')} commit={data.get('commit')}", ms)
    except Exception as e:  # noqa: BLE001
        return CheckResult("backend /health", False, f"到達不能: {type(e).__name__}: {e}", TIMEOUT_S * 1000)


def check_readyz() -> CheckResult:
    try:
        status, body, ms = _fetch(f"{BACKEND_URL}/readyz")
        data = json.loads(body or b"{}")
        schema = data.get("schema") or {}
        head_ok = (not schema) or schema.get("alembic_version") == schema.get("expected_head")
        ok = status == 200 and data.get("status") == "ready" and data.get("db") == "ok" and head_ok
        detail = (
            f"HTTP {status} status={data.get('status')} db={data.get('db')} "
            f"alembic={schema.get('alembic_version')} expected={schema.get('expected_head')}"
        )
        return CheckResult("backend /readyz", ok, detail, ms)
    except Exception as e:  # noqa: BLE001
        return CheckResult("backend /readyz", False, f"到達不能: {type(e).__name__}: {e}", TIMEOUT_S * 1000)


def check_frontend() -> CheckResult:
    try:
        status, body, ms = _fetch(f"{FRONTEND_URL}/")
        ok = status == 200 and b"<title>" in body
        return CheckResult("frontend /", ok, f"HTTP {status} bytes={len(body)}", ms)
    except Exception as e:  # noqa: BLE001
        return CheckResult("frontend /", False, f"到達不能: {type(e).__name__}: {e}", TIMEOUT_S * 1000)


# ──────────────────────────── 通知 ────────────────────────────


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return 200 <= res.status < 300
    except Exception as e:  # noqa: BLE001
        print(f"notify failed: {url.split('/')[2]} {type(e).__name__}: {e}", file=sys.stderr)
        return False


def notify(subject: str, text: str) -> list[str]:
    sent: list[str] = []
    api_key = os.environ.get("BREVO_API_KEY", "")
    emails = [e.strip() for e in os.environ.get("ALERT_EMAILS", "").split(",") if e.strip()]
    if api_key and emails:
        html = "<pre style='white-space:pre-wrap;font-family:sans-serif;line-height:1.7'>" + (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ) + "</pre>"
        ok = _post_json(
            "https://api.brevo.com/v3/smtp/email",
            {
                "sender": {"email": os.environ.get("ALERT_MAIL_FROM", "noreply@katadzuke.jp"), "name": "カタヅケ監視"},
                "to": [{"email": e} for e in emails],
                "subject": subject,
                "htmlContent": html,
            },
            {"api-key": api_key},
        )
        if ok:
            sent.append("email")
    token = os.environ.get("ALERT_LINE_CHANNEL_ACCESS_TOKEN", "")
    users = [u.strip() for u in os.environ.get("ALERT_LINE_USER_IDS", "").split(",") if u.strip()]
    if token and users:
        ok_all = True
        for uid in users:
            ok_all &= _post_json(
                "https://api.line.me/v2/bot/message/push",
                {"to": uid, "messages": [{"type": "text", "text": text[:1800]}]},
                {"Authorization": f"Bearer {token}"},
            )
        if ok_all:
            sent.append("line")
    webhook = os.environ.get("ALERT_WEBHOOK_URL", "")
    if webhook and _post_json(webhook, {"text": text, "content": text[:1900]}, {}):
        sent.append("webhook")
    return sent


# ──────────────────────────── 状態 ────────────────────────────


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"down": False, "down_runs": 0, "since": None, "slow": False}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def write_summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    text = "\n".join(lines) + "\n"
    print(text)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def main() -> int:
    results = [check_health(), check_readyz(), check_frontend()]
    failures = [r for r in results if not r.ok]
    slow = [r for r in results if r.ok and r.ms > SLOW_MS]
    now = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    state = load_state()

    lines = [f"## カタヅケ外形監視 {now}", "", "| チェック | 結果 | 応答(ms) | 詳細 |", "|---|---|---:|---|"]
    for r in results:
        lines.append(f"| {r.name} | {'OK' if r.ok else '**NG**'} | {r.ms} | {r.detail} |")

    body_lines = [f"- {r.name}: {r.detail}（{r.ms}ms）" for r in results]
    body = "\n".join(body_lines)
    sent: list[str] = []

    if failures:
        state["down_runs"] = int(state.get("down_runs", 0)) + 1
        first = not state.get("down")
        if first:
            state["down"] = True
            state["since"] = now
        repeat = REPEAT_EVERY > 0 and state["down_runs"] % REPEAT_EVERY == 0
        if first or repeat:
            names = "、".join(r.name for r in failures)
            title = "障害検知" if first else f"障害継続中（{state['down_runs']}回目の確認）"
            sent = notify(
                f"[カタヅケ監視][CRITICAL] {title}: {names}",
                f"🚨【Critical】カタヅケ監視 {title}\n発生: {state.get('since')}\n\n{body}\n\n"
                f"対応: Render のログ／DB／Vercel のデプロイ状況を確認してください。",
            )
    else:
        if state.get("down"):
            sent = notify(
                "[カタヅケ監視][RECOVERED] 復旧しました",
                f"✅ カタヅケ監視 復旧\n障害発生: {state.get('since')} → 復旧確認: {now}\n\n{body}",
            )
        was_slow = bool(state.get("slow"))
        state = {"down": False, "down_runs": 0, "since": None, "slow": bool(slow)}
        # 遅延も状態遷移でのみ通知する（遅い間ずっと毎回送らない）
        if slow and not was_slow:
            names = "、".join(f"{r.name}({r.ms}ms)" for r in slow)
            sent += notify(
                f"[カタヅケ監視][WARNING] 応答遅延: {names}",
                f"⚠️【Warning】応答が遅くなっています（しきい値 {SLOW_MS}ms）\n\n{body}",
            )
        elif was_slow and not slow:
            sent += notify(
                "[カタヅケ監視][INFO] 応答遅延が解消しました",
                f"✅ 応答速度が通常に戻りました（しきい値 {SLOW_MS}ms）\n\n{body}",
            )

    save_state(state)
    status = "DOWN" if state.get("down") else ("UP(遅延)" if state.get("slow") else "UP")
    lines += ["", f"状態: {status} / 通知: {', '.join(sent) if sent else 'なし'}"]
    write_summary(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
