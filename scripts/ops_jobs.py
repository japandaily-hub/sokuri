#!/usr/bin/env python3
"""カタヅケ自動運用ジョブ（GitHub Actions「Ops cron」から実行。標準ライブラリのみ）。

残っていた運営の手作業を機械実行に置き換える（r13・自動運用）:

    hourly      Render を起こしてリマインド処理（訪問日超過 / 入札ゼロ放置）を1周回す。
                Render Free は無通信でスピンダウンし、プロセス内の毎時ループごと止まるため
                外から叩く。
    daily       ① ADMIN_EMAILS の棚卸し（未登録・非admin・停止中があれば通知）
                ①-2 運営アラートの宛先（ALERT_EMAILS）に管理者が入っているかの照合
                ② 運営自身のプローブ問い合わせを対応済みへ
                ③ メール到達プローブ: 送信 → Brevo のイベント API で delivered まで追跡
                ④ Brevo の前日集計でバウンス・ブロック・エラーがあれば通知
    key-check   本番の APP_ENCRYPTION_KEY と GitHub Secrets の控え（ESCROW）が一致しているかを
                SHA-256 で照合（backend の /admin/jobs/key-fingerprint を使う＝Render API キー不要。
                値は出力しない）。
    key-restore /readyz が「暗号鍵未設定」で、かつ Render 側の値が空のときだけ、控えから
                Render へ書き戻して再デプロイする。--force（ローカル実行専用。ワークフローからは
                渡さない）で条件を無視して上書きできるが、設定済みの鍵を別の値で上書きすると
                保存済みデータが復号不能になるため通常は使わない。

失敗は運営へ通知（LINE / メール / Webhook・scripts/uptime_check.py の notify）し exit 1。
値そのものを標準出力に出さない（トークン・鍵・メールアドレスの列挙を避ける）。

環境変数:
  BACKEND_URL                 既定 https://sokuri-backend.onrender.com
  OPS_JOB_TOKEN               backend の OPS_JOB_TOKEN と同じ値（X-Ops-Token）
  BREVO_API_KEY               Brevo（イベント照会・通知メール）
  RENDER_API_KEY / RENDER_SERVICE_ID   key-restore のみ（既定 service は sokuri-backend）
  APP_ENCRYPTION_KEY_ESCROW   GitHub Secrets に置いた暗号鍵の控え（key-check / key-restore）
  GITHUB_TOKEN / GITHUB_REPOSITORY     daily の「毎時ジョブが実際に回っているか」の照合（Actions が自動付与）
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
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "japandaily-hub/sokuri")
#: daily が「Ops cron のスケジュール実行が直近24時間に何回成功したか」を照合する下限。
#: 設計上は毎時（24 回）だが、GitHub の schedule はこのリポジトリでは 2〜6 時間間隔でしか起動しない
#: （2026-09-04〜09-07 実測: 1 日 4〜6 回。uptime-alert の */5 も同じ）。20 のままだと毎日「止まっている」と
#: 誤報するため、ここは「完全に止まった」を検知する下限（3）にする（INC-2026-09-08-2）。実際の回数は
#: 毎回ログに出す。毎時の厳密な実行が必要なら外部スケジューラ（cron-job.org / UptimeRobot 等）から
#: workflow_dispatch を叩く（運営判断・docs/ops/incidents.md 未収束の教訓）。
HOURLY_SUCCESS_MIN_PER_DAY = int(os.environ.get("OPS_CRON_MIN_SUCCESS_PER_DAY", "3"))

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


#: 直近の配送失敗理由（Brevo の reason）。通知本文で原因を直接示すために保持する（INC-2026-09-08-1）。
_last_probe_failure_reasons: list[str] = []


def _poll_brevo_delivery(message_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    """messageId ごとに delivered / 失敗 / 未確定 を分ける（最大5分）。失敗理由は _last_probe_failure_reasons へ。"""
    pending = list(message_ids)
    delivered: list[str] = []
    failed: list[str] = []
    _last_probe_failure_reasons.clear()
    deadline = time.time() + _BREVO_POLL_SECONDS
    while pending and time.time() < deadline:
        for mid in list(pending):
            st, body = brevo("GET", f"/smtp/statistics/events?days=2&limit=50&messageId={urllib.parse.quote(mid, safe='')}")
            raw_events = (body or {}).get("events", []) if st == 200 and isinstance(body, dict) else []
            events = {e.get("event") for e in raw_events}
            if "delivered" in events:
                delivered.append(mid)
                pending.remove(mid)
            elif events & _BREVO_FAILURE_EVENTS:
                failed.append(mid)
                pending.remove(mid)
                for e in raw_events:
                    reason = str(e.get("reason") or "").strip()
                    if e.get("event") in _BREVO_FAILURE_EVENTS and reason and reason not in _last_probe_failure_reasons:
                        _last_probe_failure_reasons.append(reason[:200])
        if pending:
            time.sleep(_BREVO_POLL_INTERVAL)
    return delivered, failed, pending


def check_alert_recipients(admin_emails: set[str], alert_emails: str) -> list[str]:
    """運営アラートの宛先に管理者が入っているかを照合する（INC-2026-09-11-3）。

    GitHub の「Run failed」は管理者の受信箱へ届くのに、こちらの [CRITICAL]/[RECOVERED] は
    ALERT_EMAILS にしか届かない。両者がズレていると「失敗だけ来て復旧が来ない」＝運営には
    未解決に見える（2026-09-04〜09-11 に実発生）。アドレスそのものは通知文に出さない。
    """
    if not admin_emails:
        return []
    to = {a.strip().lower() for a in (alert_emails or "").split(",") if a.strip()}
    if not to:
        return ["運営アラートの宛先（ALERT_EMAILS）が未設定です。障害・復旧の通知がメールで届きません。"]
    missing = {e for e in admin_emails if e and e.lower() not in to}
    if missing:
        return [
            f"運営アラートの宛先に管理者 {len(missing)} 件が含まれていません。"
            "失敗通知（GitHub）は届くのに復旧通知が別の受信箱にしか届かず、未解決に見えます。"
            "GitHub Secrets の ALERT_EMAILS に管理者アドレスを追加してください。"
        ]
    return []


def _check_hourly_runs() -> list[str]:
    """直近24時間の schedule 起動のうち成功が下限未満／失敗ありなら要対応として返す。

    Actions 自体が止まった（ワークフロー無効化・失敗・キュー詰まり）ケースは、ジョブ内の
    通知では検知できない。GitHub API で実行履歴を数えて「欠測」を可視化する。
    """
    if not GITHUB_TOKEN:
        return ["GITHUB_TOKEN が無いため毎時ジョブの実行履歴を照合できません"]
    since = time.time() - 24 * 3600
    st, body = http(
        "GET",
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/workflows/ops-cron.yml/runs?event=schedule&per_page=60",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"},
    )
    if st != 200 or not isinstance(body, dict):
        return [f"毎時ジョブの実行履歴を取得できません（GitHub API HTTP {st}）"]
    success = failed = 0
    total_schedule_runs = 0
    for run in body.get("workflow_runs", []):
        total_schedule_runs += 1
        created = run.get("created_at", "")
        try:
            ts = time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except ValueError:
            continue
        if ts < since or run.get("status") != "completed":
            continue
        if run.get("conclusion") == "success":
            success += 1
        else:
            failed += 1
    print(
        f"{'✅' if failed == 0 and success >= HOURLY_SUCCESS_MIN_PER_DAY else '⚠️'} ops-cron(24h): "
        f"success={success} failed={failed} history={total_schedule_runs}（設計 24 回/日・GitHub の遅延で実測 4〜6 回/日）"
    )
    out: list[str] = []
    # 失敗回数は**要対応に積まない**（INC-2026-09-11-1）。個々の失敗はその場で fail() と
    # ワークフローの notify-failure・GitHub の失敗メールが通知済みで、翌日の再掲は重複。
    # それ以上に、ここへ積むと「前日に失敗があった」こと自体で daily が失敗し、その失敗を
    # 翌日がまた検知する自己増殖ループになり、人が介入しない限り永久に復旧しない
    # （2026-09-08〜09-10 に実発生。9/8 の真因 = Brevo 差出人拒否は 9/8 に解消済みだったのに、
    #   3 晩連続で「Run failed: Ops cron」が届き続けた）。回数はログにだけ残す。
    if total_schedule_runs < HOURLY_SUCCESS_MIN_PER_DAY:
        # 導入初日（スケジュール実行の履歴がまだ 24 回に満たない）は回数判定を保留する。
        print(f"⏭️ スケジュール実行の履歴が {total_schedule_runs} 回のため回数判定は保留（翌日から有効）")
    elif success < HOURLY_SUCCESS_MIN_PER_DAY:
        out.append(
            f"直近24時間の Ops cron 成功が {success} 回（下限 {HOURLY_SUCCESS_MIN_PER_DAY}）。"
            "スケジュールが止まっている可能性（ワークフローの無効化・リポジトリの休眠・GitHub 側の遅延）。"
            "Actions → Ops cron を手動実行して復帰するか確認。"
        )
    return out


def job_daily() -> int:
    problems: list[str] = []
    if not wake_backend():
        return fail("backend が起きません（/health 非200が90秒継続）", f"{BACKEND_URL}/health")

    # ① ADMIN_EMAILS の棚卸し
    st, body = post_job("admin-audit")
    if st != 200:
        problems.append(f"admin-audit → HTTP {st}: {str(body)[:200]}")
    else:
        entries = body.get("entries", [])
        ng = [e for e in entries if not e.get("ok")]
        print(f"{'✅' if body.get('ok') else '❌'} admin-audit: entries={len(entries)} ng={len(ng)} active_admins={body.get('active_admin_count')}")
        # ADMIN_EMAILS は運営自身のアドレス（render.yaml にも記載）なので、どの項目が不合格かを
        # ログと通知に出す。顧客の個人情報は含まれない。
        for e in entries:
            state = "未登録" if not e.get("registered") else ("停止中" if e.get("suspended") else f"role={e.get('role')}")
            print(f"   {'✅' if e.get('ok') else '❌'} {e.get('email')}: {state}")
        # ①-2 アラート宛先の照合（失敗と復旧が同じ受信箱に届くこと）
        problems.extend(
            check_alert_recipients(
                {str(e.get("email", "")) for e in entries}, os.environ.get("ALERT_EMAILS", "")
            )
        )
        if not body.get("ok"):
            detail = "、".join(
                f"{e.get('email')}（{'未登録' if not e.get('registered') else ('停止中' if e.get('suspended') else 'role=' + str(e.get('role')))}）"
                for e in ng
            ) or "ADMIN_EMAILS が空"
            problems.append(
                f"ADMIN_EMAILS の棚卸しで不整合: {detail}（有効な管理者 {body.get('active_admin_count')} 人）。"
                "未登録は ADMIN_EMAILS から外すか、本人が登録後に管理画面で『管理者にする』。"
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
    elif body.get("throttled"):
        print("⏭️ mail-probe: 直近20時間以内に送信済みのため今回は送信せず（追跡もスキップ）")
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
                + (" Brevo の理由: " + " / ".join(_last_probe_failure_reasons) if _last_probe_failure_reasons else "")
                + (
                    "（『sender ... is not valid』なら Render の MAIL_FROM を Brevo の認証済み送信者にする"
                    "＝python scripts/render_env.py set MAIL_FROM <認証済みアドレス>）"
                    if any("not valid" in r for r in _last_probe_failure_reasons)
                    else ""
                )
            )

    # ⑤ 毎時ジョブが本当に回っているか（「実行されなかった」を検知する唯一の経路）
    problems.extend(_check_hourly_runs())

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
    """本番の鍵ダイジェスト（backend が返す）と控えのダイジェストを照合する。Render API は使わない。"""
    if not ESCROW:
        return fail("暗号鍵の控えがありません", "GitHub Secrets の APP_ENCRYPTION_KEY_ESCROW が未設定。scripts/ops_bootstrap.py を実行して登録してください。")
    if not wake_backend():
        return fail("backend が起きません（/health 非200が90秒継続）", f"{BACKEND_URL}/health")
    st, body = post_job("key-fingerprint")
    if st != 200 or not isinstance(body, dict):
        return fail("本番の鍵ダイジェストを取得できません", f"POST /admin/jobs/key-fingerprint → HTTP {st}")
    if not body.get("configured"):
        return fail("本番の暗号鍵が空です", "APP_ENCRYPTION_KEY が未設定。Actions「Ops cron」を job=key-restore で実行すると控えから復元します。")
    if body.get("sha256") != hashlib.sha256(ESCROW.encode("utf-8")).hexdigest():
        return fail(
            "暗号鍵の控えが本番と一致しません",
            "本番の APP_ENCRYPTION_KEY と GitHub Secrets の控えが別の値です。本番の鍵を意図して変えたなら"
            " scripts/ops_bootstrap.py で控えを更新、意図せず変わったなら復元前に保存済みデータの復号可否を確認してください。",
        )
    print("✅ key-check: 本番と控えは一致")
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
    st, _body = render("PUT", f"/services/{RENDER_SERVICE_ID}/env-vars/APP_ENCRYPTION_KEY", body={"value": ESCROW})
    if st not in (200, 201):
        # 応答本文は出さない（Render がエラー時に送信値をエコーする可能性を排除）
        return fail("鍵の書き戻しに失敗", f"PUT env-vars/APP_ENCRYPTION_KEY → HTTP {st}")
    st, body = render("POST", f"/services/{RENDER_SERVICE_ID}/deploys", body={"clearCache": "do_not_clear"})
    deploy_note = f"deploy → HTTP {st}" + (f" id={body.get('id')}" if isinstance(body, dict) else "")
    print(f"✅ key-restore: 書き戻し完了 / {deploy_note}")
    notify("[カタヅケ運用] 暗号鍵を控えから復元しました", f"Render の APP_ENCRYPTION_KEY を GitHub Secrets の控えから書き戻しました。{deploy_note}")
    return 0


# ──────────────────────────── main ────────────────────────────


STATE_FILE = os.environ.get("OPS_STATE_FILE", ".ops_state.json")


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 -- 初回・キャッシュ未復元は「前回正常」とみなす
        return {"failed": False, "since": None}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print(f"state save failed: {type(e).__name__}: {e}", file=sys.stderr)


def _track_recovery(job: str, code: int) -> None:
    """前回失敗→今回成功なら復旧通知を送る（状態は Actions のキャッシュで持ち回す）。

    失敗のたびの通知は fail() が出す。ここでは「失敗が続いていたものが直った」を1回だけ知らせる。
    """
    state = _load_state()
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    if code != 0:
        if not state.get("failed"):
            state = {"failed": True, "since": now}
        _save_state(state)
        return
    if state.get("failed"):
        sent = notify(
            f"[カタヅケ運用][RECOVERED] {job} が正常に戻りました",
            f"✅ Ops cron（{job}）が正常に戻りました。\n失敗開始: {state.get('since')} → 復旧確認: {now}",
        )
        print(f"✅ recovered: notified={sent or 'none'}")
    _save_state({"failed": False, "since": None})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", choices=["hourly", "daily", "key-check", "key-restore"])
    ap.add_argument("--force", action="store_true", help="key-restore: 条件を無視して控えで上書きする")
    args = ap.parse_args()
    if args.job in ("hourly", "daily", "key-check") and not OPS_JOB_TOKEN:
        # 初期設定（scripts/ops_bootstrap.py）前はスケジュールが毎時失敗通知を出し続けるだけなので、
        # 未設定は「スキップ」として静かに終える（設定後の欠測は daily ⑤ が検知する）。
        print("⏭️ OPS_JOB_TOKEN が未設定のためスキップ（scripts/ops_bootstrap.py で初期設定してください）")
        return 0
    if args.job == "key-restore":
        return job_key_restore(args.force)
    runner = {"hourly": job_hourly, "daily": job_daily, "key-check": job_key_check}[args.job]
    code = runner()
    _track_recovery(args.job, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
