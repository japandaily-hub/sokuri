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
# LINE専用ユーザー（実メール未設定）に払い出す仮メールのドメインサフィックス。
# auth.py の line_exchange で `line-{line_user_id}@line.katazuke.internal` として発行される。
_PLACEHOLDER_EMAIL_SUFFIX = "@line.katazuke.internal"


def is_placeholder_email(email: str | None) -> bool:
    """LINE専用ユーザー向けの仮メール（実メール未設定）かどうかを判定する。

    仮メールは実際には受信されないため、そのまま送信経路（通知メール送信・
    業者への contact_email 開示等）に流すと配送不能や情報として無意味な
    開示になる。呼び出し元でこの判定を経由してスキップ/文言差し替えを行うこと。
    """
    if not email:
        return False
    return email.lower().endswith(_PLACEHOLDER_EMAIL_SUFFIX)


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


async def send_bid_lost(to_email: str, case_id: str) -> bool:
    """落札通知（落選業者宛）。"""
    return await _send(
        to_email,
        "【カタヅケ】ご入札いただいた案件について",
        _wrap(
            "<p>ご入札いただいた案件は、誠に恐れ入りますが今回は成約に至りませんでした。</p>"
            "<p>またの機会がございましたらよろしくお願いいたします。</p>"
        ),
    )


async def send_schedule_confirmed(to_email: str, transaction_id: str, visit_date: str) -> bool:
    """訪問日程が確定した際の通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _send(
        to_email,
        "【カタヅケ】訪問日程が確定しました",
        _wrap(
            f"<p>訪問日程が <strong>{visit_date}</strong> に確定しました。</p>"
            f'<p><a href="{url}">成約詳細を確認する</a></p>'
        ),
    )


async def send_operator_application_received(to_email: str, company_name: str) -> bool:
    """④ 業者事前申込の受付確認（申込者宛）。"""
    return await _send(
        to_email,
        "【カタヅケ】業者登録のお申込みを受け付けました",
        _wrap(
            f"<p><strong>{company_name}</strong> 様</p>"
            "<p>業者登録のお申込みを受け付けました。審査完了まで今しばらくお待ちください。</p>"
        ),
    )


async def send_operator_application_admin_alert(to_email: str, company_name: str) -> bool:
    """④ 業者事前申込の新規受付通知（admin宛）。"""
    return await _send(
        to_email,
        "【カタヅケ管理】新規業者申込が届きました",
        _wrap(f"<p>新規業者申込（<strong>{company_name}</strong>）が届きました。管理画面から確認してください。</p>"),
    )


async def send_operator_application_approved(to_email: str, company_name: str, invite_code: str) -> bool:
    """⑤ 業者事前申込の承認通知（申込者宛・招待コード案内）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/signup"
    return await _send(
        to_email,
        "【カタヅケ】業者登録が承認されました",
        _wrap(
            f"<p><strong>{company_name}</strong> 様</p>"
            "<p>業者登録の審査が完了し、承認されました。以下の招待コードで本登録を完了してください。</p>"
            f'<p style="font-size:20px;font-weight:bold;letter-spacing:1px;">{invite_code}</p>'
            f'<p><a href="{url}">本登録ページへ進む</a></p>'
        ),
    )


async def send_operator_application_rejected(to_email: str, company_name: str, reason: str) -> bool:
    """⑥ 業者事前申込の却下通知（申込者宛）。"""
    return await _send(
        to_email,
        "【カタヅケ】業者登録のお申込みについて",
        _wrap(
            f"<p><strong>{company_name}</strong> 様</p>"
            "<p>誠に恐れ入りますが、今回のお申込みは承認を見送らせていただきました。</p>"
            f"<p>理由: {reason}</p>"
        ),
    )
