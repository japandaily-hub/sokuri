"""同時に送った要求で、失敗のみカウントの回数制限（login 等）を超えられないこと。

2026-09-27 のセキュリティレビュー M-3（既存の問題）: ``user_login``・``operator_login`` は
``ctx.check_account()``（peek）→ ``await`` で DB を照会 → パスワード照合 → ``record_failure``
の順で動いていた。peek と記録の間に ``await`` があるため、同時に送った要求（single-packet
attack など）はどれも、ほかの要求の失敗が記録される前に peek を通る。1 つの窓で、アカウント軸
（5 回／15 分）・IP 軸（20 回。IPv6 は /64・/56・/48 の各段）の上限を超えて照合させられた。

HTTP 経由のテストは、``get_session`` を差し替えて、各要求の最初の DB 照会（login の利用者・
業者の照会＝照合の直前の ``await``）の手前で全件をそろえる（``_Rendezvous``）。要求は
それぞれ「DB 照会に到達した」か「応答が返った（429 など）」のどちらかになり、全件がそろった
時点で、到達した要求をまとめて先へ進める。修正前のコードでは全件が peek を通って照会に
到達するので、同時送信の並びを決定的に再現できる。

後半は、ストアの予約（``reserve``／``release``）と照合の枠（``PasswordAttempt``）の単体テスト、
および枠の使い方の約束を構文木で固定するメタガード（失敗のみカウントのスコープは必ず枠で
照合する・枠の中に ``await`` を置かない）。
"""

from __future__ import annotations

import ast
import asyncio
import logging
from collections import Counter
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import (
    NoopRateLimitContext,
    RateLimitContext,
    _apply_ip_axis,
    get_rate_limiter,
)
from app.api.v1.endpoints import auth as auth_endpoint
from app.api.v1.router import api_router
from app.core.rate_limit import InMemoryRateLimitStore, RateLimiter, RateLimitRule
from app.db.session import get_session
from tests.test_rate_limit import FakeClock
from tests.test_rate_limit_api import (
    _LOGIN_MSG,
    _config,
    _create_operator,
    _create_user,
)

# 待ち合わせがそろわないまま止まった場合に、テストを失敗させるまでの秒数（通常は一瞬でそろう）。
_RENDEZVOUS_TIMEOUT_SEC = 10.0

_USER_LOGIN = "/api/v1/auth/login"
_OPERATOR_LOGIN = "/api/v1/auth/operator/login"


class _Rendezvous:
    """同時に送った ``expected`` 件を、各要求の最初の DB 照会の手前でそろえる。"""

    def __init__(self, expected: int) -> None:
        self._expected = expected
        self.arrived = 0
        self.finished = 0
        self._open = asyncio.Event()

    def _open_if_everyone_is_here(self) -> None:
        # 到達した要求は開くまで先へ進めないので、開く前の finished は
        # 「照会まで来ずに応答した要求」だけを数えている。
        if self.arrived + self.finished >= self._expected:
            self._open.set()

    async def arrive(self) -> None:
        self.arrived += 1
        self._open_if_everyone_is_here()
        await asyncio.wait_for(self._open.wait(), timeout=_RENDEZVOUS_TIMEOUT_SEC)

    def finish(self) -> None:
        self.finished += 1
        self._open_if_everyone_is_here()


