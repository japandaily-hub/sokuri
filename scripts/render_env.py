#!/usr/bin/env python3
"""Render の環境変数を .env.alerts の RENDER_API_KEY で読み書きする（標準ライブラリのみ・値は表示しない）。

    python scripts/render_env.py get  KEY              … 設定の有無と長さだけ表示
    python scripts/render_env.py set  KEY VALUE        … 設定（既存は上書き）。Render が自動で再デプロイする
    python scripts/render_env.py set  KEY VALUE --show … 値を表示してよい非秘密（MAIL_FROM 等）だけ --show

Blueprint（render.yaml）の envVars は既存サービスへ同期されないため、本番で効かせる値の変更は
dashboard かこのコマンドで行い、render.yaml は実態に追従させる（scripts/render_drift_check.py が
キーの有無を突き合わせる）。用途例（INC-2026-09-08-1）:

    python scripts/render_env.py set MAIL_FROM katazuke.support@gmail.com --show
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "srv-d8enmu0g4nts73a43dhg")


def load_env_alerts() -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        with open(os.path.join(ROOT, ".env.alerts"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def _api(key: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        f"https://api.render.com/v1{path}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "kdz-ops"},
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            raw = res.read()
            return res.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["get", "set"])
    ap.add_argument("key")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--show", action="store_true", help="値を表示する（非秘密のみ）")
    args = ap.parse_args()
    api_key = os.environ.get("RENDER_API_KEY") or load_env_alerts().get("RENDER_API_KEY", "")
    if not api_key:
        print("RENDER_API_KEY が .env.alerts にありません", file=sys.stderr)
        return 2
    if args.action == "get":
        st, envs = _api(api_key, "GET", f"/services/{SERVICE_ID}/env-vars?limit=100")
        if st != 200 or not isinstance(envs, list):
            print(f"取得失敗 HTTP {st}", file=sys.stderr)
            return 1
        for item in envs:
            ev = item.get("envVar") or item
            if ev.get("key") == args.key:
                val = str(ev.get("value") or "")
                print(f"{args.key}: 設定あり（{len(val)} 文字）" + (f" = {val}" if args.show else ""))
                return 0
        print(f"{args.key}: 未設定")
        return 0
    if args.value is None:
        print("set には VALUE が必要です", file=sys.stderr)
        return 2
    st, _ = _api(api_key, "PUT", f"/services/{SERVICE_ID}/env-vars/{args.key}", {"value": args.value})
    if st not in (200, 201):
        print(f"{args.key} の設定に失敗（HTTP {st}）", file=sys.stderr)
        return 1
    print(f"✅ Render {args.key} を設定しました" + (f"（= {args.value}）" if args.show else f"（{len(args.value)} 文字）") + "。再デプロイが自動で始まります（1〜2 分）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
