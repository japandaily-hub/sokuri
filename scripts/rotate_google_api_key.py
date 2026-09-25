#!/usr/bin/env python3
"""GOOGLE_API_KEY（Gemini）を1コマンドで差し替える。人がやるのは「新キーをコピー」と「旧キーの削除」だけ。

使い方（リポジトリ直下で）:
    1. https://aistudio.google.com/apikey で「API キーを作成」→ 表示されたキーをコピー
       （AI Studio で作れない場合は Cloud コンソールの「認証情報」で、現行キーと同じプロジェクトに
       Gemini API に制限したキーを作る。サービスアカウントへのバインドが必須で "AQ." 形式になる）
    2. python scripts/rotate_google_api_key.py            （--dry-run で書き込みなしの予行）
    3. 画面の指示どおり AI Studio で旧キーを削除して Enter → 失効を自動確認して完了

やること（値は一切表示しない。表示は文字数とキー末尾4文字のみ）:
    - 新キーをクリップボードから読む（取れなければ非表示入力）。形式・旧キーとの相違・Gemini API 疎通を検証
    - 失効させるべきキーを洗い出す（ローカル backend/.env と本番 Render の現行値。差し替え前に有効なものだけ）
    - Render（sokuri-backend）の GOOGLE_API_KEY を新キーにし、読み戻して一致を確認
    - 再デプロイを必ず起動して live まで待つ（env-vars API はダッシュボードと違い自動再デプロイされない。
      既に新キーが入っていても、前回の実行がデプロイ前に止まった可能性があるので毎回デプロイする）
    - 旧キー削除後、そのキーが Gemini API で拒否されることを確認（削除漏れの検出）
    - 失効を確認できたら、ローカル backend/.env の GOOGLE_API_KEY を置き換え（他の行・改行コードは保持）
      （先に書き換えると、中断後の再実行で漏えいキーを見失うため最後に回す）
    - クリップボード（と Win+V 履歴）を消去（途中で失敗しても必ず実行）
旧キーは「本番が新キーで起動し直した後」にだけ削除を案内するので、差し替え中に AI 解析は止まらない。
途中で止まっても、同じコマンドを再実行すれば安全にやり直せる（旧キーは削除しないこと）。
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ops_bootstrap import render_put_env, render_service_id, wait_render_deploy  # noqa: E402
from setup_alerts import ENV_FILE, fail, http, ok, read_env_file, warn  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_KEY = "GOOGLE_API_KEY"
LOCAL_BACKEND_ENV = os.path.join("backend", ".env")
BACKEND_URL = os.environ.get("KDZ_BACKEND_URL", "https://sokuri-backend.onrender.com")
RENDER_API = "https://api.render.com/v1"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# 旧 URL（/app/apikey）は 2026-09 時点で「Page not found」になるため現行の URL を案内する。
AI_STUDIO_URL = "https://aistudio.google.com/apikey"
# 旧形式（"AIza" で始まる 39 文字）と、サービスアカウントにバインドされた新形式（"AQ." で始まる）の
# 両方を受け付ける。2026-09 時点で Cloud コンソールから Gemini API に制限したキーを作ると、
# サービスアカウントへのバインドが必須になり新形式で発行される（実測 53 文字）。長さは将来の
# 変更に備えて幅を持たせ、最終判定は Gemini API への疎通確認（gemini_status）で行う。
KEY_PATTERN = re.compile(r"^(?:AIza[0-9A-Za-z_\-]{35}|AQ\.[0-9A-Za-z_\-.]{30,200})$")
# 同名の実行ファイルをカレントから拾わないよう絶対パスで呼ぶ
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
ABORT_HINT = "旧キーはまだ削除せず、原因を解消してから同じコマンドを再実行してください"


def safe_http(method: str, url: str, **kwargs):
    """setup_alerts.http は HTTPError しか捕捉しないため、接続断・タイムアウトを (0, None) に畳む。"""
    try:
        return http(method, url, **kwargs)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        warn(f"通信エラー（{type(exc).__name__}）: {url.split('?')[0]}")
        return 0, None


def gemini_status(api_key: str) -> int:
    """Gemini API にキーを渡して HTTP ステータスだけ返す。キーは URL でなくヘッダで送る（ログ残り防止）。"""
    st, _ = safe_http("GET", GEMINI_MODELS_URL, headers={"x-goog-api-key": api_key}, timeout=30)
    return st


def tail(key: str) -> str:
    return f"…{key[-4:]}"


# ──────────────────────────── クリップボード ────────────────────────────


def _powershell(command: str) -> str | None:
    if os.name != "nt" or not os.path.exists(POWERSHELL):
        return None
    try:
        res = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=15, check=False)
        return res.stdout or ""
    except (OSError, subprocess.SubprocessError) as exc:
        warn(f"PowerShell を実行できませんでした（{type(exc).__name__}）")
        return None


def read_clipboard() -> str:
    return (_powershell("Get-Clipboard -Raw") or "").strip()


def clear_clipboard() -> None:
    script = (
        "Set-Clipboard -Value ' ';"
        " try { $null = [Windows.ApplicationModel.DataTransfer.Clipboard,Windows.ApplicationModel.DataTransfer,ContentType=WindowsRuntime];"
        " [void][Windows.ApplicationModel.DataTransfer.Clipboard]::ClearHistory() } catch { }"
    )
    if _powershell(script) is None:
        warn("クリップボードを自動消去できません。別の文字をコピーし、Win+V の履歴からも削除してください")
    else:
        ok("クリップボード（Win+V 履歴を含む）を消去しました（クラウド同期を使っている場合は設定から同期データも消去）")


def obtain_new_key() -> tuple[str, bool]:
    """(新キー, クリップボード由来か) を返す。"""
    clip = read_clipboard()
    if KEY_PATTERN.match(clip):
        ok(f"クリップボードから新キーを取得（{len(clip)} 文字）")
        return clip, True
    if clip:
        warn("クリップボードの内容は API キーの形式ではありません")
    return getpass.getpass("  新しいキーを貼り付けて Enter（画面には表示されません）: ").strip(), False


# ──────────────────────────── ローカル .env ────────────────────────────


def read_local_key(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", newline="") as f:
        for line in f:
            if line.startswith(f"{ENV_KEY}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def write_local_key(path: str, new_key: str) -> bool:
    """backend/.env の該当行だけを置き換える。改行コード・他の行はそのまま。一時ファイル経由で原子的に書く。"""
    with open(path, encoding="utf-8", newline="") as f:
        lines = f.readlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{ENV_KEY}="):
            eol = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
            lines[i] = f"{ENV_KEY}={new_key}{eol}"
            replaced = True
    if not replaced:
        eol = "\r\n" if lines and lines[-1].endswith("\r\n") else "\n"
        if lines and not lines[-1].endswith(("\n", "\r\n")):
            lines[-1] += eol
        lines.append(f"{ENV_KEY}={new_key}{eol}")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except OSError as exc:
        fail(f"{path} の書き換えに失敗（{type(exc).__name__}）")
        return False
    finally:
        # 平文キー入りの一時ファイルを残さない（Ctrl-C を含む全経路）
        if os.path.exists(tmp):
            os.remove(tmp)


# ──────────────────────────── Render ────────────────────────────


def render_current(api_key: str, svc_id: str) -> tuple[bool, str | None]:
    """(取得成功か, 現行値)。ops_bootstrap.render_get_env は「未設定」と「API 失敗」を区別できないため自前で読む。"""
    st, envs = safe_http("GET", f"{RENDER_API}/services/{svc_id}/env-vars?limit=100", headers={"Authorization": f"Bearer {api_key}"})
    if st != 200 or not isinstance(envs, list):
        return False, None
    for item in envs:
        ev = item.get("envVar") or item
        if ev.get("key") == ENV_KEY:
            return True, (ev.get("value") or None)
    return True, None


def trigger_deploy(api_key: str, svc_id: str) -> str | None:
    st, body = safe_http("POST", f"{RENDER_API}/services/{svc_id}/deploys", headers={"Authorization": f"Bearer {api_key}"}, body={"clearCache": "do_not_clear"})
    deploy_id = body.get("id") if isinstance(body, dict) else None
    if st not in (200, 201) or not deploy_id:
        fail(f"再デプロイの起動に失敗（HTTP {st}）")
        return None
    ok("再デプロイを起動しました")
    return deploy_id


def readyz_sanity(max_wait: int = 5 * 60) -> bool:
    """本番が起動して AI 解析の設定を持っていることの確認。/readyz はキーの有無しか示さないので、
    新キーで動いている根拠は「新キーを書いた後に起動したデプロイが live」の方で担保する。"""
    deadline = time.time() + max_wait
    last = "unknown"
    while time.time() < deadline:
        st, body = safe_http("GET", f"{BACKEND_URL}/readyz", timeout=60)
        if st == 200 and isinstance(body, dict):
            gemini = (body.get("config") or {}).get("gemini")
            last = f"status={body.get('status')} gemini={gemini}"
            if body.get("status") == "ready" and gemini is True:
                ok(f"本番 /readyz: {last}")
                return True
        else:
            last = f"HTTP {st}"
        time.sleep(10)
    fail(f"本番 /readyz が期待状態になりません（最後: {last}）")
    return False


# ──────────────────────────── 旧キー失効 ────────────────────────────


def wait_revoked(old_key: str, label: str) -> bool:
    """人が AI Studio で旧キーを削除するのを待ち、Gemini API が拒否することを確かめる。
    呼び出し前に「このキーは有効（200）だった」ことを確認済みなので、4xx への変化＝削除の反映とみなせる。"""
    for attempt in range(1, 4):
        input(f"\n  👉 {AI_STUDIO_URL} で末尾「{tail(old_key)}」のキー（{label}）を削除したら Enter: ")
        last = 0
        for _ in range(6):  # 削除の反映には数十秒かかることがある
            last = gemini_status(old_key)
            if last in (400, 401, 403):
                ok(f"末尾「{tail(old_key)}」は失効済み（Gemini API が HTTP {last} で拒否）")
                return True
            time.sleep(10)
        warn(f"末尾「{tail(old_key)}」がまだ拒否されません（HTTP {last}）。削除できているか確認してください（{attempt}/3）")
    fail(f"末尾「{tail(old_key)}」の失効を確認できませんでした。AI Studio で削除を確認してください")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="検証だけ行い、Render・backend/.env には書き込まない")
    args = ap.parse_args()
    os.chdir(ROOT)

    print("1) Render API キーの読み込み")
    render_key = read_env_file(ENV_FILE).get("RENDER_API_KEY", "")
    if not render_key:
        fail(f"{ENV_FILE} に RENDER_API_KEY がありません")
        return 2
    ok("RENDER_API_KEY を読み込みました")

    print("2) 新キーの取得と検証")
    new_key, _ = obtain_new_key()
    try:
        return rotate(render_key, new_key, args.dry_run)
    finally:
        # 形式不一致で非表示入力に回った場合もクリップボードに本物のキーが残り得るので常に消す。
        # dry-run だけは本実行でそのまま使えるよう残す
        if not args.dry_run:
            clear_clipboard()


def rotate(render_key: str, new_key: str, dry_run: bool) -> int:
    if not KEY_PATTERN.match(new_key):
        fail("新キーの形式が不正です（AIza で始まる 39 文字、または AQ. で始まる新形式のはず）")
        return 2
    st = gemini_status(new_key)
    if st != 200:
        fail(f"新キーで Gemini API に接続できません（HTTP {st}）。作成直後なら1分ほど待って再実行してください")
        return 1
    ok("新キーで Gemini API に接続できました")

    print("3) 失効させるキーの洗い出し（ローカル backend/.env と本番 Render）")
    svc_id = render_service_id(render_key)
    if not svc_id:
        return 1
    fetched, current = render_current(render_key, svc_id)
    if not fetched:
        fail(f"本番の {ENV_KEY} を取得できません（Render API エラー）。{ABORT_HINT}")
        return 1
    local_old = read_local_key(LOCAL_BACKEND_ENV)
    candidates: dict[str, str] = {}
    for key, label in ((local_old, "ローカル backend/.env の旧キー"), (current, "本番 Render の旧キー")):
        if not key or key == new_key:
            continue
        if not KEY_PATTERN.match(key):
            warn(f"{label} は API キーの形式ではありません（コメント混入等）。失効確認の対象外にします")
            continue
        candidates.setdefault(key, label)
    to_revoke: dict[str, str] = {}
    for key, label in candidates.items():
        st = gemini_status(key)
        if st == 200:
            to_revoke[key] = label
            ok(f"{label}: 末尾「{tail(key)}」は有効 → 差し替え後に削除します")
        elif st in (400, 401, 403):
            ok(f"{label}: 末尾「{tail(key)}」は既に無効（HTTP {st}）→ 削除不要")
        else:
            fail(f"{label}: 末尾「{tail(key)}」の有効性を判定できません（HTTP {st}）。{ABORT_HINT}")
            return 1
    print(f"  本番の現行値: {'未設定' if current is None else ('新キー' if current == new_key else f'末尾「{tail(current)}」')}")

    if dry_run:
        ok("[dry-run] ここまで。Render・backend/.env には書き込んでいません")
        return 0

    print("4) Render へ書き込み（読み戻して一致を確認）")
    if current != new_key and not render_put_env(render_key, svc_id, ENV_KEY, new_key, dry_run=False):
        fail(ABORT_HINT)
        return 1
    for _ in range(3):  # 書き込み直後の読み戻しで反映遅れに当たっても誤中断しない
        fetched, after = render_current(render_key, svc_id)
        if fetched and after == new_key:
            break
        time.sleep(3)
    if not fetched or after != new_key:
        fail(f"本番の {ENV_KEY} が新キーになっていることを確認できません。{ABORT_HINT}")
        return 1
    ok("本番の設定値は新キーです")

    print("5) 再デプロイ（新キーでプロセスを起動し直す）")
    deploy_id = trigger_deploy(render_key, svc_id)
    if not deploy_id or not wait_render_deploy(render_key, svc_id, deploy_id):
        fail(f"デプロイが live になりません。本番は旧キーで動いている可能性があります。{ABORT_HINT}")
        return 1

    print("7) 本番の起動確認（/readyz）")
    if not readyz_sanity():
        fail(ABORT_HINT)
        return 1

    print("8) 旧キーの削除（ここだけ手作業）")
    if not to_revoke:
        ok("削除が必要な旧キーはありません")
    all_revoked = all([wait_revoked(key, label) for key, label in to_revoke.items()])
    print("\n注意: 廃止済みの旧 Railway バックエンド（Web からは未使用）も旧キーを持っている可能性があり、そちらの AI 解析は止まります（実害なし）")
    if not all_revoked:
        # ローカルの旧キーは「失効させるべきキー」の手掛かりなので、失効確認まで書き換えない（再実行で再発見できる）
        fail(f"{LOCAL_BACKEND_ENV} は旧キーのまま残しました。AI Studio で削除後、同じコマンドを再実行してください")
        return 1

    print("9) ローカル backend/.env の更新")
    if os.path.exists(LOCAL_BACKEND_ENV):
        if not write_local_key(LOCAL_BACKEND_ENV, new_key):
            return 1
        ok(f"{LOCAL_BACKEND_ENV} を新キーに置き換えました")
    else:
        warn(f"{LOCAL_BACKEND_ENV} が無いので省略")
    print("完了: 本番・ローカルとも新キーに切り替わり、旧キーは失効しました")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n中断しました。{ABORT_HINT}")
        sys.exit(130)
    except OSError as exc:  # 再利用した Render ヘルパー内の接続断・タイムアウト（URLError は OSError の派生）
        print(f"\n通信エラーで中断しました（{type(exc).__name__}）。{ABORT_HINT}")
        sys.exit(1)