class _SessionWithRendezvous:
    """``get_session`` の差し替え。要求ごとに1つ作る。

    最初の ``scalar()`` の手前で ``_Rendezvous`` にそろえ、そのあとは実セッションへの
    呼び出しを ``lock`` で1本ずつにする（テストの SQLite は1接続を共有するため）。
    """

    def __init__(self, real: AsyncSession, rendezvous: _Rendezvous, lock: asyncio.Lock) -> None:
        self._real = real
        self._rendezvous = rendezvous
        self._lock = lock
        self._waited = False

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        if not self._waited:
            self._waited = True
            await self._rendezvous.arrive()
        async with self._lock:
            return await self._real.scalar(*args, **kwargs)

    async def commit(self) -> None:
        async with self._lock:
            await self._real.commit()

    async def refresh(self, instance: Any, *args: Any, **kwargs: Any) -> None:
        async with self._lock:
            await self._real.refresh(instance, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _ConcurrentLoginHarness:
    """同時送信の再現に使うクライアント一式（アプリ・待ち合わせ・照合の回数）。"""

    def __init__(self, client: AsyncClient, verify_calls: list[str]) -> None:
        self.client = client
        self.verify_calls = verify_calls
        self.rendezvous: _Rendezvous | None = None

    async def post_all(
        self, requests: list[tuple[str, dict[str, str], dict[str, str] | None]]
    ) -> list[httpx.Response]:
        """``(path, json, headers)`` の並びを同時に送り、応答を同じ順で返す。"""
        rendezvous = _Rendezvous(len(requests))
        self.rendezvous = rendezvous

        async def send(
            path: str, body: dict[str, str], headers: dict[str, str] | None
        ) -> httpx.Response:
            try:
                return await self.client.post(path, json=body, headers=headers)
            finally:
                rendezvous.finish()

        return list(await asyncio.gather(*(send(*request) for request in requests)))


def _statuses(responses: list[httpx.Response]) -> Counter[int]:
    return Counter(response.status_code for response in responses)


@pytest.fixture
def verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """auth.py の ``verify_password`` の呼び出し（＝実際に照合した回数）を記録する。"""
    calls: list[str] = []
    real_verify = auth_endpoint.verify_password

    def counting_verify(password: str, stored: str) -> bool:
        calls.append(password)
        return real_verify(password, stored)

    monkeypatch.setattr(auth_endpoint, "verify_password", counting_verify)
    return calls


def _harness_app(db_session: AsyncSession, limiter: RateLimiter, box: dict[str, Any]) -> FastAPI:
    app = FastAPI()
    lock = asyncio.Lock()

    async def override_session() -> AsyncIterator[_SessionWithRendezvous]:
        rendezvous = box["harness"].rendezvous
        assert rendezvous is not None, "post_all() 以外から送った要求です"
        yield _SessionWithRendezvous(db_session, rendezvous, lock)

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.include_router(api_router, prefix="/api/v1")
    return app


async def _open_harness(
    db_session: AsyncSession, limiter: RateLimiter, verify_calls: list[str]
) -> AsyncIterator[_ConcurrentLoginHarness]:
    box: dict[str, Any] = {}
    app = _harness_app(db_session, limiter, box)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        harness = _ConcurrentLoginHarness(client, verify_calls)
        box["harness"] = harness
        yield harness


@pytest.fixture
async def harness(
    db_session: AsyncSession, verify_calls: list[str]
) -> AsyncIterator[_ConcurrentLoginHarness]:
    """本番相当の既定ルール（アカウント軸 5・IP 軸 20・窓 900 秒）。"""
    limiter = RateLimiter(config=_config(), store=InMemoryRateLimitStore(clock=FakeClock()))
    async for opened in _open_harness(db_session, limiter, verify_calls):
        yield opened


@pytest.fixture
async def harness_small_ip(
    db_session: AsyncSession, verify_calls: list[str]
) -> AsyncIterator[_ConcurrentLoginHarness]:
    """IP 軸の上限を 3 にしたもの（IPv6 は /64 が 3・/56 が 6・/48 が 24）。"""
    limiter = RateLimiter(
        config=_config(login_ip_max=3), store=InMemoryRateLimitStore(clock=FakeClock())
    )
    async for opened in _open_harness(db_session, limiter, verify_calls):
        yield opened


# ──────────────────────── 同時送信で上限を超えて照合させられないこと ────────────────────────


class TestConcurrentFailuresCannotExceedTheLimit:
    async def test_user_login_account_axis_caps_password_checks(
        self, harness: _ConcurrentLoginHarness, db_session: AsyncSession
    ):
        """同じアカウントへ誤ったパスワードを 12 件同時に送る。照合は上限の 5 回だけで、
        残り 7 件は照合せずに 429（修正前は 12 件とも照合して 401）。"""
        await _create_user(db_session, "race-user@example.com", password="correct-password-1")
        responses = await harness.post_all(
            [
                (_USER_LOGIN, {"email": "race-user@example.com", "password": f"guess-{i}"}, None)
                for i in range(12)
            ]
        )

        assert _statuses(responses) == {401: 5, 429: 7}
        assert len(harness.verify_calls) == 5
        for response in responses:
            if response.status_code == 429:
                assert response.json() == {"detail": _LOGIN_MSG}
                assert int(response.headers["Retry-After"]) >= 1

    async def test_operator_login_account_axis_caps_password_checks(
        self, harness: _ConcurrentLoginHarness, db_session: AsyncSession
    ):
        """業者ログインも同じ（scope="login"・識別子は "operator:" で分離）。"""
        await _create_operator(db_session, "race-operator@example.com")
        responses = await harness.post_all(
            [
                (
                    _OPERATOR_LOGIN,
                    {"email": "race-operator@example.com", "password": f"guess-{i}"},
                    None,
                )
                for i in range(12)
            ]
        )

        assert _statuses(responses) == {401: 5, 429: 7}
        assert len(harness.verify_calls) == 5

    async def test_login_ip_axis_caps_attempts_across_distinct_accounts(
        self, harness: _ConcurrentLoginHarness
    ):
        """同じ IP から別々のアカウント 30 件へ同時に送る。IP 軸の上限 20 件までしか
        結果（401）を返さない（修正前は 30 件とも 401＝上限を超えて試せた）。"""
        headers = {"X-Forwarded-For": "198.51.100.77"}
        responses = await harness.post_all(
            [
                (_USER_LOGIN, {"email": f"race-ip-{i}@example.com", "password": "guess"}, headers)
                for i in range(30)
            ]
        )

        assert _statuses(responses) == {401: 20, 429: 10}
        for response in responses:
            if response.status_code == 429:
                assert response.json() == {"detail": _LOGIN_MSG}

    async def test_login_ipv6_wider_tier_caps_attempts_spread_over_many_slash64(
        self, harness_small_ip: _ConcurrentLoginHarness
    ):
        """同じ /56 の別々の /64（10 個）から 1 件ずつ同時に送る。/64 の段（上限 3）には
        どれもかからないが、/56 の段（上限 6）で止まる（修正前は 10 件とも 401）。"""
        responses = await harness_small_ip.post_all(
            [
                (
                    _USER_LOGIN,
                    {"email": f"race-v6-{i}@example.com", "password": "guess"},
                    {"X-Forwarded-For": f"2001:db8:7:{i + 1:x}::1"},
                )
                for i in range(10)
            ]
        )

        assert _statuses(responses) == {401: 6, 429: 4}


# ──────────────────── 正しいパスワードの利用者を不必要に 429 にしないこと ────────────────────


class TestConcurrentCorrectPasswordsAreNotRejected:
    async def test_concurrent_correct_logins_to_one_account_all_succeed(
        self, harness: _ConcurrentLoginHarness, db_session: AsyncSession
    ):
        """同じアカウントへ正しいパスワードで 8 件同時（上限 5 を超える件数）。成功は枠を
        使わないので、全件 200。"""
        await _create_user(db_session, "race-ok@example.com", password="correct-password-2")
        responses = await harness.post_all(
            [
                (
                    _USER_LOGIN,
                    {"email": "race-ok@example.com", "password": "correct-password-2"},
                    None,
                )
                for _ in range(8)
            ]
        )

        assert _statuses(responses) == {200: 8}

    async def test_concurrent_correct_logins_after_earlier_failures_all_succeed(
        self, harness: _ConcurrentLoginHarness, db_session: AsyncSession
    ):
        """先に 3 回失敗（上限 5 の手前）してから、正しいパスワードで 4 件同時。
        照合中の要求を枠に数えて先に 429 にする方式だと、3 件目以降が 429 になる。"""
        await _create_user(db_session, "race-ok-late@example.com", password="correct-password-3")
        for i in range(3):
            responses = await harness.post_all(
                [
                    (
                        _USER_LOGIN,
                        {"email": "race-ok-late@example.com", "password": f"typo-{i}"},
                        None,
                    )
                ]
            )
            assert _statuses(responses) == {401: 1}

        responses = await harness.post_all(
            [
                (
                    _USER_LOGIN,
                    {"email": "race-ok-late@example.com", "password": "correct-password-3"},
                    None,
                )
                for _ in range(4)
            ]
        )
        assert _statuses(responses) == {200: 4}

    async def test_concurrent_correct_logins_from_one_ip_beyond_ip_limit_all_succeed(
        self, harness_small_ip: _ConcurrentLoginHarness, db_session: AsyncSession
    ):
        """同じ IP から別々の利用者 6 人が正しいパスワードで同時にログイン（IP 軸の上限 3 を
        超える人数）。成功は IP 軸に数えないので全員 200。"""
        for i in range(6):
            await _create_user(db_session, f"race-ok-ip-{i}@example.com", password="shared-ok-1")
        headers = {"X-Forwarded-For": "198.51.100.78"}
        responses = await harness_small_ip.post_all(
            [
                (
                    _USER_LOGIN,
                    {"email": f"race-ok-ip-{i}@example.com", "password": "shared-ok-1"},
                    headers,
                )
                for i in range(6)
            ]
        )

        assert _statuses(responses) == {200: 6}


# ──────────────────────────── 緊急停止スイッチ ────────────────────────────


class _StoreThatMustNotBeTouched:
    """緊急停止スイッチが「ストアに一切触れない」ことを確かめるためのストア。"""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"RATE_LIMIT_ENABLED=false なのにストアの {name} に触れました")


