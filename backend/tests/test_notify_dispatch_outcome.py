"""notify_dispatch.DispatchOutcome の契約テスト（三値の成否判定 delivered/failed/skipped）。

真因整理:
``_best_effort`` は dispatch_* 内の例外を握り潰して再送出しないため、reminders.py の
アラート分岐へ例外は届かない。さらに line_notify.push_* / notify.send_* は**内部で
すでに全例外を捕捉し bool/None を返す**設計のため、本番の最頻失敗モードは例外では
なく「黙った False」である。したがって bool ではなく :data:`DispatchOutcome`
（delivered/failed/skipped）で成否を明示する。

**新しいテストルール**: ここでは notify_dispatch.dispatch_* そのものを patch しない。
patch する境界は外部 HTTP 呼び出しの直前 ``line_notify.push_*`` / ``notify.send_*``
に限定する（dispatch_* を直接 patch すると ``_best_effort`` のラップより外側で
差し替わり、DispatchOutcome の分岐そのものを検証できなくなる＝過去の偽陰性の原因）。
"""

from __future__ import annotations

import inspect
from typing import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest

from app.services import notify_dispatch
from app.services.notify_dispatch import DELIVERED, FAILED, SKIPPED, DispatchOutcome

#: 実メール（is_placeholder_email が False になる通常のメールアドレス）。
_REAL_EMAIL = "user@example.com"
#: LINE専用ユーザーの仮メール（notify.is_placeholder_email が True になる）。
_PLACEHOLDER_EMAIL = "line-U123@line.katazuke.internal"


class _ReminderCase:
    """3種のリマインド dispatch を横展開するためのテーブル定義。"""

    def __init__(
        self,
        name: str,
        dispatch: Callable[..., Awaitable[DispatchOutcome]],
        push_path: str,
        send_path: str,
        build_args: Callable[[str | None, str | None], tuple[object, ...]],
    ) -> None:
        self.name = name
        self.dispatch = dispatch
        self.push_path = push_path
        self.send_path = send_path
        self.build_args = build_args

    def __repr__(self) -> str:  # pytest の parametrize ID を読みやすくする
        return self.name


_REMINDER_CASES = [
    _ReminderCase(
        "dispatch_visit_overdue",
        notify_dispatch.dispatch_visit_overdue,
        "app.services.line_notify.push_visit_overdue",
        "app.services.notify.send_visit_overdue",
        lambda line_user_id, email: (line_user_id, email, "txn-1", "user"),
    ),
    _ReminderCase(
        "dispatch_no_bid_reminder",
        notify_dispatch.dispatch_no_bid_reminder,
        "app.services.line_notify.push_no_bid_reminder",
        "app.services.notify.send_no_bid_reminder",
        lambda line_user_id, email: (line_user_id, email, "case-1"),
    ),
    _ReminderCase(
        "dispatch_bids_pending_reminder",
        notify_dispatch.dispatch_bids_pending_reminder,
        "app.services.line_notify.push_bids_pending_reminder",
        "app.services.notify.send_bids_pending_reminder",
        lambda line_user_id, email: (line_user_id, email, "case-1"),
    ),
]


@pytest.mark.parametrize("case", _REMINDER_CASES, ids=repr)
async def test_line_success_returns_delivered_and_skips_mail(case: _ReminderCase, monkeypatch):
    push_mock = AsyncMock(return_value=True)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(case.push_path, push_mock)
    monkeypatch.setattr(case.send_path, send_mock)

    outcome = await case.dispatch(*case.build_args("U123", _REAL_EMAIL))

    assert outcome == DELIVERED
    push_mock.assert_called_once()
    send_mock.assert_not_called()


@pytest.mark.parametrize("case", _REMINDER_CASES, ids=repr)
async def test_line_failure_then_mail_success_returns_delivered(
    case: _ReminderCase, monkeypatch
):
    push_mock = AsyncMock(return_value=False)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(case.push_path, push_mock)
    monkeypatch.setattr(case.send_path, send_mock)

    outcome = await case.dispatch(*case.build_args("U123", _REAL_EMAIL))

    assert outcome == DELIVERED
    push_mock.assert_called_once()
    send_mock.assert_called_once()


@pytest.mark.parametrize("case", _REMINDER_CASES, ids=repr)
async def test_line_false_then_mail_false_without_exception_returns_failed(
    case: _ReminderCase, monkeypatch
):
    """本件の核心シナリオ: 例外は一切発生しないが、LINE・メールとも黙って False。"""
    push_mock = AsyncMock(return_value=False)
    send_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(case.push_path, push_mock)
    monkeypatch.setattr(case.send_path, send_mock)

    outcome = await case.dispatch(*case.build_args("U123", _REAL_EMAIL))

    assert outcome == FAILED
    push_mock.assert_called_once()
    send_mock.assert_called_once()


@pytest.mark.parametrize("case", _REMINDER_CASES, ids=repr)
@pytest.mark.parametrize("unreachable_email", [None, _PLACEHOLDER_EMAIL], ids=["none", "placeholder"])
async def test_line_false_then_mail_not_attempted_returns_failed(
    case: _ReminderCase, unreachable_email: str | None, monkeypatch
):
    """LINEは試行済みで失敗・メールは試行対象外（仮メール/None）→ 試行した以上 failed。"""
    push_mock = AsyncMock(return_value=False)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(case.push_path, push_mock)
    monkeypatch.setattr(case.send_path, send_mock)

    outcome = await case.dispatch(*case.build_args("U123", unreachable_email))

    assert outcome == FAILED
    push_mock.assert_called_once()
    send_mock.assert_not_called()


