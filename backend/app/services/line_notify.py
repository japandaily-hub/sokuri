"""LINE 通知 — LINE Messaging API（Push メッセージ）。

LINE_CHANNEL_ACCESS_TOKEN 未設定時は送信をスキップしてログのみ残す（開発・テスト安全側）。
送信失敗は呼び出し元の処理を失敗させない（通知はベストエフォート、notify.py と同じ設計思想）。
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"


async def _push(line_user_id: str, text: str) -> bool:
    settings = get_settings()
    if not settings.line_channel_access_token:
        logger.info(
            "line_notify: LINE_CHANNEL_ACCESS_TOKEN 未設定のため送信スキップ - %s", line_user_id
        )
        return False
    payload = {
        "to": line_user_id,
        "messages": [{"type": "text", "text": text}],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                _LINE_PUSH_ENDPOINT,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.line_channel_access_token}",
                    "Content-Type": "application/json",
                },
            )
            res.raise_for_status()
        return True
    except Exception as exc:
        logger.error("line_notify: LINE Push送信失敗（処理は継続） - %s", exc)
        return False


async def push_bid_selected(line_user_id: str, transaction_id: str, amount: int) -> bool:
    """③ 落札通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _push(
        line_user_id,
        f"【カタヅケ】あなたの入札（{amount:,} 円）が選ばれました。\n"
        f"住所詳細が開示されています。訪問日の調整を進めてください。\n{url}",
    )


async def push_bid_lost(line_user_id: str, case_id: str) -> bool:
    """落札通知（落選業者宛）。"""
    return await _push(
        line_user_id,
        "【カタヅケ】ご入札いただいた案件は、誠に恐れ入りますが今回は成約に至りませんでした。"
        "またの機会がございましたらよろしくお願いいたします。",
    )


async def push_schedule_confirmed(line_user_id: str, transaction_id: str, visit_date: str) -> bool:
    """訪問日程が確定した際の通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _push(
        line_user_id,
        f"【カタヅケ】訪問日程が {visit_date} に確定しました。\n{url}",
    )