class TestKillSwitchUnderConcurrency:
    async def test_killswitch_bypasses_completely_even_under_concurrency(
        self, db_session: AsyncSession, verify_calls: list[str]
    ):
        """RATE_LIMIT_ENABLED=false なら、同時送信でも 429 は出ず、ストアにも触れない。"""
        await _create_user(db_session, "race-kill@example.com", password="correct-password-4")
        limiter = RateLimiter(
            config=_config(enabled=False),
            store=_StoreThatMustNotBeTouched(),  # type: ignore[arg-type]
        )
        async for opened in _open_harness(db_session, limiter, verify_calls):
            responses = await opened.post_all(
                [
                    (
                        _USER_LOGIN,
                        {"email": "race-kill@example.com", "password": f"guess-{i}"},
                        None,
                    )
                    for i in range(12)
                ]
                + [
                    (
                        _USER_LOGIN,
                        {"email": "race-kill@example.com", "password": "correct-password-4"},
                        None,
                    )
                ]
            )

        assert _statuses(responses) == {401: 12, 200: 1}
        assert len(verify_calls) == 13


# ──────────────────────── ストアの予約（reserve／release）の単体テスト ────────────────────────


def _store() -> tuple[FakeClock, InMemoryRateLimitStore]:
    clock = FakeClock()
    return clock, InMemoryRateLimitStore(clock=clock)


