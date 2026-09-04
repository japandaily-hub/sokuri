"""運営向けアラート通知（障害・異常時に運営へ知らせる）。

顧客向け通知（notify.py / line_notify.py）とは**アカウント・宛先を分離**する:
- メール: Brevo は共用でよいが、差出人名を「カタヅケ監視」にし、宛先は ALERT_EMAILS（運営の監視用）。
- LINE: 顧客向け公式アカウントとは別チャネルのトークン ALERT_LINE_CHANNEL_ACCESS_TOKEN と
  運営の LINE ユーザーID ALERT_LINE_USER_IDS を使う（顧客向け配信枠・友だち一覧に混ぜない）。
- Webhook: ALERT_WEBHOOK_URL（Slack / Discord 互換。{"text": ..., "content": ...} の両方を送る）。

いずれも未設定なら送信をスキップしてログのみ残す（開発・テスト安全側）。送信失敗でも例外を投げない。
同じ key のアラートは ALERT_COOLDOWN_SECONDS の間は再送しない（プロセス内メモリ。多重起動時は
プロセスごとに抑制される＝最大でプロセス数ぶん届く。誤検知より取りこぼしを避ける設計）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

Severity = Literal["critical", "warning"]

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
_LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
_ALERT_TEXT_MAX = 1800  # LINE の 1 メッセージ上限(5000)より十分小さく、可読性を優先


@dataclass
class _State:
    last_sent_at: dict[str, float] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_state = _State()

#: fire_and_forget が生成した Task の強参照。``asyncio.create_task`` の戻り値を
#: 保持しないと、イベントループは Task を弱参照でしか持たないため GC に回収されて
#: アラートが送られないまま静かに消えることがある（CPython の既知の落とし穴）。
#: 完了時に done コールバックで自身を取り除く（集合が無限に増えない）。
_inflight_tasks: set[asyncio.Task] = set()


def _truncate(text: str, limit: int = _ALERT_TEXT_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def reset_state_for_tests() -> None:
    """テスト専用: クールダウン状態を初期化する。"""
    _state.last_sent_at.clear()


def _format_text(title: str, body: str, severity: Severity) -> str:
    tag = "🚨【Critical】" if severity == "critical" else "⚠️【Warning】"
    settings = get_settings()
    env = settings.app_env
    commit = settings.render_git_commit[:7] if settings.render_git_commit else "-"
    return _truncate(f"{tag} カタヅケ監視\n{title}\n\n{body}\n\n環境: {env} / commit: {commit}")


async def _send_email(subject: str, text: str) -> bool:
    settings = get_settings()
    recipients = settings.alert_emails
    if not settings.brevo_api_key or not recipients:
        logger.info("alerts: メール送信スキップ（BREVO_API_KEY または ALERT_EMAILS 未設定） - %s", subject)
        return False
    html = (
        '<div style="font-family:sans-serif;max-width:640px;margin:0 auto;padding:24px;">'
        '<h2 style="color:#b91c1c;margin:0 0 12px;">カタヅケ監視アラート</h2>'
        f'<pre style="white-space:pre-wrap;font-family:inherit;line-height:1.7;">{_escape(text)}</pre>'
        "</div>"
    )
    payload = {
        "sender": {"email": settings.alert_mail_from or settings.mail_from, "name": "カタヅケ監視"},
        "to": [{"email": e} for e in recipients],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(_BREVO_ENDPOINT, json=payload, headers={"api-key": settings.brevo_api_key})
            res.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 -- 通知失敗で本処理を止めない
        logger.error("alerts: メール送信失敗（処理は継続） - %s", exc)
        return False


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _send_line(text: str) -> bool:
    settings = get_settings()
    token = settings.alert_line_channel_access_token
    user_ids = settings.alert_line_user_ids
    if not token or not user_ids:
        logger.info("alerts: LINE送信スキップ（ALERT_LINE_CHANNEL_ACCESS_TOKEN または ALERT_LINE_USER_IDS 未設定）")
        return False
    ok = True
    async with httpx.AsyncClient(timeout=10.0) as client:
        for uid in user_ids:
            try:
                res = await client.post(
                    _LINE_PUSH_ENDPOINT,
                    json={"to": uid, "messages": [{"type": "text", "text": text}]},
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                res.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                ok = False
                logger.error("alerts: LINE送信失敗（処理は継続） - %s", exc)
    return ok


async def _send_webhook(text: str) -> bool:
    settings = get_settings()
    url = settings.alert_webhook_url
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Slack Incoming Webhook は "text"、Discord Webhook は "content" を読む。両方入れて互換にする。
            res = await client.post(url, json={"text": text, "content": text})
            res.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("alerts: Webhook送信失敗（処理は継続） - %s", exc)
        return False


async def send_alert(
    title: str,
    body: str,
    *,
    severity: Severity = "critical",
    key: str | None = None,
) -> bool:
    """運営へアラートを送る。key が同じものはクールダウン中は再送しない。

    戻り値はいずれかのチャネルで送信できたか。未設定・失敗でも例外は投げない。
    """
    settings = get_settings()
    dedupe_key = key or title
    now = time.monotonic()
    async with _state.lock:
        last = _state.last_sent_at.get(dedupe_key)
        if last is not None and now - last < settings.alert_cooldown_seconds:
            logger.info("alerts: クールダウン中のため抑制 - key=%s", dedupe_key)
            return False
        _state.last_sent_at[dedupe_key] = now

    text = _format_text(title, body, severity)
    subject = f"[カタヅケ監視][{severity.upper()}] {title}"
    logger.warning("alerts: %s", text.replace("\n", " | "))
    # 3チャネルは**同時**に走らせる（直列にしない）。アラートの主因の1つが
    # 「Brevo が枠切れ・キー失効でメールを送れない」ことであり（r6 H-3）、
    # メールの成否や遅延に LINE / Webhook を巻き込ませないため。gather の引数順は
    # 「Brevo 非依存の経路を先に置く」という意図の明示（実行は並行）。
    results = await asyncio.gather(
        _send_line(text),
        _send_webhook(text),
        _send_email(subject, text),
        return_exceptions=True,
    )
    return any(r is True for r in results)


def fire_and_forget(coro) -> None:  # noqa: ANN001 -- asyncio コルーチン
    """リクエスト処理を待たせずにアラートを送る（イベントループ上でスケジュール）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("alerts: 実行中のイベントループが無いためアラートを送れません")
        coro.close()
        return
    task = loop.create_task(coro)
    # 強参照を保持してから done コールバックを付ける（GC 回収による送信取りこぼし防止）。
    _inflight_tasks.add(task)
    task.add_done_callback(_inflight_tasks.discard)
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
