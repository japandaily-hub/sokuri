#!/usr/bin/env python3
"""自動運用（ops-cron）の初期設定を1コマンドで行う（ローカルで一度だけ実行）。

使い方:
    backend\\.venv\\Scripts\\python.exe scripts\\ops_bootstrap.py [--dry-run] [--probe-email ADDR] [--deploy]

やること（.env.alerts の GITHUB_TOKEN / RENDER_API_KEY を使う。値は一切表示しない）:
    1. OPS_JOB_TOKEN … Render に既にあれば再利用、無ければ生成。Render 環境変数と GitHub Secret の両方へ登録
    2. APP_ENCRYPTION_KEY_ESCROW … Render の APP_ENCRYPTION_KEY を取得し GitHub Secret として控えを置く
       （鍵の正本は Render・控えは GitHub の2系統。週次 key-check が一致を照合し、消失時は key-restore で書き戻す）
    3. RENDER_API_KEY … GitHub Secret へ（key-check / key-restore が Render API を叩くため）
    4. OPS_PROBE_CONTACT_EMAIL … --probe-email の値を Render 環境変数へ（運営自身のプローブ問い合わせの差出人）
    5. Render に環境変数を書いたら再デプロイを起動して live まで待つ（API 経由の env-vars 変更は
       ダッシュボードと違い自動再デプロイされない。--deploy で書き込みが無くても強制起動）
    6. 実証: Actions「Ops cron」を job=daily で起動し、完了（success）まで待って結果を表示（--no-verify で省略）
    ※ --admin-emails ADDR[,ADDR] を付けると Render の ADMIN_EMAILS を置き換える（棚卸しの是正用。再デプロイ＋実証まで自動）

認証情報・鍵はこのプロセス内でしか使わず、ファイルにも標準出力にも残さない（表示は文字数のみ）。
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from setup_alerts import (  # noqa: E402
    ENV_FILE,
    RENDER_SERVICE_NAME,
    REPO,
    fail,
    github_headers,
    http,
    ok,
    read_env_file,
    seal,
    warn,
)


OPS_WORKFLOW_FILE = "ops-cron.yml"


def desc(value: str) -> str:
    """値を出さずに長さだけ示す（ログ・端末に指紋も残さない）。"""
    return f"{len(value)} 文字"


# ──────────────────────────── Render ────────────────────────────


def render_service_id(api_key: str) -> str | None:
    st, services = http("GET", "https://api.render.com/v1/services?limit=50", headers={"Authorization": f"Bearer {api_key}"})
    if st != 200:
        fail(f"Render API に接続できません（HTTP {st}）")
        return None
    for item in services or []:
        s = item.get("service") or item
        if s.get("name") == RENDER_SERVICE_NAME:
            return s["id"]
    fail(f"サービス {RENDER_SERVICE_NAME} が見つかりません")
    return None


def render_get_env(api_key: str, svc_id: str, key: str) -> str | None:
    st, envs = http("GET", f"https://api.render.com/v1/services/{svc_id}/env-vars?limit=100", headers={"Authorization": f"Bearer {api_key}"})
    if st != 200:
        return None
    for item in envs or []:
        ev = item.get("envVar") or item
        if ev.get("key") == key and ev.get("value"):
            return ev["value"]
    return None


def render_put_env(api_key: str, svc_id: str, key: str, value: str, dry_run: bool) -> bool:
    if dry_run:
        ok(f"[dry-run] Render {key} を登録（{desc(value)}）")
        return True
    st, body = http("PUT", f"https://api.render.com/v1/services/{svc_id}/env-vars/{key}", headers={"Authorization": f"Bearer {api_key}"}, body={"value": value})
    if st in (200, 201):
        ok(f"Render {key} を登録（{desc(value)}）")
        return True
    # 応答本文は出さない（送信値がエコーされる可能性を排除）
    fail(f"Render {key} の登録に失敗（HTTP {st}）")
    return False


# ──────────────────────────── GitHub ────────────────────────────


def github_public_key(token: str) -> dict | None:
    st, key = http("GET", f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=github_headers(token))
    if st != 200:
        fail(f"GitHub Secrets の公開鍵を取得できません（HTTP {st}: {key}）。PAT に Secrets: Read and write が必要")
        return None
    return key


def github_put_secret(token: str, pub: dict, name: str, value: str, dry_run: bool) -> bool:
    if dry_run:
        ok(f"[dry-run] GitHub Secret {name} を登録（{desc(value)}）")
        return True
    st, body = http(
        "PUT",
        f"https://api.github.com/repos/{REPO}/actions/secrets/{name}",
        headers=github_headers(token),
        body={"encrypted_value": seal(pub["key"], value), "key_id": pub["key_id"]},
    )
    if st in (201, 204):
        ok(f"GitHub Secret {name} を登録（{'作成' if st == 201 else '更新'}・{desc(value)}）")
        return True
    fail(f"GitHub Secret {name} の登録に失敗（HTTP {st}: {str(body)[:120]}）")
    return False


# ──────────────────────────── main ────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="何も書き込まず、やることだけ表示")
    ap.add_argument("--probe-email", default="", help="Render の OPS_PROBE_CONTACT_EMAIL に設定する差出人")
    ap.add_argument("--deploy", action="store_true", help="Render への書き込みが無くても再デプロイを起動する")
    ap.add_argument(
        "--skip-escrow",
        action="store_true",
        help="手順3（暗号鍵の控えを GitHub Secret へ置く）を飛ばす。控えだけ後で別途この手順を実行する場合に使う",
    )
    ap.add_argument("--no-verify", action="store_true", help="最後の実証（Actions の daily 起動と完了待ち）を行わない")
    ap.add_argument(
        "--admin-emails",
        default="",
        help="Render の ADMIN_EMAILS をこの値（カンマ区切り）に置き換える。日次の棚卸しで未登録が検出されたときの是正用",
    )
    args = ap.parse_args()

    values = read_env_file(ENV_FILE)
    gh_token = values.get("GITHUB_TOKEN", "")
    render_key = values.get("RENDER_API_KEY", "")
    if not gh_token or not render_key:
        fail("GITHUB_TOKEN と RENDER_API_KEY の両方が .env.alerts に必要です")
        return 1

    print("1) 接続確認")
    svc_id = render_service_id(render_key)
    if not svc_id:
        return 1
    ok(f"Render サービス: {RENDER_SERVICE_NAME} ({svc_id})")
    pub = github_public_key(gh_token)
    if not pub:
        return 1
    ok(f"GitHub リポジトリ: {REPO}")

    all_ok = True
    wrote_render = False  # Render の環境変数を書いたら最後に必ず再デプロイする

    print("2) OPS_JOB_TOKEN（運営ジョブの共有トークン）")
    token = render_get_env(render_key, svc_id, "OPS_JOB_TOKEN")
    if token:
        ok(f"Render に設定済みのトークンを再利用（{desc(token)}）")
    else:
        token = secrets.token_urlsafe(32)
        ok("新しいトークンを生成")
        all_ok &= render_put_env(render_key, svc_id, "OPS_JOB_TOKEN", token, args.dry_run)
        wrote_render = True
    all_ok &= github_put_secret(gh_token, pub, "OPS_JOB_TOKEN", token, args.dry_run)

    print("3) APP_ENCRYPTION_KEY の控え（GitHub Secret APP_ENCRYPTION_KEY_ESCROW）")
    if args.skip_escrow:
        warn("--skip-escrow のため飛ばしました（週次 key-check が『控え未登録』を通知し続けます。後で本スクリプトを --skip-escrow 無しで実行）")
    else:
        enc = render_get_env(render_key, svc_id, "APP_ENCRYPTION_KEY")
        if not enc:
            fail("Render に APP_ENCRYPTION_KEY がありません（先に設定してください）")
            all_ok = False
        else:
            all_ok &= github_put_secret(gh_token, pub, "APP_ENCRYPTION_KEY_ESCROW", enc, args.dry_run)

    print("4) RENDER_API_KEY（GitHub Secret・key-check / key-restore 用）")
    all_ok &= github_put_secret(gh_token, pub, "RENDER_API_KEY", render_key, args.dry_run)

    print("5) OPS_PROBE_CONTACT_EMAIL（プローブ問い合わせの差出人）")
    if args.probe_email:
        current = render_get_env(render_key, svc_id, "OPS_PROBE_CONTACT_EMAIL")
        if current == args.probe_email:
            ok("Render OPS_PROBE_CONTACT_EMAIL は設定済み（変更なし）")
        else:
            all_ok &= render_put_env(render_key, svc_id, "OPS_PROBE_CONTACT_EMAIL", args.probe_email, args.dry_run)
            wrote_render = True
    else:
        current = render_get_env(render_key, svc_id, "OPS_PROBE_CONTACT_EMAIL")
        (ok if current else warn)(f"--probe-email 未指定のため変更なし（現在: {'設定済み' if current else '未設定'}）")

    if args.admin_emails:
        print("5b) ADMIN_EMAILS の是正（棚卸しで未登録が出たアドレスを外す／登録済み管理者だけにする）")
        wanted = ",".join(e.strip() for e in args.admin_emails.split(",") if e.strip())
        current = render_get_env(render_key, svc_id, "ADMIN_EMAILS") or ""
        if current == wanted:
            ok("Render ADMIN_EMAILS は既にその値（変更なし）")
        else:
            all_ok &= render_put_env(render_key, svc_id, "ADMIN_EMAILS", wanted, args.dry_run)
            wrote_render = True
            warn("render.yaml の ADMIN_EMAILS も同じ値に揃えてコミットしてください（既存サービスには同期されないが、正本として）")

    # Render の env-vars API は（ダッシュボードと違い）再デプロイを起動しない。書き込んだ値を
    # backend に読み込ませるには deploys を明示的に叩く必要がある（実測 2026-09-06: 90 秒待っても
    # 旧プロセスのままで daily が 403 になった）。Render 側に何か書いたら必ずデプロイする。
    render_written = wrote_render or args.deploy
    deploy_id = None
    if render_written and not args.dry_run:
        st, body = http("POST", f"https://api.render.com/v1/services/{svc_id}/deploys", headers={"Authorization": f"Bearer {render_key}"}, body={"clearCache": "do_not_clear"})
        deploy_id = (body or {}).get("id") if isinstance(body, dict) else None
        (ok if st in (200, 201) else fail)(f"Render 再デプロイを起動 → HTTP {st}")
        all_ok &= st in (200, 201)

    if all_ok and not args.dry_run and not args.no_verify:
        if deploy_id:
            all_ok &= wait_render_deploy(render_key, svc_id, deploy_id)
        all_ok &= verify_via_actions(gh_token)

    print("完了" if all_ok else "一部失敗（上の ❌ を確認）")
    return 0 if all_ok else 1


def wait_render_deploy(api_key: str, svc_id: str, deploy_id: str, max_wait: int = 10 * 60) -> bool:
    """起動した Render デプロイが live になるまで待つ（backend が新しい環境変数で起動した保証）。"""
    print("6) Render の再デプロイ完了を待つ（最大 10 分）")
    h = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + max_wait
    status = "unknown"
    while time.time() < deadline:
        time.sleep(15)
        st, body = http("GET", f"https://api.render.com/v1/services/{svc_id}/deploys/{deploy_id}", headers=h)
        status = (body or {}).get("status", "unknown") if st == 200 and isinstance(body, dict) else f"HTTP {st}"
        if status in ("live", "build_failed", "update_failed", "canceled", "deactivated"):
            break
    (ok if status == "live" else fail)(f"デプロイ状態: {status}")
    return status == "live"


def verify_via_actions(token: str) -> bool:
    """Actions「Ops cron」を job=daily で起動し、完了まで待って結果を表示する（初期設定の実証）。"""
    print("7) 実証（Actions「Ops cron」job=daily を起動して完了を待つ）")
    h = github_headers(token)
    st, _ = http(
        "POST",
        f"https://api.github.com/repos/{REPO}/actions/workflows/{OPS_WORKFLOW_FILE}/dispatches",
        headers=h,
        body={"ref": "main", "inputs": {"job": "daily"}},
    )
    if st != 204:
        fail(f"ワークフローの起動に失敗（HTTP {st}）。Actions から手動で job=daily を実行してください")
        return False
    ok("起動しました。完了を待ちます（最大 12 分）")
    deadline = time.time() + 12 * 60
    run = None
    while time.time() < deadline:
        time.sleep(15)
        st, body = http(
            "GET",
            f"https://api.github.com/repos/{REPO}/actions/workflows/{OPS_WORKFLOW_FILE}/runs?event=workflow_dispatch&per_page=1",
            headers=h,
        )
        runs = (body or {}).get("workflow_runs") if st == 200 and isinstance(body, dict) else None
        if runs:
            run = runs[0]
            if run.get("status") == "completed":
                break
    if not run or run.get("status") != "completed":
        warn("完了を確認できませんでした（Actions の画面で結果を確認してください）")
        return False
    (ok if run.get("conclusion") == "success" else fail)(f"daily → {run.get('conclusion')}  {run.get('html_url')}")
    return run.get("conclusion") == "success"


if __name__ == "__main__":
    sys.exit(main())