class TestStoreReservations:
    def test_held_reservations_count_toward_the_limit_until_released(self) -> None:
        """予約は外すまで上限に数える。外せば次の予約が通る。失敗の記録（キー）は作らない。"""
        _, store = _store()
        reservations = [store.reserve("k", 900, 3) for _ in range(3)]
        assert all(r.verdict.allowed and r.token is not None for r in reservations)
        assert len({r.token for r in reservations}) == 3

        rejected = store.reserve("k", 900, 3)
        assert not rejected.verdict.allowed
        assert rejected.token is None
        assert rejected.verdict.retry_after_seconds >= 1

        store.release("k", reservations[0].token)  # type: ignore[arg-type]
        assert store.reserve("k", 900, 3).verdict.allowed
        assert len(store) == 0  # 予約は失敗の記録（バケット）を作らない

    def test_recorded_failures_and_reservations_are_added_together(self) -> None:
        """判定は「記録済みの失敗 + 予約中 + この1回」。どちらか片方だけを見る実装だと、
        照合中の要求がそろって通るか、記録済みの失敗を無視して通ってしまう。"""
        _, store = _store()
        store.hit("k", 900, 3)
        store.hit("k", 900, 3)
        first = store.reserve("k", 900, 3)
        assert first.verdict.allowed
        assert first.verdict.remaining == 0
        assert not store.reserve("k", 900, 3).verdict.allowed

        store.release("k", first.token)  # type: ignore[arg-type]
        assert store.reserve("k", 900, 3).verdict.allowed

    def test_peek_counts_reservations_and_changes_nothing(self) -> None:
        _, store = _store()
        held = [store.reserve("k", 900, 2) for _ in range(2)]
        assert not store.peek("k", 900, 2).allowed
        assert not store.peek("k", 900, 2).allowed  # 何度 peek しても状態は変わらない

        for reservation in held:
            store.release("k", reservation.token)  # type: ignore[arg-type]
        assert store.peek("k", 900, 2).allowed

    def test_reset_clears_failures_but_keeps_other_attempts_reservations(self) -> None:
        """成功（reset）は失敗の記録だけを消し、同時に照合中の別の要求の予約は残す。
        予約まで消すと、その要求の失敗が記録される前に次の要求が判定を通れてしまう。"""
        _, store = _store()
        store.hit("k", 900, 2)
        in_flight = store.reserve("k", 900, 2)
        assert in_flight.verdict.allowed

        store.reset("k")
        assert store.reserve("k", 900, 2).verdict.allowed  # 0 + 1 + 1 = 2
        assert not store.reserve("k", 900, 2).verdict.allowed  # 0 + 2 + 1 = 3

    def test_retry_after_uses_recorded_window_or_full_window(self) -> None:
        """不許可の Retry-After は、記録済みの窓の残り時間。記録が無く予約だけで埋まって
        いるときは窓の長さ（照合中の要求がすべて失敗した場合の値）。"""
        clock, store = _store()
        store.hit("recorded", 900, 1)
        clock.advance(100)
        assert store.reserve("recorded", 900, 1).verdict.retry_after_seconds == 800

        assert store.reserve("reserved-only", 900, 1).verdict.allowed
        assert store.reserve("reserved-only", 900, 1).verdict.retry_after_seconds == 900

    def test_unreleased_reservation_expires_after_the_window(self) -> None:
        """外し忘れた予約（実装の不具合）でも、窓の長さが経てば数えなくなる＝枠が
        恒久的に減らない。"""
        clock, store = _store()
        assert store.reserve("leak", 900, 1).verdict.allowed
        clock.advance(899.9)
        assert not store.reserve("leak", 900, 1).verdict.allowed
        clock.advance(0.1)
        assert store.peek("leak", 900, 1).allowed
        assert store.reserve("leak", 900, 1).verdict.allowed
        assert len(store._reservations["leak"]) == 1  # noqa: SLF001 -- 期限切れは消えている

    def test_release_ignores_unknown_expired_and_repeated_tokens(self) -> None:
        clock, store = _store()
        reservation = store.reserve("k", 10, 1)
        store.release("k", 999_999)
        store.release("other", reservation.token)  # type: ignore[arg-type]
        assert not store.reserve("k", 10, 1).verdict.allowed  # 別 key・不明 token では外れない

        store.release("k", reservation.token)  # type: ignore[arg-type]
        store.release("k", reservation.token)  # type: ignore[arg-type]
        assert "k" not in store._reservations  # noqa: SLF001 -- 空になった key は消す

        expired = store.reserve("k", 10, 1)
        clock.advance(10)
        store.release("k", expired.token)  # type: ignore[arg-type]
        assert store.reserve("k", 10, 1).verdict.allowed

    def test_periodic_sweep_drops_expired_reservations_of_untouched_keys(self) -> None:
        """同じ key に二度と要求が来なくても、外し忘れた予約は定期スイープで消える。"""
        clock, store = _store()
        store.reserve("abandoned", 10, 5)
        clock.advance(11)
        for i in range(256):  # _SWEEP_EVERY 回の hit でスイープが走る
            store.hit(f"other-{i}", 3600, 5)
        assert "abandoned" not in store._reservations  # noqa: SLF001 -- ホワイトボックス検証

    def test_clear_drops_reservations(self) -> None:
        _, store = _store()
        store.reserve("k", 900, 1)
        store.clear()
        assert store.reserve("k", 900, 1).verdict.allowed


