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
    5. --deploy 指定時のみ Render の再デプロイを起動（環境変数の追加は Render が自動で再デプロイするため通常不要）

認証情報・鍵はこのプロセス内でしか使わず、ファイルにも標準出力にも残さない（表示は SHA-256 の先頭8桁のみ）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys

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


def sha8(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


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
        ok(f"[dry-run] Render {key} を登録（sha256 {sha8(value)}…）")
        return True
    st, body = http("PUT", f"https://api.render.com/v1/services/{svc_id}/env-vars/{key}", headers={"Authorization": f"Bearer {api_key}"}, body={"value": value})
    if st in (200, 201):
        ok(f"Render {key} を登録（sha256 {sha8(value)}…）")
        return True
    fail(f"Render {key} の登録に失敗（HTTP {st}: {body}）")
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
        ok(f"[dry-run] GitHub Secret {name} を登録（sha256 {sha8(value)}…）")
        return True
    st, body = http(
        "PUT",
        f"https://api.github.com/repos/{REPO}/actions/secrets/{name}",
        headers=github_headers(token),
        body={"encrypted_value": seal(pub["key"], value), "key_id": pub["key_id"]},
    )
    if st in (201, 204):
        ok(f"GitHub Secret {name} を登録（{'作成' if st == 201 else '更新'}・sha256 {sha8(value)}…）")
        return True
    fail(f"GitHub Secret {name} の登録に失敗（HTTP {st}: {body}）")
    return False


# ──────────────────────────── main ────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="何も書き込まず、やることだけ表示")
    ap.add_argument("--probe-email", default="", help="Render の OPS_PROBE_CONTACT_EMAIL に設定する差出人")
    ap.add_argument("--deploy", action="store_true", help="最後に Render の再デプロイを起動する")
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

    print("2) OPS_JOB_TOKEN（運営ジョブの共有トークン）")
    token = render_get_env(render_key, svc_id, "OPS_JOB_TOKEN")
    if token:
        ok(f"Render に設定済みのトークンを再利用（sha256 {sha8(token)}…）")
    else:
        token = secrets.token_urlsafe(32)
        ok("新しいトークンを生成")
        all_ok &= render_put_env(render_key, svc_id, "OPS_JOB_TOKEN", token, args.dry_run)
    all_ok &= github_put_secret(gh_token, pub, "OPS_JOB_TOKEN", token, args.dry_run)

    print("3) APP_ENCRYPTION_KEY の控え（GitHub Secret APP_ENCRYPTION_KEY_ESCROW）")
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
        all_ok &= render_put_env(render_key, svc_id, "OPS_PROBE_CONTACT_EMAIL", args.probe_email, args.dry_run)
    else:
        current = render_get_env(render_key, svc_id, "OPS_PROBE_CONTACT_EMAIL")
        (ok if current else warn)(f"--probe-email 未指定のため変更なし（現在: {'設定済み' if current else '未設定'}）")

    if args.deploy and not args.dry_run:
        st, body = http("POST", f"https://api.render.com/v1/services/{svc_id}/deploys", headers={"Authorization": f"Bearer {render_key}"}, body={"clearCache": "do_not_clear"})
        (ok if st in (200, 201) else fail)(f"Render 再デプロイ → HTTP {st}")
        all_ok &= st in (200, 201)

    print("完了" if all_ok else "一部失敗（上の ❌ を確認）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
