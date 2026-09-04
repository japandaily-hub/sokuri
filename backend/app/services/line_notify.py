"""LINE 通知 — LINE Messaging API（Push メッセージ）。

LINE_CHANNEL_ACCESS_TOKEN 未設定時は送信をスキップしてログのみ残す（開発・テスト安全側）。
送信失敗は呼び出し元の処理を失敗させない（通知はベストエフォート、notify.py と同じ設計思想）。
"""

from __future__ import annotations

import logging
import re
from typing import Literal

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

# 通知文へ差し込む外部入力（業者名など）から改行・タブ・全半角の連続空白を潰す。
# LINE のテキストメッセージは改行でそのまま行が増えるため、社名に改行を仕込まれると
# 「【カタヅケ】…」に続く偽の案内行（フィッシングURL等）を捏造できてしまう。
_INLINE_WHITESPACE_RE = re.compile("[\r\n\t　 ]+")

#: 差し込み値の最大長。LINE の1通あたり上限ではなく、可読性の確保と
#: 長大文字列による行崩し・本文押し出しの抑止が目的。
_INLINE_MAX_LENGTH = 40


def _sanitize_inline(value: str, *, max_length: int = _INLINE_MAX_LENGTH) -> str:
    """通知文へ差し込む外部入力を「改行なしの1行・長さ上限つき」へ正規化する。"""
    return _INLINE_WHITESPACE_RE.sub(" ", value).strip()[:max_length]


def _mask_line_user_id(line_user_id: str | None) -> str:
    """ログ出力用の LINE ユーザーID マスク（先頭4文字のみ残す）。

    line_user_id は個人を一意に識別する外部IDであり、Push の宛先そのもの。
    平文でログに残すと、ログ閲覧権限しか持たない者が宛先を収集できてしまう。
    """
    if not line_user_id:
        return "(none)"
    return f"{line_user_id[:4]}…"


async def _push(line_user_id: str, text: str) -> bool:
    settings = get_settings()
    if not settings.line_channel_access_token:
        logger.info(
            "line_notify: LINE_CHANNEL_ACCESS_TOKEN 未設定のため送信スキップ - %s",
            _mask_line_user_id(line_user_id),
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


async def push_bank_account_changed(line_user_id: str, action: str) -> bool:
    """振込先口座の登録・変更・削除の本人通知（口座番号等は含めない）。"""
    return await _push(
        line_user_id,
        f"【カタヅケ】お客様の振込先口座情報が{action}されました。"
        "お心当たりがない場合は、至急カタヅケまでご連絡ください。",
    )


async def push_bid_lost(line_user_id: str, case_id: str, prefecture: str, city: str, purpose: str) -> bool:
    """落札通知（落選業者宛）。案件を特定できるよう地域・利用目的とリンクを本文に含める（M7対応）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/cases/{case_id}"
    safe_prefecture = _sanitize_inline(prefecture)
    safe_city = _sanitize_inline(city)
    safe_purpose = _sanitize_inline(purpose)
    return await _push(
        line_user_id,
        f"【カタヅケ】ご入札いただいた案件（{safe_prefecture}{safe_city}／{safe_purpose}）は、"
        f"誠に恐れ入りますが今回は成約に至りませんでした。\n{url}",
    )


async def push_reduction_requested(line_user_id: str, case_id: str, amount: int) -> bool:
    """減額申請の受付通知（依頼者宛・ADD-2対応）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    return await _push(
        line_user_id,
        f"【カタヅケ】落札業者から {amount:,} 円への減額のご相談が届いています。\n{url}",
    )


async def push_reduction_decided(
    line_user_id: str, transaction_id: str, approved: bool, amount: int
) -> bool:
    """減額申請の承認／却下結果通知（申請業者宛・H2対応）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    if approved:
        text = f"【カタヅケ】ご相談いただいた減額（{amount:,} 円）が承認されました。\n{url}"
    else:
        text = f"【カタヅケ】ご相談いただいた減額は、依頼者により見送られました。\n{url}"
    return await _push(line_user_id, text)


async def push_transaction_cancelled(
    line_user_id: str, transaction_id: str, recipient_party: Literal["user", "operator"]
) -> bool:
    """成約キャンセル通知（相手方宛・ADD-1対応）。"""
    settings = get_settings()
    path = (
        f"/chat/{transaction_id}"
        if recipient_party == "user"
        else f"/operator/transactions/{transaction_id}"
    )
    return await _push(
        line_user_id,
        f"【カタヅケ】進行中だった成約が、相手方によりキャンセルされました。\n{settings.frontend_base_url}{path}",
    )


async def push_schedule_confirmed(line_user_id: str, transaction_id: str, visit_date: str) -> bool:
    """訪問日程が確定した際の通知（業者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/operator/transactions/{transaction_id}"
    return await _push(
        line_user_id,
        f"【カタヅケ】訪問日程が {visit_date} に確定しました。\n{url}",
    )


async def push_bid_received(
    line_user_id: str, case_id: str, company_name: str, amount: int
) -> bool:
    """新規入札通知（依頼者宛）。"""
    settings = get_settings()
    url = f"{settings.frontend_base_url}/cases/{case_id}"
    # 業者名は業者自身が入力する値＝通知文への信頼できない差し込み。改行を含めると
    # 独立した行として描画され、ブランドを騙る案内行やURLを捏造できるため、
    # Push 直前に1行へ正規化する（security review Medium指摘対応）。
    safe_company_name = _sanitize_inline(company_name)
    return await _push(
        line_user_id,
        f"【カタヅケ】新しい入札が届きました。\n{safe_company_name}：{amount:,} 円\n{url}",
    )


async def push_message_received(
    line_user_id: str, transaction_id: str, recipient_party: Literal["user", "operator"]
) -> bool:
    """新着チャットメッセージ通知（当事者宛）。

    メッセージ本文は含めない。チャットは住所・連絡先等の機微情報を含みうるため、
    第三者チャネル（LINE）へ本文を流さず「新着がある」事実と遷移先URLのみを通知する。
    """
    settings = get_settings()
    path = (
        f"/chat/{transaction_id}"
        if recipient_party == "user"
        else f"/operator/chat/{transaction_id}"
    )
    return await _push(
        line_user_id,
        f"【カタヅケ】新しいメッセージが届きました。\n{settings.frontend_base_url}{path}",
    )