class TestRateLimiterReservations:
    def test_disabled_limiter_reserve_and_release_never_touch_the_store(self) -> None:
        limiter = RateLimiter(
            config=_config(enabled=False),
            store=_StoreThatMustNotBeTouched(),  # type: ignore[arg-type]
        )
        rule = RateLimitRule(1, 900)
        reservation = limiter.reserve("k", rule)
        assert reservation.verdict.allowed
        assert reservation.token is None
        limiter.release("k", None)
        limiter.release("k", 1)

    def test_release_without_token_is_a_noop(self) -> None:
        store = InMemoryRateLimitStore(clock=FakeClock())
        limiter = RateLimiter(config=_config(), store=store)
        rule = RateLimitRule(1, 900)
        assert limiter.reserve("k", rule).verdict.allowed
        limiter.release("k", None)
        assert not limiter.reserve("k", rule).verdict.allowed


# ──────────────────────── 照合の枠（PasswordAttempt）の単体テスト ────────────────────────


def _context(
    *,
    account_max: int | None = 5,
    ip: str | None = None,
    ip_max: int = 20,
    scope: str = "login",
) -> tuple[RateLimitContext, InMemoryRateLimitStore]:
    store = InMemoryRateLimitStore(clock=FakeClock())
    limiter = RateLimiter(config=_config(), store=store)
    buckets = (
        _apply_ip_axis(scope, limiter, RateLimitRule(ip_max, 900), count_all=False, ip=ip)
        if ip is not None
        else ()
    )
    ctx = RateLimitContext(
        limiter=limiter,
        scope=scope,
        account_rule=RateLimitRule(account_max, 900) if account_max is not None else None,
        ip_buckets=buckets,
    )
    return ctx, store


