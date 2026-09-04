"""通知振り分け層 — LINE 連携済みなら LINE Push、未連携/送信失敗ならメールにフォールバックする。

BackgroundTasks はレスポンス送出後（= DBコミット後、セッションクローズ後）に実行される。
ORM オブジェクトをそのまま渡すと detached セッションアクセスで例外化するリスクがあるため、
呼び出し元でプリミティブ値（str | None, str, ...）へ変換してから渡す設計とする。
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Awaitable, Callable, Literal, ParamSpec

from app.services import line_notify, notify

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")

#: 単体テストから差し替えられるよう、モジュール属性として束縛した単調増加クロック。
#: 壁時計（time.time）はNTP補正・DST で巻き戻りうるため、経過時間の判定には使わない。
_monotonic = time.monotonic

#: 同一 (transaction_id, recipient_party) への新着メッセージ Push の最小間隔（秒）。
_MESSAGE_PUSH_DEBOUNCE_SECONDS = 300.0

#: デバウンス台帳。キー = (transaction_id, recipient_party)、値 = 最終送信時刻（monotonic）。
_MESSAGE_PUSH_LAST_SENT: dict[tuple[str, str], float] = {}

#: 台帳の掃除を走らせるサイズ閾値。毎回 O(n) 走査すると成約数に比例して重くなるため、
#: 一定サイズを超えたときだけ期限切れエントリをまとめて捨てる（償却 O(1)）。
_MESSAGE_PUSH_SWEEP_THRESHOLD = 512


def _sweep_message_push_ledger(now: float) -> None:
    """デバウンス台帳から期限切れ（= 再送可能）エントリを取り除く。"""
    expired = [
        key
        for key, last_sent in _MESSAGE_PUSH_LAST_SENT.items()
        if now - last_sent >= _MESSAGE_PUSH_DEBOUNCE_SECONDS
    ]
    for key in expired:
        _MESSAGE_PUSH_LAST_SENT.pop(key, None)


def _best_effort(
    func: Callable[_P, Awaitable[None]],
) -> Callable[_P, Awaitable[None]]:
    """通知起因の例外を BackgroundTask の外へ出さないためのラッパ。

    BackgroundTasks 内で送出された例外は ASGI サーバのタスクグループまで伝播し、
    レスポンス送出後の 500 化やワーカーのエラーログ汚染を招く。通知はベストエフォート
    であり業務処理の成否とは独立なので、ここで捕捉して構造化ログに残すだけに留める。
    """

    @functools.wraps(func)
    async def _wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        try:
            await func(*args, **kwargs)
        except Exception:
            # 宛先そのもの（line_user_id / email）は本文へ出さない。引数位置は
            # 各 dispatch_* で第1引数=line_user_id に統一済みのため、関数名のみで
            # 十分に切り分け可能。
            logger.exception("notify_dispatch: 通知処理で例外（処理は継続） - %s", func.__name__)

    return _wrapper


@_best_effort
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


@_best_effort
async def dispatch_bank_account_changed(
    line_user_id: str | None, email: str, action: str
) -> None:
    """振込先口座の登録・変更・削除の本人通知（security review M-1 / 再レビュー A）。

    不正な書き換えの早期検知が目的のため、他の通知と異なりフォールバックではなく
    **LINE Push とメールの両方** に送る（LINE 専用ユーザーは仮メールのためメール側は
    自動的にスキップされ、LINE Push が唯一の通知経路になる）。
    """
    if line_user_id:
        await line_notify.push_bank_account_changed(line_user_id, action)
    if not notify.is_placeholder_email(email):
        await notify.send_bank_account_changed(email, action)


@_best_effort
async def dispatch_bid_lost(line_user_id: str | None, email: str, case_id: str) -> None:
    """落札通知（落選業者宛）。LINE優先・失敗/未連携時はメールにフォールバック。"""
    if line_user_id:
        ok = await line_notify.push_bid_lost(line_user_id, case_id)
        if ok:
            return
    if notify.is_placeholder_email(email):
        return
    await notify.send_bid_lost(email, case_id)


@_best_effort
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


@_best_effort
async def dispatch_bid_received(
    line_user_id: str | None, email: str | None, case_id: str, company_name: str, amount: int
) -> None:
    """新規入札通知（依頼者宛）。LINE優先・失敗/未連携時はメールにフォールバック。

    LINE専用ユーザーの仮メール（実メール未設定）宛には送信しない判定は、呼び出し元では
    なくここへ集約する（LINE連携済みなら仮メールでも LINE には届けるため）。
    """
    if line_user_id:
        ok = await line_notify.push_bid_received(line_user_id, case_id, company_name, amount)
        if ok:
            return
    if not email or notify.is_placeholder_email(email):
        return
    await notify.send_bid_received(email, case_id, company_name, amount)


@_best_effort
async def dispatch_message_received(
    line_user_id: str | None,
    transaction_id: str,
    recipient_party: Literal["user", "operator"],
) -> None:
    """新着チャットメッセージ通知（当事者宛）。LINEのみ・同一宛先は5分に1通へ間引く。

    メールでの新着メッセージ通知は既存に無く、メッセージ毎の高頻度配信は迷惑メール化
    （およびSMTPレート消費）のリスクが高いため、意図的にフォールバックを設けない。

    デバウンスの制約（既知の限界）:
      台帳はプロセスメモリ上の dict であり、**単一プロセス内でのみ**有効。
      複数ワーカー／複数インスタンスで運用する場合、ワーカー数に比例して
      Push 回数が増えうる（最悪 N 通/5分）。厳密な全体レート制御が必要になったら
      Redis 等の共有ストアへ台帳を移すこと。再起動で台帳が消えるのも同様に許容
      （通知が1通余分に出るだけで、業務上の不整合は生じない）。
      イベントループ単一スレッド前提のため、判定と記録の間に await を挟まないことで
      チェック＆セットのアトミック性を確保している（順序を変えないこと）。
    """
    if not line_user_id:
        return

    key = (transaction_id, recipient_party)
    now = _monotonic()
    last_sent = _MESSAGE_PUSH_LAST_SENT.get(key)
    if last_sent is not None and now - last_sent < _MESSAGE_PUSH_DEBOUNCE_SECONDS:
        logger.info(
            "notify_dispatch: 新着メッセージ通知をデバウンス抑止 - txn=%s party=%s",
            transaction_id,
            recipient_party,
        )
        return
    # await の前に記録する（同時実行での二重送信を防ぐ）。
    _MESSAGE_PUSH_LAST_SENT[key] = now
    if len(_MESSAGE_PUSH_LAST_SENT) > _MESSAGE_PUSH_SWEEP_THRESHOLD:
        _sweep_message_push_ledger(now)

    ok = await line_notify.push_message_received(line_user_id, transaction_id, recipient_party)
    if not ok:
        # 送れていない以上、5分間の抑止を効かせる理由がない（次のメッセージで再挑戦させる）。
        _MESSAGE_PUSH_LAST_SENT.pop(key, None)
