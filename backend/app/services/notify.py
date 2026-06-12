"""メール通知 — Brevo (Sendinblue) transactional email API。

BREVO_API_KEY 未設定時は送信をスキップしてログのみ残す（開発・テスト安全側）。
送信失敗は呼び出し元の処理を失敗させない（通知はベストエフォート）。
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


async def _send(to_email: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.brevo_api_key:
        logger.info("notify: BREVO_API_KEY 未設定のため送信スキップ - %s / %s", to_email, subject)
        return False
    payload = {
        "sender": {"email": settings.mail_from, "name": settings.mail_from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                _BREVO_ENDPOINT,
                json=payload,
                headers={"api-key": settings.brevo_api_key},
            )
            res.raise_for_status()
        return True
    except Exception as exc:
        logger.error("notify: メール送信失敗（処理は継続） - %s", exc)
        return False


def _wrap(body: str) -> str:
    return (
        '<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px;">'
        '<h2 style="color:#14B8A6;margin:0 0 16px;">カタヅケ</h2>'
        f"{body}"
        '<p style="color:#888;font-size:12px;margin-top:24px;">'
        "このメールはカタヅケから自動送信されています。</p></div>"
    )


async def send_case_created(to_email: str, case_id: str) -> bool:
    """① 案件化完了（ユーザー宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】案件の登録が完了しました",
        _wrap(
            "<p>お片付け案件の登録が完了しました。</p>"
            "<p>業者からの入札が届き次第、メールでお知らせします。</p>"
            f'<p><a href="{url}">案件の状況を確認する</a></p>'
        ),
    )


async def send_bid_received(to_email: str, case_id: str, company_name: str, amount: int) -> bool:
    """② 入札通知（ユーザー宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _send(
        to_email,
        "【カタヅケ】新しい入札が届きました",
        _wrap(
            f"<p><strong>{company_name}</strong> から "
            f"<strong>{amount:,} 円</strong> の入札が届きました。</p>"
            f'<p><a href="{url}">入札一覧を確認して業者を選ぶ</a></p>'
        ),
    )


async def send_bid_selected(to_email: str, transaction_id: str, amount: int) -> bool:
    """③ 落札通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】入札が落札されました",
        _wrap(
            f"<p>あなたの入札（<strong>{amount:,} 円</strong>）が選ばれました。</p>"
            "<p>住所詳細が開示されています。訪問日の調整を進めてください。</p>"
            f'<p><a href="{url}">落札案件の詳細を確認する</a></p>'
        ),
    )