class TestPasswordAttempt:
    async def test_await_inside_the_attempt_still_caps_concurrent_attempts(self) -> None:
        """枠の中に await を置いても（照合を asyncio.to_thread へ移した場合など）、同時に
        入れるのは上限の数まで。修正前の peek → await → record では 10 件とも入れた。"""
        ctx, store = _context(account_max=5)
        entered = 0

        async def attempt_once() -> int:
            nonlocal entered
            try:
                with ctx.password_attempt("user:await@example.com") as attempt:
                    entered += 1
                    await asyncio.sleep(0)  # 照合中に他の要求へ順番を譲る
                    attempt.record_failure()
                    return 401
            except HTTPException as exc:
                return exc.status_code

        results = await asyncio.gather(*(attempt_once() for _ in range(10)))
        assert Counter(results) == {401: 5, 429: 5}
        assert entered == 5
        assert store._reservations == {}  # noqa: SLF001 -- 予約はすべて外れている

    async def test_await_inside_the_attempt_caps_each_ipv6_tier(self) -> None:
        """IP軸の全段を予約する。同じ /64 から同時に 5 件なら /64 の上限 2 件まで。"""
        ctx, _ = _context(account_max=None, ip="2001:db8:9:1::1", ip_max=2)
        assert [bucket.axis for bucket in ctx.ip_buckets] == ["ip6_64", "ip6_56", "ip6_48"]

        async def attempt_once() -> int:
            try:
                with ctx.password_attempt("user:v6@example.com") as attempt:
                    await asyncio.sleep(0)
                    attempt.record_failure()
                    return 401
            except HTTPException as exc:
                return exc.status_code

        results = await asyncio.gather(*(attempt_once() for _ in range(5)))
        assert Counter(results) == {401: 2, 429: 3}

    def test_exception_inside_the_attempt_releases_and_counts_nothing(self) -> None:
        ctx, store = _context(account_max=1, ip="198.51.100.5", ip_max=1)
        with pytest.raises(ValueError):
            with ctx.password_attempt("user:boom@example.com"):
                raise ValueError("DB の障害など")
        assert len(store) == 0
        assert store._reservations == {}  # noqa: SLF001
        with ctx.password_attempt("user:boom@example.com") as attempt:  # 枠は残っている
            attempt.record_success()

    def test_leaving_without_settling_counts_nothing(self) -> None:
        """照合せずに抜けた場合（LINE 専用ユーザー・照合前の 409 など）は何も数えない。"""
        ctx, store = _context(account_max=1)
        for _ in range(3):
            with ctx.password_attempt("user:line-only@example.com"):
                pass
        assert len(store) == 0
        assert store._reservations == {}  # noqa: SLF001

    def test_failure_is_recorded_on_every_ip_tier_and_the_account(self) -> None:
        ctx, store = _context(account_max=5, ip="2001:db8:9:2::1", ip_max=20)
        with ctx.password_attempt("user:tiers@example.com") as attempt:
            attempt.record_failure()
        assert len(store) == 4  # /64・/56・/48 の3段＋アカウント軸
        assert store._reservations == {}  # noqa: SLF001

    def test_success_resets_the_account_axis_but_not_the_ip_axis(self) -> None:
        ctx, store = _context(account_max=2, ip="198.51.100.6", ip_max=3)
        with ctx.password_attempt("user:ok@example.com") as attempt:
            attempt.record_failure()
        with ctx.password_attempt("user:ok@example.com") as attempt:
            attempt.record_success()
        # アカウント軸はリセット済み: 失敗 2 回までは入れる。
        for _ in range(2):
            with ctx.password_attempt("user:ok@example.com") as attempt:
                attempt.record_failure()
        # IP軸は成功でリセットされず、3 回の失敗で埋まっている。
        with pytest.raises(HTTPException) as exc_info:
            with ctx.password_attempt("user:another@example.com"):
                pass
        assert exc_info.value.status_code == 429
        assert len(store) == 2  # IP軸の1段＋アカウント軸

    def test_rejection_on_a_later_axis_releases_earlier_reservations(self) -> None:
        """アカウント軸で弾いたとき、先に取った IP軸の予約を残さない（残すと同じ IP の
        別の利用者が、照合もしていない要求の分だけ 429 になる）。"""
        ctx, store = _context(account_max=1, ip="198.51.100.7", ip_max=20)
        with ctx.password_attempt("user:locked@example.com") as attempt:
            attempt.record_failure()
        with pytest.raises(HTTPException) as exc_info:
            with ctx.password_attempt("user:locked@example.com"):
                pytest.fail("上限に達したアカウントで枠に入れてしまった")
        assert exc_info.value.status_code == 429
        assert store._reservations == {}  # noqa: SLF001

    def test_429_detail_is_identical_for_account_and_ip_axes_and_logs_axis(self, caplog) -> None:
        """アカウント軸・IP軸のどちらで弾いても同じ文言（列挙防止）。ログは軸と丸めた
        ip_net だけで、生の IP を出さない。"""
        ctx, _ = _context(account_max=1, ip="198.51.100.8", ip_max=2)
        with ctx.password_attempt("user:a@example.com") as attempt:
            attempt.record_failure()

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            with pytest.raises(HTTPException) as account_exc:
                with ctx.password_attempt("user:a@example.com"):
                    pass
            with ctx.password_attempt("user:b@example.com") as attempt:
                attempt.record_failure()
            with pytest.raises(HTTPException) as ip_exc:
                with ctx.password_attempt("user:c@example.com"):
                    pass

        assert account_exc.value.detail == _LOGIN_MSG
        assert ip_exc.value.detail == _LOGIN_MSG
        assert int(account_exc.value.headers["Retry-After"]) >= 1
        assert int(ip_exc.value.headers["Retry-After"]) >= 1
        messages = [record.getMessage() for record in caplog.records]
        assert any("axis=account " in m and "ip_net=-" in m for m in messages)
        assert any("axis=ip " in m and "ip_net=198.51.100.0/24" in m for m in messages)
        assert not any("198.51.100.8" in m for m in messages)

    def test_misuse_raises_runtime_error(self) -> None:
        ctx, _ = _context()
        attempt = ctx.password_attempt("user:misuse@example.com")
        with pytest.raises(RuntimeError):
            attempt.record_failure()  # with の外
        with attempt:
            attempt.record_failure()
            with pytest.raises(RuntimeError):
                attempt.record_success()  # 二重の確定
        with pytest.raises(RuntimeError):
            with attempt:  # 同じ枠の使い回し
                pass

    def test_noop_context_attempt_is_inert(self) -> None:
        ctx = NoopRateLimitContext()
        with ctx.password_attempt("user:noop@example.com") as attempt:
            attempt.record_failure()
            attempt.record_success()
        assert ctx.password_attempt("x") is ctx.password_attempt("y")


