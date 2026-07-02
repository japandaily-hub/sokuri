"""通知振り分け層 — LINE 連携済みなら LINE Push、未連携/送信失敗ならメールにフォールバックする。

BackgroundTasks はレスポンス送出後（= DBコミット後、セッションクローズ後）に実行される。
ORM オブジェクトをそのまま渡すと detached セッションアクセスで例外化するリスクがあるため、
呼び出し元でプリミティブ値（str | None, str, ...）へ変換してから渡す設計とする。
"""

from __future__ import annotations

import logging

from app.services import line_notify, notify

logger = logging.getLogger(__name__)


async def dispatch_bid_selected(
    line_user_id: str | None, email: str, transaction_id: str, amount: int
) -> None:
    """③ 落札通知（業者宛）。LINE優先・失敗/未連携時はメールにフォールバック。"""
    if line_user_id:
        ok = await line_notify.push_bid_selected(line_user_id, transaction_id, amount)
        if ok:
            return
    if notify.is_placeholder_email(email):
        return
    await notify.send_bid_selected(email, transaction_id, amount)


async def dispatch_bid_lost(line_user_id: str | None, email: str, case_id: str) -> None:
    """落札通知（落選業者宛）。LINE優先・失敗/未連携時はメールにフォールバック。"""
    if line_user_id:
        ok = await line_notify.push_bid_lost(line_user_id, case_id)
        if ok:
            return
    if notify.is_placeholder_email(email):
        return
    await notify.send_bid_lost(email, case_id)


async def dispatch_schedule_confirmed(
    line_user_id: str | None, email: str, transaction_id: str, visit_date: str
) -> None:
    """訪問日程確定通知（業者宛）。LINE優先・失敗/未連携時はメールにフォールバック。"""
    if line_user_id:
        ok = await line_notify.push_schedule_confirmed(line_user_id, transaction_id, visit_date)
        if ok:
            return
    if notify.is_placeholder_email(email):
        return
    await notify.send_schedule_confirmed(email, transaction_id, visit_date)
