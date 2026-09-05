#!/usr/bin/env python3
"""外形監視（GitHub Actions の cron から実行）。標準ライブラリのみ。

チェック内容:
  1. BACKEND_URL/health  … 200 かつ {"status":"ok"}
  2. BACKEND_URL/readyz  … 200 かつ status=ready・db=ok・alembic_version == expected_head
  3. FRONTEND_URL/       … 200 かつ HTML に <title> がある（Vercel の 5xx / 空応答を検出）
  4. 応答時間が SLOW_MS（既定 8000ms）を超えたら Warning
  5. /readyz の degraded_config（本番必須設定の未充足）が非空なら Warning（r10 O-H2）

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
終了コード（r10 ADD-H1 で変更）:
  0 … 正常、または「通知が必要で、少なくとも1チャネルへ送信できた」
  1 … 通知が必要だったのに**全チャネルで送信に失敗した**（＝障害を検知したのに運営へ何も届いていない）
      GitHub Actions の実行を赤くし、workflow 失敗メールを最後の砦にする。
      従来は常に 0 かつ Step Summary が「通知: なし」となり、正常時と文字列が完全に一致していたため、
      ALERT_LINE トークン失効・Brevo の Authorised IPs 制限・Secrets 消失を誰も検知できなかった。
GitHub の Step Summary に結果を書く。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

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
    #: /readyz の degraded_config（本番必須設定のうち未充足のキー名）。
    #: 他のチェックでは常に空。ok=True でも非空になりうる（設定不備は 200 ready のまま）。
    degraded_config: list[str] = field(default_factory=list)


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
        # 設定不備（BREVO_API_KEY 失効・ADMIN_EMAILS 未設定・アラート経路の欠落等）は
        # /readyz が意図的に status=ready のまま返すため、ok 判定には含めず別軸で扱う
        # （ここで NG にすると「API 全断」と「設定1件の欠落」が同じ Critical になる）。
        degraded_config = [str(k) for k in (data.get("degraded_config") or [])]
        detail = (
            f"HTTP {status} status={data.get('status')} db={data.get('db')} "
            f"alembic={schema.get('alembic_version')} expected={schema.get('expected_head')}"
        )
        if degraded_config:
            detail += f" degraded_config={','.join(degraded_config)}"
        return CheckResult("backend /readyz", ok, detail, ms, degraded_config)
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
    readyz = check_readyz()
    results = [check_health(), readyz, check_frontend()]
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
    # 通知が必要だったか（＝notify() を1回以上呼んだか）。全滅判定に使う（ADD-H1）。
    notify_attempted = False

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
            notify_attempted = True
            sent = notify(
                f"[カタヅケ監視][CRITICAL] {title}: {names}",
                f"🚨【Critical】カタヅケ監視 {title}\n発生: {state.get('since')}\n\n{body}\n\n"
                f"対応: Render のログ／DB／Vercel のデプロイ状況を確認してください。",
            )
    else:
        if state.get("down"):
            notify_attempted = True
            sent = notify(
                "[カタヅケ監視][RECOVERED] 復旧しました",
                f"✅ カタヅケ監視 復旧\n障害発生: {state.get('since')} → 復旧確認: {now}\n\n{body}",
            )
        was_slow = bool(state.get("slow"))
        # degraded_config の遷移判定は down/up と独立の軸のため、state を作り直す際も
        # 直前値を引き継ぐ（引き継がないと復旧のたびに「設定不備が新たに発生した」と
        # 誤検知して毎回 Warning が飛ぶ）。
        state = {
            "down": False,
            "down_runs": 0,
            "since": None,
            "slow": bool(slow),
            "degraded_config": list(state.get("degraded_config") or []),
        }
        # 遅延も状態遷移でのみ通知する（遅い間ずっと毎回送らない）
        if slow and not was_slow:
            names = "、".join(f"{r.name}({r.ms}ms)" for r in slow)
            notify_attempted = True
            sent += notify(
                f"[カタヅケ監視][WARNING] 応答遅延: {names}",
                f"⚠️【Warning】応答が遅くなっています（しきい値 {SLOW_MS}ms）\n\n{body}",
            )
        elif was_slow and not slow:
            notify_attempted = True
            sent += notify(
                "[カタヅケ監視][INFO] 応答遅延が解消しました",
                f"✅ 応答速度が通常に戻りました（しきい値 {SLOW_MS}ms）\n\n{body}",
            )

    # ── 本番必須設定の未充足（r10 O-H2）─────────────────────────────
    # /readyz は設定不備でも status=ready を返す設計のため、up/down とは独立の軸として
    # 「変化した時だけ」Warning を出す（毎回送ると通知疲れで本物の障害が埋もれる）。
    # 到達不能で degraded_config を取得できなかった実行（readyz が NG）は、「解消した」と
    # 誤検知しないよう遷移判定そのものをスキップし、直前値を据え置く。
    prev_degraded = sorted(state.get("degraded_config") or [])
    if readyz.ok:
        current_degraded = sorted(readyz.degraded_config)
        if current_degraded != prev_degraded:
            notify_attempted = True
            if current_degraded:
                sent += notify(
                    f"[カタヅケ監視][WARNING] 本番必須設定の未充足: {'、'.join(current_degraded)}",
                    f"⚠️【Warning】/readyz の degraded_config が非空です\n"
                    f"未充足: {', '.join(current_degraded)}\n"
                    f"（直前: {', '.join(prev_degraded) if prev_degraded else 'なし'}）\n\n"
                    "API は稼働していますが、該当機能（メール通知・LINE Push・AI 解析・"
                    "アラート経路など）は無言でスキップされます。"
                    "Render の環境変数を確認してください。",
                )
            else:
                sent += notify(
                    "[カタヅケ監視][INFO] 本番必須設定の未充足が解消しました",
                    f"✅ /readyz の degraded_config が空になりました"
                    f"（直前: {', '.join(prev_degraded)}）",
                )
        state["degraded_config"] = current_degraded
    else:
        state["degraded_config"] = prev_degraded

    save_state(state)
    status = "DOWN" if state.get("down") else ("UP(遅延)" if state.get("slow") else "UP")
    lines += ["", f"状態: {status} / 通知: {', '.join(sent) if sent else 'なし'}"]
    # ADD-H1: 通知が必要だったのに1チャネルも送れなかった実行を、正常時（通知不要で
    # 「通知: なし」）と機械的に区別する。exit 1 で Actions を赤くし、GitHub の
    # workflow 失敗メールを最後の砦にする。
    if notify_attempted and not sent:
        lines += [
            "",
            "**通知全滅**: 通知が必要でしたが、全チャネル（メール/LINE/Webhook）で"
            "送信に失敗しました。Secrets（BREVO_API_KEY / ALERT_EMAILS / ALERT_LINE_* / "
            "ALERT_WEBHOOK_URL）と各サービスの稼働状況を確認してください。",
        ]
        write_summary(lines)
        return 1
    write_summary(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