# ──────────────────────── メタガード: 照合の枠の置き場所（構文木で検査） ────────────────────────

ENDPOINTS_DIR = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "endpoints"

# 失敗のみカウント方式のスコープ（パスワード照合の失敗だけを数える）。ここに無いスコープで
# 枠を使うと、ガードが数えた IP軸を record_failure がもう一度数える（二重カウント）。
_PASSWORD_ATTEMPT_SCOPES = frozenset(
    {"login", "password_change", "account_delete", "line_link_reauth"}
)


def _guard_scopes(function: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    """引数の既定値に書かれた ``RateLimitGuard("<scope>")`` の scope。"""
    scopes = set()
    for node in ast.walk(function.args):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "RateLimitGuard"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            scopes.add(node.args[0].value)
    return scopes


def _password_attempt_blocks(function: ast.AsyncFunctionDef | ast.FunctionDef) -> list[ast.With]:
    blocks = []
    for node in ast.walk(function):
        if isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "password_attempt"
            for item in node.items
        ):
            blocks.append(node)
    return blocks


def _awaits_inside(block: ast.With) -> list[int]:
    """枠の本体にある await（入れ子の関数定義の中は実行されないので除く）の行番号。"""
    lines: list[int] = []
    pending: list[ast.AST] = list(block.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            lines.append(node.lineno)
        pending.extend(ast.iter_child_nodes(node))
    return lines


def _endpoint_functions() -> list[tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]]:
    functions = []
    for path in sorted(ENDPOINTS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                functions.append((path.name, node))
    return functions


class TestPasswordAttemptPlacementGuard:
    """``PasswordAttempt`` の使い方の約束を構文木で固定する（原則3「教訓はテストにする」）。"""

    def test_every_password_scope_handler_checks_inside_an_attempt(self) -> None:
        """失敗のみカウントのスコープのハンドラは、照合を必ず枠で包む（枠が無いと
        上限の判定も失敗の記録もされない＝r8 の H-4 と同じ事故になる）。"""
        found = []
        missing = []
        for filename, function in _endpoint_functions():
            scopes = _guard_scopes(function) & _PASSWORD_ATTEMPT_SCOPES
            if not scopes:
                continue
            found.append(function.name)
            if not _password_attempt_blocks(function):
                missing.append(f"{filename}:{function.lineno} {function.name} {sorted(scopes)}")
        assert len(found) >= 9, f"対象のハンドラが足りません（検査の前提が崩れています）: {found}"
        assert not missing, "照合を password_attempt の枠で包んでいません: " + ", ".join(missing)

    def test_attempts_are_used_only_in_password_scopes(self) -> None:
        violations = []
        for filename, function in _endpoint_functions():
            if _password_attempt_blocks(function) and not (
                _guard_scopes(function) & _PASSWORD_ATTEMPT_SCOPES
            ):
                violations.append(f"{filename}:{function.lineno} {function.name}")
        assert not violations, "失敗のみカウント以外のスコープで枠を使っています: " + ", ".join(
            violations
        )

    def test_no_await_inside_password_attempt(self) -> None:
        """枠の中に await を置くと、照合中の予約がほかの要求から見え、同時に届いた正しい
        パスワードの要求が一瞬 429 になりうる（上限そのものは守られる）。照合の材料は枠に
        入る前にそろえる。どうしても枠の中で待つ必要があるなら、その影響を検討したうえで
        ここを見直す（``PasswordAttempt`` の docstring）。"""
        violations = []
        for filename, function in _endpoint_functions():
            for block in _password_attempt_blocks(function):
                violations.extend(f"{filename}:{line}" for line in _awaits_inside(block))
        assert not violations, "password_attempt の枠の中に await があります: " + ", ".join(
            violations
        )
