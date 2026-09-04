#!/usr/bin/env python3
"""運営向けアラートの通知先を、1コマンドで GitHub Secrets と Render 環境変数に登録し、疎通テストまで行う。

使い方:
    1. .env.alerts.example を .env.alerts にコピーして値を埋める（.env.alerts は gitignore 済み）
    2. backend\\.venv\\Scripts\\python.exe scripts\\setup_alerts.py [--dry-run] [--skip-github] [--skip-render] [--no-test]

やること:
    - .env.alerts を読み、必須項目の有無と形式を検証（LINE トークンの疎通、Brevo キーの疎通も確認）
    - GitHub: リポジトリ Secrets を作成/更新（libsodium sealed box で暗号化して送る。PyNaCl が必要）
    - Render: サービス sokuri-backend の環境変数を作成/更新（自動で再デプロイされる）
    - GitHub Actions「Uptime alert」を force_notify=true で起動し、完了まで待って結果を表示
認証情報はこのプロセス内でしか使わず、どこにも保存しない。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# Windows の cp932 コンソールでも日本語・絵文字を出力できるようにする（Actions/Linux では無害）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

REPO = os.environ.get("ALERTS_REPO", "japandaily-hub/sokuri")
RENDER_SERVICE_NAME = os.environ.get("ALERTS_RENDER_SERVICE", "sokuri-backend")
WORKFLOW_FILE = "uptime-alert.yml"
ENV_FILE = os.environ.get("ALERTS_ENV_FILE", ".env.alerts")

# 通知先として GitHub / Render の両方に登録するキー
ALERT_KEYS = [
    "BREVO_API_KEY",
    "ALERT_EMAILS",
    "ALERT_MAIL_FROM",
    "ALERT_LINE_CHANNEL_ACCESS_TOKEN",
    "ALERT_LINE_USER_IDS",
    "ALERT_WEBHOOK_URL",
]


# ──────────────────────────── 共通 ────────────────────────────


def read_env_file(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        sys.exit(f"{path} がありません。.env.alerts.example をコピーして値を埋めてください。")
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def http(method: str, url: str, *, headers: dict[str, str] | None = None, body: dict | None = None, timeout: int = 30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            return res.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            parsed = raw.decode("utf-8", "replace")
        return e.code, parsed


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def fail(msg: str) -> None:
    print(f"  ❌ {msg}")


# ──────────────────────────── 検証 ────────────────────────────


def validate(values: dict[str, str]) -> bool:
    print("1) 設定値の検証")
    good = True
    emails = [e for e in values.get("ALERT_EMAILS", "").split(",") if e.strip()]
    for e in emails:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e.strip()):
            fail(f"ALERT_EMAILS の形式が不正: {e}")
            good = False
    line_token = values.get("ALERT_LINE_CHANNEL_ACCESS_TOKEN", "")
    line_users = [u.strip() for u in values.get("ALERT_LINE_USER_IDS", "").split(",") if u.strip()]
    for u in line_users:
        if not re.fullmatch(r"U[0-9a-f]{32}", u):
            fail(f"ALERT_LINE_USER_IDS の形式が不正（U + 32桁の16進）: {u}")
            good = False
    if bool(line_token) != bool(line_users):
        fail("LINE はトークンとユーザーIDの両方が必要です")
        good = False
    if not (values.get("BREVO_API_KEY") and emails) and not (line_token and line_users) and not values.get("ALERT_WEBHOOK_URL"):
        fail("通知先が1つもありません（メール／LINE／Webhook のいずれかを設定してください）")
        good = False

    # 疎通（ネットワーク到達性込み）
    if line_token:
        st, body = http("GET", "https://api.line.me/v2/bot/info", headers={"Authorization": f"Bearer {line_token}"})
        if st == 200 and isinstance(body, dict):
            ok(f"LINE トークン有効: 公式アカウント「{body.get('displayName')}」（顧客向けと別アカウントか確認してください）")
        else:
            fail(f"LINE トークンが無効です（HTTP {st}）")
            good = False
    if values.get("BREVO_API_KEY"):
        st, body = http("GET", "https://api.brevo.com/v3/account", headers={"api-key": values["BREVO_API_KEY"]})
        if st == 200:
            ok(f"Brevo キー有効: {body.get('email') if isinstance(body, dict) else ''}")
        else:
            fail(f"Brevo キーが無効です（HTTP {st}）")
            good = False
    if values.get("ALERT_WEBHOOK_URL"):
        ok("Webhook URL を登録します（疎通は最後のテスト通知で確認）")
    return good


# ──────────────────────────── GitHub ────────────────────────────


def github_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}


def seal(public_key_b64: str, value: str) -> str:
    try:
        from nacl import encoding, public  # type: ignore
    except ImportError:
        sys.exit("PyNaCl が必要です: backend\\.venv\\Scripts\\python.exe -m pip install pynacl")
    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode("utf-8"))
    return base64.b64encode(sealed).decode("utf-8")


def setup_github(token: str, values: dict[str, str], dry_run: bool) -> bool:
    print("2) GitHub Secrets の登録")
    if not token:
        fail("GITHUB_TOKEN が未設定のためスキップ（.env.alerts に Fine-grained PAT を設定）")
        return False
    st, me = http("GET", "https://api.github.com/user", headers=github_headers(token))
    if st != 200:
        fail(f"GitHub トークンが無効です（HTTP {st}）")
        return False
    ok(f"GitHub 認証: {me.get('login')}")
    st, key = http("GET", f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=github_headers(token))
    if st != 200:
        fail(f"Secrets の公開鍵を取得できません（HTTP {st}: {key}）。PAT の権限に Secrets: Read and write が必要です")
        return False
    all_ok = True
    for k in ALERT_KEYS:
        v = values.get(k, "")
        if not v:
            continue
        if dry_run:
            ok(f"[dry-run] {k} を登録（{len(v)} 文字）")
            continue
        st, body = http(
            "PUT",
            f"https://api.github.com/repos/{REPO}/actions/secrets/{k}",
            headers=github_headers(token),
            body={"encrypted_value": seal(key["key"], v), "key_id": key["key_id"]},
        )
        if st in (201, 204):
            ok(f"{k} を登録（{'作成' if st == 201 else '更新'}）")
        else:
            fail(f"{k} の登録に失敗（HTTP {st}: {body}）")
            all_ok = False
    return all_ok


def dispatch_and_wait(token: str, dry_run: bool) -> None:
    print("4) 疎通テスト（Actions「Uptime alert」を force_notify=true で起動）")
    if dry_run:
        ok("[dry-run] 起動をスキップ")
        return
    st, _ = http(
        "POST",
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches",
        headers=github_headers(token),
        body={"ref": "main", "inputs": {"force_notify": "true"}},
    )
    if st != 204:
        fail(f"起動に失敗（HTTP {st}）。PAT の権限に Actions: Read and write が必要です")
        return
    ok("起動しました。完了を待ちます（最大3分）…")
    started = time.time()
    run = None
    while time.time() - started < 180:
        time.sleep(10)
        st, body = http(
            "GET",
            f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs?event=workflow_dispatch&per_page=1",
            headers=github_headers(token),
        )
        runs = (body or {}).get("workflow_runs") or []
        if runs:
            run = runs[0]
            if run.get("status") == "completed":
                break
    if not run:
        warn("実行が見つかりませんでした。Actions タブで確認してください")
        return
    concl = run.get("conclusion")
    (ok if concl == "success" else fail)(f"実行結果: {run.get('status')} / {concl} → {run.get('html_url')}")
    print("   受信を確認してください: メール（件名 [カタヅケ監視][TEST]）／LINE／Webhook")


# ──────────────────────────── Render ────────────────────────────


def setup_render(api_key: str, values: dict[str, str], dry_run: bool) -> bool:
    print("3) Render 環境変数の登録")
    if not api_key:
        fail("RENDER_API_KEY が未設定のためスキップ（Render の Account Settings > API Keys で発行）")
        return False
    h = {"Authorization": f"Bearer {api_key}"}
    st, services = http("GET", "https://api.render.com/v1/services?limit=50", headers=h)
    if st != 200:
        fail(f"Render API に接続できません（HTTP {st}: {services}）")
        return False
    svc = None
    for item in services or []:
        s = item.get("service") or item
        if s.get("name") == RENDER_SERVICE_NAME:
            svc = s
            break
    if not svc:
        fail(f"サービス {RENDER_SERVICE_NAME} が見つかりません")
        return False
    ok(f"サービス: {svc['name']} ({svc['id']})")
    all_ok = True
    for k in ALERT_KEYS:
        v = values.get(k, "")
        if not v:
            continue
        if dry_run:
            ok(f"[dry-run] {k} を登録（{len(v)} 文字）")
            continue
        st, body = http("PUT", f"https://api.render.com/v1/services/{svc['id']}/env-vars/{k}", headers=h, body={"value": v})
        if st in (200, 201):
            ok(f"{k} を登録")
        else:
            fail(f"{k} の登録に失敗（HTTP {st}: {body}）")
            all_ok = False
    if all_ok and not dry_run:
        ok("Render は環境変数の更新で自動再デプロイされます（数分後に /health の commit は変わらず、アラート設定が有効になります）")
    return all_ok


# ──────────────────────────── main ────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="登録せず検証と表示だけ行う")
    ap.add_argument("--skip-github", action="store_true")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--no-test", action="store_true", help="疎通テストの起動を行わない")
    args = ap.parse_args()

    values = read_env_file(ENV_FILE)
    print(f"設定ファイル: {ENV_FILE}\n")
    if not validate(values):
        print("\n検証に失敗しました。値を直して再実行してください。")
        return 1
    gh_ok = True
    if not args.skip_github:
        gh_ok = setup_github(values.get("GITHUB_TOKEN", ""), values, args.dry_run)
    if not args.skip_render:
        setup_render(values.get("RENDER_API_KEY", ""), values, args.dry_run)
    if gh_ok and not args.skip_github and not args.no_test:
        dispatch_and_wait(values.get("GITHUB_TOKEN", ""), args.dry_run)
    print("\n完了。以後は5分毎の外形監視と、アプリ内の例外・5xx検知が通知されます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