@pytest.mark.parametrize("case", _REMINDER_CASES, ids=repr)
@pytest.mark.parametrize("unreachable_email", [None, _PLACEHOLDER_EMAIL], ids=["none", "placeholder"])
async def test_no_line_and_no_mail_target_returns_skipped(
    case: _ReminderCase, unreachable_email: str | None, monkeypatch
):
    push_mock = AsyncMock(return_value=True)
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(case.push_path, push_mock)
    monkeypatch.setattr(case.send_path, send_mock)

    outcome = await case.dispatch(*case.build_args(None, unreachable_email))

    assert outcome == SKIPPED
    push_mock.assert_not_called()
    send_mock.assert_not_called()


@pytest.mark.parametrize("case", _REMINDER_CASES, ids=repr)
async def test_push_exception_does_not_propagate_and_is_failed(case: _ReminderCase, monkeypatch):
    """line_notify.push_* 自体が想定外の例外を投げても、外へ漏れず failed に畳まれる。"""
    push_mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(case.push_path, push_mock)

    outcome = await case.dispatch(*case.build_args("U123", _REAL_EMAIL))

    assert outcome == FAILED


@pytest.mark.parametrize("case", _REMINDER_CASES, ids=repr)
async def test_send_exception_does_not_propagate_and_is_failed(case: _ReminderCase, monkeypatch):
    """notify.send_* 自体が想定外の例外を投げても、外へ漏れず failed に畳まれる。"""
    push_mock = AsyncMock(return_value=False)
    send_mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(case.push_path, push_mock)
    monkeypatch.setattr(case.send_path, send_mock)

    outcome = await case.dispatch(*case.build_args("U123", _REAL_EMAIL))

    assert outcome == FAILED


# ──────────────────────── dispatch_bank_account_changed（両送り型） ────────────────────────


async def test_bank_account_changed_line_success_mail_failure_is_delivered_and_mail_attempted(
    monkeypatch,
):
    """フォールバックではなく両方へ必ず試行する（早期returnで送信をスキップしないことの回帰防止）。"""
    push_mock = AsyncMock(return_value=True)
    send_mock = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.line_notify.push_bank_account_changed", push_mock)
    monkeypatch.setattr("app.services.notify.send_bank_account_changed", send_mock)

    outcome = await notify_dispatch.dispatch_bank_account_changed(
        "U123", _REAL_EMAIL, "変更"
    )

    assert outcome == DELIVERED
    push_mock.assert_called_once()
    send_mock.assert_called_once()  # フォールバック化していれば呼ばれないはず


async def test_bank_account_changed_both_fail_returns_failed(monkeypatch):
    push_mock = AsyncMock(return_value=False)
    send_mock = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.line_notify.push_bank_account_changed", push_mock)
    monkeypatch.setattr("app.services.notify.send_bank_account_changed", send_mock)

    outcome = await notify_dispatch.dispatch_bank_account_changed(
        "U123", _REAL_EMAIL, "変更"
    )

    assert outcome == FAILED


# ──────────────────────── dispatch_message_received（既存挙動の回帰防止） ────────────────────────


@pytest.fixture(autouse=True)
def _reset_message_push_ledger():
    """デバウンス台帳はモジュールグローバルなので、テスト間の汚染を断つ。"""
    notify_dispatch._MESSAGE_PUSH_LAST_SENT.clear()
    yield
    notify_dispatch._MESSAGE_PUSH_LAST_SENT.clear()


async def test_message_received_not_linked_returns_skipped(monkeypatch):
    push_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

    outcome = await notify_dispatch.dispatch_message_received(None, "txn1", "user")

    assert outcome == SKIPPED
    push_mock.assert_not_called()


async def test_message_received_debounce_suppression_returns_skipped(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("app.services.notify_dispatch._monotonic", lambda: clock[0])
    push_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

    first = await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")
    clock[0] += 1.0
    second = await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")

    assert first == DELIVERED
    assert second == SKIPPED
    push_mock.assert_called_once()


async def test_message_received_push_failure_returns_failed_and_clears_ledger(monkeypatch):
    push_mock = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

    outcome = await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")

    assert outcome == FAILED
    # 送れていない以上、5分間の抑止を効かせる理由がない（次のメッセージで再挑戦させる）。
    assert ("txn-deb", "user") not in notify_dispatch._MESSAGE_PUSH_LAST_SENT


# ──────────────────────── メタテスト: 契約の逸脱を CI で検出する ────────────────────────


def test_all_public_dispatch_functions_declare_dispatch_outcome_return_type():
    """将来 dispatch_* を追加した際、戻り値注釈 DispatchOutcome を付け忘れたら CI で落ちる。"""
    dispatch_funcs = [
        (name, func)
        for name, func in inspect.getmembers(notify_dispatch, inspect.isfunction)
        if name.startswith("dispatch_")
    ]
    assert dispatch_funcs, "dispatch_* が1つも見つからない（メタテスト自体が壊れている）"
    for name, func in dispatch_funcs:
        annotation = func.__annotations__.get("return")
        assert annotation == "DispatchOutcome", (
            f"{name} の戻り値注釈が DispatchOutcome になっていない（実際: {annotation!r}）"
        )
