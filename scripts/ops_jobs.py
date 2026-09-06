#!/usr/bin/env python3
"""カタヅケ自動運用ジョブ（GitHub Actions「Ops cron」から実行。標準ライブラリのみ）。

残っていた運営の手作業を機械実行に置き換える（r13・自動運用）:

    hourly      Render を起こしてリマインド処理（訪問日超過 / 入札ゼロ放置）を1周回す。
                Render Free は無通信でスピンダウンし、プロセス内の毎時ループごと止まるため
                外から叩く。
    daily       ① ADMIN_EMAILS の棚卸し（未登録・非admin・停止中があれば通知）
                ② 運営自身のプローブ問い合わせを対応済みへ
                ③ メール到達プローブ: 送信 → Brevo のイベント API で delivered まで追跡
                ④ Brevo の前日集計でバウンス・ブロック・エラーがあれば通知
    key-check   本番の APP_ENCRYPTION_KEY（Render）と GitHub Secrets の控え（ESCROW）が
                一致しているかを SHA-256 で照合（値は出力しない）。
    key-restore /readyz が「暗号鍵未設定」で、かつ Render 側の値が空のときだけ、控えから
                Render へ書き戻して再デプロイする（--force で条件を無視）。

失敗は運営へ通知（LINE / メール / Webhook・scripts/uptime_check.py の notify）し exit 1。
値そのものを標準出力に出さない（トークン・鍵・メールアドレスの列挙を避ける）。

環境変数:
  BACKEND_URL                 既定 https://sokuri-backend.onrender.com
  OPS_JOB_TOKEN               backend の OPS_JOB_TOKEN と同じ値（X-Ops-Token）
  BREVO_API_KEY               Brevo（イベント照会・通知メール）
  RENDER_API_KEY / RENDER_SERVICE_ID   key-check / key-restore（既定 service は sokuri-backend）
  APP_ENCRYPTION_KEY_ESCROW   GitHub Secrets に置いた暗号鍵の控え
  ALERT_*                     通知先（uptime_check.notify と同じ）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uptime_check import notify  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

BACKEND_URL = os.environ.get("BACKEND_URL", "https://sokuri-backend.onrender.com").rstrip("/")
OPS_JOB_TOKEN = os.environ.get("OPS_JOB_TOKEN", "")
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "srv-d8enmu0g4nts73a43dhg")
ESCROW = os.environ.get("APP_ENCRYPTION_KEY_ESCROW", "")

#: Brevo のイベント種別のうち「配送されなかった」と判定するもの
_BREVO_FAILURE_EVENTS = {"hardBounces", "hard_bounce", "blocked", "error", "invalid", "spam"}
_BREVO_POLL_SECONDS = 300
_BREVO_POLL_INTERVAL = 30


# ──────────────────────────── HTTP ────────────────────────────


def http(method: str, url: str, *, headers: dict[str, str] | None = None, body: dict | None = None, timeout: int = 60):
    """(status, json|text) を返す。接続エラーは (0, 例外名) にして呼び出し側で扱う。"""
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
            return e.code, (json.loads(raw) if raw else None)
        except Exception:  # noqa: BLE001
            return e.code, raw.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def wake_backend(max_wait: int = 90) -> bool:
    """/health が 200 を返すまで待つ（スピンダウンからの復帰待ち）。"""
    deadline = time.time() + max_wait
    while True:
        st, _ = http("GET", f"{BACKEND_URL}/health", timeout=30)
        if st == 200:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(5)


def post_job(path: str):
    if not OPS_JOB_TOKEN:
        return 0, "OPS_JOB_TOKEN が未設定"
    return http("POST", f"{BACKEND_URL}/api/v1/admin/jobs/{path}", headers={"X-Ops-Token": OPS_JOB_TOKEN}, timeout=120)


def brevo(method: str, path: str, *, body: dict | None = None):
    return http(method, f"https://api.brevo.com/v3{path}", headers={"api-key": BREVO_API_KEY}, body=body)


def render(method: str, path: str, *, body: dict | None = None):
    return http(method, f"https://api.render.com/v1{path}", headers={"Authorization": f"Bearer {RENDER_API_KEY}"}, body=body)


def sha8(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def fail(title: str, body: str) -> int:
    """運営へ通知して exit code 1 を返す（通知先未設定でも stdout には残す）。"""
    print(f"❌ {title}\n{body}")
    sent = notify(f"[カタヅケ運用] {title}", f"❌ {title}\n{body}")
    print(f"notified: {sent or 'none'}")
    return 1


# ──────────────────────────── hourly ────────────────────────────


def job_hourly() -> int:
    if not wake_backend():
        return fail("backend が起きません（/health 非200が90秒継続）", f"{BACKEND_URL}/health")
    st, body = post_job("reminders")
    if st != 200:
        return fail("リマインドの定期実行に失敗", f"POST /admin/jobs/reminders → HTTP {st}: {str(body)[:300]}")
    print(f"✅ reminders: overdue={body.get('overdue')} no_bid={body.get('no_bid')}")
    return 0


# ──────────────────────────── daily ────────────────────────────


def _poll_brevo_delivery(message_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    """messageId ごとに delivered / 失敗 / 未確定 を分ける（最大5分）。"""
    pending = list(message_ids)
    delivered: list[str] = []
    failed: list[str] = []
    deadline = time.time() + _BREVO_POLL_SECONDS
    while pending and time.time() < deadline:
        for mid in list(pending):
            st, body = brevo("GET", f"/smtp/statistics/events?days=2&limit=50&messageId={urllib.parse.quote(mid, safe='')}")
            events = {e.get("event") for e in (body or {}).get("events", [])} if st == 200 and isinstance(body, dict) else set()
            if "delivered" in events:
                delivered.append(mid)
                pending.remove(mid)
            elif events & _BREVO_FAILURE_EVENTS:
                failed.append(mid)
                pending.remove(mid)
        if pending:
            time.sleep(_BREVO_POLL_INTERVAL)
    return delivered, failed, pending


def job_daily() -> int:
    problems: list[str] = []
    if not wake_backend():
        return fail("backend が起きません（/health 非200が90秒継続）", f"{BACKEND_URL}/health")

    # ① ADMIN_EMAILS の棚卸し
    st, body = post_job("admin-audit")
    if st != 200:
        problems.append(f"admin-audit → HTTP {st}: {str(body)[:200]}")
    else:
        ng = [e for e in body.get("entries", []) if not e.get("ok")]
        print(f"{'✅' if body.get('ok') else '❌'} admin-audit: entries={len(body.get('entries', []))} ng={len(ng)} active_admins={body.get('active_admin_count')}")
        if not body.get("ok"):
            problems.append(
                f"ADMIN_EMAILS の棚卸しで不整合 {len(ng)} 件（有効な管理者 {body.get('active_admin_count')} 人）。"
                "未登録は ADMIN_EMAILS から外すか、登録後に管理画面で『管理者にする』。"
            )

    # ② プローブ問い合わせを対応済みへ
    st, body = post_job("contacts/handle-probes")
    if st != 200:
        problems.append(f"contacts/handle-probes → HTTP {st}: {str(body)[:200]}")
    else:
        print(f"✅ handle-probes: handled={body.get('handled')} probe={'set' if body.get('probe_email') else 'unset'}")

    # ③ メール到達プローブ（受理≠配送）
    st, body = post_job("mail-probe")
    if st != 200:
        problems.append(f"mail-probe → HTTP {st}: {str(body)[:200]}")
    elif not body.get("sent"):
        problems.append(f"メール到達プローブを送れません（recipients={body.get('recipients')}）。BREVO_API_KEY / ADMIN_EMAILS / Brevo の日次上限を確認。")
    elif not BREVO_API_KEY:
        print("⚠️ BREVO_API_KEY 未設定のため配送追跡をスキップ")
    else:
        delivered, failed, pending = _poll_brevo_delivery(body.get("message_ids", []))
        print(f"{'✅' if not failed and not pending else '❌'} mail-probe: delivered={len(delivered)} failed={len(failed)} pending={len(pending)}")
        if failed or pending:
            problems.append(
                f"メール到達プローブ: 送信 {len(body.get('message_ids', []))} 通のうち配送確認 {len(delivered)}・"
                f"失敗 {len(failed)}・5分以内に未確定 {len(pending)}。Brevo の送信者認証・受信側のブロック・無料枠を確認。"
            )

    # ④ 前日集計（受理後の破棄検知）
    if BREVO_API_KEY:
        st, rep = brevo("GET", "/smtp/statistics/aggregatedReport?days=1")
        if st == 200 and isinstance(rep, dict):
            bad = {k: rep.get(k, 0) for k in ("hardBounces", "softBounces", "blocked", "error", "invalid", "spamReports")}
            total_bad = sum(int(v or 0) for v in bad.values())
            print(f"{'✅' if total_bad == 0 else '⚠️'} brevo(1d): requests={rep.get('requests')} delivered={rep.get('delivered')} bad={bad}")
            if total_bad:
                problems.append(f"Brevo 直近1日: 配送不能 {total_bad} 件 {json.dumps(bad, ensure_ascii=False)}（要求 {rep.get('requests')} / 配送 {rep.get('delivered')}）")
        else:
            problems.append(f"Brevo 集計の取得に失敗 → HTTP {st}")

    if problems:
        return fail("日次ジョブで要対応の項目", "\n".join(f"- {p}" for p in problems))
    print("✅ daily: all clear")
    return 0


# ──────────────────────────── key-check / key-restore ────────────────────────────


def _render_env(key: str) -> tuple[int, str | None]:
    st, body = render("GET", f"/services/{RENDER_SERVICE_ID}/env-vars/{key}")
    if st == 200 and isinstance(body, dict):
        ev = body.get("envVar") or body
        return st, (ev.get("value") or None)
    return st, None


def _readyz_degraded() -> tuple[int, list[str]]:
    st, body = http("GET", f"{BACKEND_URL}/readyz", timeout=30)
    if isinstance(body, dict):
        return st, list(body.get("degraded_config") or [])
    return st, []


def job_key_check() -> int:
    if not RENDER_API_KEY:
        return fail("鍵の照合ができません", "RENDER_API_KEY（GitHub Secrets）が未設定")
    if not ESCROW:
        return fail("暗号鍵の控えがありません", "GitHub Secrets の APP_ENCRYPTION_KEY_ESCROW が未設定。scripts/ops_bootstrap.py を実行して登録してください。")
    st, live = _render_env("APP_ENCRYPTION_KEY")
    if st != 200:
        return fail("Render の環境変数を取得できません", f"GET env-vars/APP_ENCRYPTION_KEY → HTTP {st}")
    if not live:
        return fail("本番の暗号鍵が空です", "Render の APP_ENCRYPTION_KEY が未設定。Actions「Ops cron」を job=key-restore で実行すると控えから復元します。")
    if hashlib.sha256(live.encode()).digest() != hashlib.sha256(ESCROW.encode()).digest():
        return fail(
            "暗号鍵の控えが本番と一致しません",
            f"Render sha256={sha8(live)}… / 控え sha256={sha8(ESCROW)}…。本番の鍵が変わったなら控えを更新（ops_bootstrap.py）、"
            "意図せず変わったなら復元前に保存済みデータの復号可否を確認してください。",
        )
    print(f"✅ key-check: 一致（sha256 {sha8(live)}…）")
    return 0


def job_key_restore(force: bool) -> int:
    if not RENDER_API_KEY or not ESCROW:
        return fail("鍵の復元ができません", "RENDER_API_KEY と APP_ENCRYPTION_KEY_ESCROW の両方が必要")
    st, degraded = _readyz_degraded()
    st_env, live = _render_env("APP_ENCRYPTION_KEY")
    print(f"readyz={st} degraded={degraded} render_env=HTTP {st_env} value={'set' if live else 'empty'}")
    if not force:
        if live:
            print("⏭️ Render に鍵が設定済みのため復元しません（上書きは --force）")
            return 0
        if "encryption_key" not in degraded:
            print("⏭️ /readyz は鍵未設定を報告していないため復元しません（--force で強制）")
            return 0
    st, body = render("PUT", f"/services/{RENDER_SERVICE_ID}/env-vars/APP_ENCRYPTION_KEY", body={"value": ESCROW})
    if st not in (200, 201):
        return fail("鍵の書き戻しに失敗", f"PUT env-vars/APP_ENCRYPTION_KEY → HTTP {st}: {str(body)[:200]}")
    st, body = render("POST", f"/services/{RENDER_SERVICE_ID}/deploys", body={"clearCache": "do_not_clear"})
    deploy_note = f"deploy → HTTP {st}" + (f" id={body.get('id')}" if isinstance(body, dict) else "")
    print(f"✅ key-restore: 書き戻し完了（sha256 {sha8(ESCROW)}…）/ {deploy_note}")
    notify("[カタヅケ運用] 暗号鍵を控えから復元しました", f"Render の APP_ENCRYPTION_KEY を GitHub Secrets の控えから書き戻しました（sha256 {sha8(ESCROW)}…）。{deploy_note}")
    return 0


# ──────────────────────────── main ────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", choices=["hourly", "daily", "key-check", "key-restore"])
    ap.add_argument("--force", action="store_true", help="key-restore: 条件を無視して控えで上書きする")
    args = ap.parse_args()
    if args.job == "hourly":
        return job_hourly()
    if args.job == "daily":
        return job_daily()
    if args.job == "key-check":
        return job_key_check()
    return job_key_restore(args.force)


if __name__ == "__main__":
    sys.exit(main())
