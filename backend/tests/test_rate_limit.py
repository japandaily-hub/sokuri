"""レート制限ドメイン層の単体テスト（HTTP なし）。

- ``FakeClock``: 窓が最大3600秒あるため実時間 sleep ではテスト不可能。偽クロックを
  注入し、境界（899.9秒後は制限中、900.1秒後は解放）を決定論的に検証する。
- ``app.core.rate_limit``（固定ウィンドウ・InMemoryRateLimitStore・RateLimiter）
- ``app.core.client_ip``（X-Forwarded-For の右から N ホップ解決・ログ用丸め）
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from app.core.client_ip import resolve_client_ip, truncate_ip_for_log
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
)


@dataclass
class FakeClock:
    """``time.monotonic`` 互換の偽クロック。``advance()`` で任意に時間を進める。"""

    now: float = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_request(
    xff: str | list[str] | None, client_host: str | None = "203.0.113.99"
) -> SimpleNamespace:
    """``resolve_client_ip`` が要求する最小限のインターフェースを持つ Request 風オブジェクト。

    ``xff`` にリストを渡すと、同名の X-Forwarded-For ヘッダを複数行として
    構築する（重複ヘッダのテスト用）。plain dict ではなく Starlette の
    ``Headers``（``getlist()`` をサポートする本物の多値ヘッダコンテナ）を
    使うことで、実際の ``request.headers`` と同じ振る舞いを再現する
    （security review High-2: plain dict は ``getlist()`` を持たないため、
    ``get_xff_raw()`` の単体テストとして機能しなかった）。
    """
    if xff is None:
        raw_headers: list[tuple[bytes, bytes]] = []
    elif isinstance(xff, list):
        raw_headers = [(b"x-forwarded-for", v.encode("utf-8")) for v in xff]
    else:
        raw_headers = [(b"x-forwarded-for", xff.encode("utf-8"))]
    headers = Headers(raw=raw_headers)
    client = SimpleNamespace(host=client_host) if client_host is not None else None
    return SimpleNamespace(headers=headers, client=client)


# ──────────────────────────── InMemoryRateLimitStore ────────────────────────────


class TestInMemoryRateLimitStore:
    def test_tc01_hit_allows_up_to_limit_then_blocks(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(5):
            verdict = store.hit("k", window_seconds=900, limit=5)
            assert verdict.allowed is True
        verdict = store.hit("k", window_seconds=900, limit=5)
        assert verdict.allowed is False

    def test_tc02_peek_does_not_consume(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(100):
            verdict = store.peek("k", window_seconds=900, limit=5)
            assert verdict.allowed is True
        for _ in range(5):
            assert store.hit("k", window_seconds=900, limit=5).allowed is True
        assert store.hit("k", window_seconds=900, limit=5).allowed is False

    def test_tc03_window_elapsed_resets_counter(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(5):
            store.hit("k", window_seconds=900, limit=5)
        assert store.hit("k", window_seconds=900, limit=5).allowed is False
        clock.advance(900)
        assert store.hit("k", window_seconds=900, limit=5).allowed is True

    def test_tc04_boundary_exact(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(5):
            store.hit("k", window_seconds=900, limit=5)
        clock.advance(899.9)
        assert store.hit("k", window_seconds=900, limit=5).allowed is False

        clock2 = FakeClock()
        store2 = InMemoryRateLimitStore(clock=clock2)
        for _ in range(5):
            store2.hit("k2", window_seconds=900, limit=5)
        clock2.advance(900.1)
        assert store2.hit("k2", window_seconds=900, limit=5).allowed is True

    def test_tc05_retry_after_is_ceiling_and_at_least_one(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(5):
            store.hit("k", window_seconds=900, limit=5)
        clock.advance(898.4)
        verdict = store.hit("k", window_seconds=900, limit=5)
        assert verdict.allowed is False
        assert verdict.retry_after_seconds == 2  # ceil(900 - 898.4) = ceil(1.6) = 2
        assert verdict.retry_after_seconds >= 1

    def test_tc06_reset_clears_only_target_key(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(5):
            store.hit("k1", window_seconds=900, limit=5)
            store.hit("k2", window_seconds=900, limit=5)
        store.reset("k1")
        assert store.hit("k1", window_seconds=900, limit=5).allowed is True
        assert store.hit("k2", window_seconds=900, limit=5).allowed is False

    def test_tc07_independent_keys(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(5):
            assert store.hit("login:acct:a", window_seconds=900, limit=5).allowed is True
        # scope違い
        assert store.hit("signup:ip:a", window_seconds=3600, limit=10).allowed is True
        # axis違い
        assert store.hit("login:ip:a", window_seconds=900, limit=20).allowed is True
        # 主体違い
        assert store.hit("login:acct:b", window_seconds=900, limit=5).allowed is True

    def test_tc08_max_keys_cap_evicts_oldest(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(max_keys=10, clock=clock)
        for i in range(20):
            store.hit(f"k{i}", window_seconds=900, limit=5)
            clock.advance(0.01)
        assert len(store) <= 10

    def test_tc09_periodic_sweep_removes_expired_entries(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        # バケットは自身の window_seconds を保持するため、"stale" とは異なる
        # 窓長(1秒)のキーでも正確にスイープされる（以前の実装は全scope共通の
        # 最大窓長をヒューリスティックに使っており、短い窓のキーが最大3600秒
        # 残ってしまっていた。security review H-1 対応で修正済み）。
        store.hit("stale", window_seconds=1, limit=5)
        clock.advance(10)
        # _SWEEP_EVERY = 256 回に到達するまで別キーを叩いてスイープを誘発する。
        for i in range(256):
            store.hit(f"filler{i}", window_seconds=900, limit=1000)
        assert "stale" not in store._buckets  # noqa: SLF001 -- ホワイトボックス検証

    def test_qa_l2_peek_immediately_after_hitting_limit_is_blocked(self) -> None:
        """QA指摘 L-2: hit() を limit 回呼んだ直後に peek() が allowed=False を返す
        （HTTP統合テスト経由の間接検証だけでなく、ドメイン層で直接固定化する）。"""
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        for _ in range(5):
            assert store.hit("k", window_seconds=900, limit=5).allowed is True
        assert store.peek("k", window_seconds=900, limit=5).allowed is False

    def test_cap_eviction_protects_blocked_buckets_evicts_harmless_first(self) -> None:
        """security review H-1/M-4/L-5 対応の退避ポリシー検証。

        上限（count >= limit）に達していない「無害な」キーを count 昇順で
        優先的に退避し、上限到達済み（＝ブロック中で被害者を守っている）
        キーは最終手段としてのみ退避対象にすることを固定化する。
        """
        clock = FakeClock()
        max_keys = 20
        store = InMemoryRateLimitStore(max_keys=max_keys, clock=clock)

        # 「被害者」バケット: 上限(5)に達した攻撃対象アカウント。
        # window_start が最初の失敗時刻のまま古くなるよう、先に作っておく
        # （単純な最古優先ロジックだと真っ先に退避されてしまう対象）。
        for _ in range(5):
            store.hit("victim:acct:blocked", window_seconds=900, limit=5)
        clock.advance(1.0)

        # 「無害」バケット群: 上限未到達（count=1）で、victim より新しい。
        harmless_keys = [f"attacker:ip:{i}" for i in range(30)]
        for key in harmless_keys:
            store.hit(key, window_seconds=900, limit=1000)
            clock.advance(0.001)

        assert len(store) <= max_keys
        # 被害者バケットは（無害なキーが多数残っている限り）退避されない。
        assert "victim:acct:blocked" in store._buckets  # noqa: SLF001
        # 無害なキーの一部が優先的に退避されている（被害者より先に消える）。
        surviving_harmless = [k for k in harmless_keys if k in store._buckets]  # noqa: SLF001
        assert len(surviving_harmless) < len(harmless_keys)

    def test_cap_eviction_hysteresis_drops_to_ninety_percent(self) -> None:
        """ヒステリシス: 超過の都度1件ずつではなく max_keys*0.9 まで一気に退避する
        （毎 hit で重い退避処理が走り続ける CPU DoS を防ぐ。security review H-1）。"""
        clock = FakeClock()
        max_keys = 100
        store = InMemoryRateLimitStore(max_keys=max_keys, clock=clock)
        for i in range(max_keys + 1):
            store.hit(f"k{i}", window_seconds=900, limit=1000)
            clock.advance(0.001)
        # 90 (=100*0.9) まで一気に落ちている（101件目のオーバーフローで
        # 1件だけ削除されるのではなく、ヒステリシスにより多めに削除される）。
        assert len(store) == 90

    def test_hmac_key_derivation_does_not_reuse_jwt_secret_directly(self) -> None:
        """security review M-3: レート制限用ハッシュは jwt_secret を直接使わず、
        用途分離した派生鍵を経由する。"""
        from app.api.rate_limit_deps import _hash_identity, _rate_limit_hmac_key
        from app.config import get_settings

        settings = get_settings()
        derived = _rate_limit_hmac_key()
        assert derived != settings.jwt_secret.encode("utf-8")
        # 同じ入力からは常に同じダイジェストが得られる（一貫性）。
        assert _hash_identity("someone@example.com") == _hash_identity("someone@example.com")

    def test_f5_same_key_hit_with_different_limit_and_window_uses_latest_call_params(
        self,
    ) -> None:
        """F-5: 同一ストアキーに異なる (limit, window_seconds) で hit した場合の
        挙動をドメイン層で固定化する。

        本番運用では同一キー（scope:axis:digest）は常に同一スコープの同一
        ルールでのみ呼ばれる想定だが、ストア自体はキー毎にルールを記憶しない
        設計（メモリ最小化）のため、window_start/count は前回の呼び出しから
        引き継がれる一方、経過判定・limit判定は**その回の呼び出しに渡された
        引数**を使う。呼び出し側がルールを一貫させる責務を負う、という
        契約を明示的にテストで固定化する。
        """
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        # 1回目: window=900, limit=5 で count=1。
        v1 = store.hit("k", window_seconds=900, limit=5)
        assert v1.allowed is True
        assert v1.remaining == 4
        # 2回目: 同じキーに window=10, limit=2 で呼ぶ。経過判定は「今回の
        # window_seconds(10)」を使うが、直前の呼び出しからまだ0秒しか
        # 経過していないため窓は継続扱いとなり、count は 1→2 に増える。
        # 判定には「今回の limit(2)」が使われる。
        v2 = store.hit("k", window_seconds=10, limit=2)
        assert v2.allowed is True  # count=2 <= limit=2
        assert v2.remaining == 0
        # 3回目: 同条件でもう1回。count=3 > limit=2 でブロックされる。
        v3 = store.hit("k", window_seconds=10, limit=2)
        assert v3.allowed is False

    def test_tc10_disabled_rate_limiter_always_allows_and_never_touches_store(self) -> None:
        clock = FakeClock()
        store = InMemoryRateLimitStore(clock=clock)
        config = RateLimitConfig(
            enabled=False,
            login_account=RateLimitRule(1, 900),
            login_ip=RateLimitRule(1, 900),
            sensitive_account=RateLimitRule(1, 900),
            signup_ip=RateLimitRule(1, 3600),
            line_ip=RateLimitRule(1, 900),
            max_keys=10000,
        )
        limiter = RateLimiter(config=config, store=store)
        rule = RateLimitRule(1, 900)
        for _ in range(100):
            assert limiter.record("k", rule).allowed is True
        assert len(store) == 0

    def test_tc11_email_hash_key_is_case_normalized(self) -> None:
        # ドメイン層は直接 email を扱わないため、アダプタ層と同一方式
        # （strip+lower してからハッシュ化）でキー導出の性質を検証する。
        from app.api.rate_limit_deps import _hash_identity

        assert _hash_identity("A@b.com") == _hash_identity("a@b.com")
        assert _hash_identity(" a@b.com ") == _hash_identity("a@b.com")


# ──────────────────────────── resolve_client_ip ────────────────────────────


class TestResolveClientIp:
    def test_tc12_no_xff_returns_client_host(self) -> None:
        req = _make_request(xff=None, client_host="198.51.100.7")
        assert resolve_client_ip(req, trusted_hops=1) == "198.51.100.7"

    def test_tc13_single_entry(self) -> None:
        req = _make_request(xff="1.2.3.4")
        assert resolve_client_ip(req, trusted_hops=1) == "1.2.3.4"

    def test_tc14_spoof_resistance_takes_rightmost(self) -> None:
        req = _make_request(xff="9.9.9.9, 203.0.113.5")
        assert resolve_client_ip(req, trusted_hops=1) == "203.0.113.5"

    def test_tc15_two_hops(self) -> None:
        req = _make_request(xff="1.1.1.1, 2.2.2.2, 3.3.3.3")
        assert resolve_client_ip(req, trusted_hops=2) == "2.2.2.2"

    def test_tc16_fewer_entries_than_hops_returns_none_no_exception(self) -> None:
        """要素数不足時は例外を投げず None を返す（security review High-1で
        parts[0] フォールバックを廃止したため、TC-16 の期待値も更新した。
        呼び出し側の RateLimitGuard は None かつ XFF 存在時は 400 で拒否する）。"""
        req = _make_request(xff="1.2.3.4")
        assert resolve_client_ip(req, trusted_hops=2) is None

    @pytest.mark.parametrize("bad_value", ["not-an-ip", "", "; DROP TABLE"])
    def test_tc17_invalid_values_return_none(self, bad_value: str) -> None:
        req = _make_request(xff=bad_value)
        assert resolve_client_ip(req, trusted_hops=1) is None

    def test_tc18_port_suffix_is_stripped(self) -> None:
        req = _make_request(xff="1.2.3.4:5678")
        assert resolve_client_ip(req, trusted_hops=1) == "1.2.3.4"
        req_v6 = _make_request(xff="[2001:db8::1]:443")
        assert resolve_client_ip(req_v6, trusted_hops=1) == "2001:db8::1"

    def test_tc16b_hops_zero_ignores_xff(self) -> None:
        req = _make_request(xff="9.9.9.9, 1.2.3.4", client_host="198.51.100.7")
        assert resolve_client_ip(req, trusted_hops=0) == "198.51.100.7"

    def test_qa_m2_request_client_is_none_and_no_xff_returns_none(self) -> None:
        """QA指摘 M-2: request.client が None（インフラ構成上ありうる）でも
        例外を投げず None を返す（IP軸スキップの判断材料として使われる）。"""
        req = _make_request(xff=None, client_host=None)
        assert resolve_client_ip(req, trusted_hops=1) is None

    def test_qa_m2_request_client_is_none_with_xff_still_resolves(self) -> None:
        """request.client が None でも XFF があれば通常どおり解決できる。"""
        req = _make_request(xff="203.0.113.5", client_host=None)
        assert resolve_client_ip(req, trusted_hops=1) == "203.0.113.5"

    def test_xff_entries_capped_and_rightmost_preserved(self) -> None:
        """security review L-4: XFF の要素数に上限(32)を設ける。切り詰めは
        右端（直近ホップ側）を残し左側（攻撃者が伸ばせる側）を捨てる方向で
        行う必要がある（逆にすると真の直近ホップ自体を失いかねない）。"""
        # 40件のダミーIP + 末尾に本物のクライアントIP。hops=1 なら末尾を取る。
        many = ", ".join(f"10.0.0.{i}" for i in range(40))
        req = _make_request(xff=f"{many}, 203.0.113.77")
        assert resolve_client_ip(req, trusted_hops=1) == "203.0.113.77"

    def test_f1_entries_filtered_before_slicing_keeps_full_32(self) -> None:
        """security review F-1: 「スライス→空要素除去」の順だと、除去前の
        生トークン数で切ってしまい実効保持数が32件未満になりうる。
        空要素を含む入力でも意味のある32件が正しく保持されることを固定化する。"""
        # 空トークンを大量に混ぜても、意味のある要素は40個ある
        # （10.0.0.0〜10.0.0.39）。除去してから末尾32件を保持できていれば
        # 10.0.0.8〜10.0.0.39 が残り、hops=1 は 10.0.0.39 を返すはず。
        noisy = ",,, ,".join(f"10.0.0.{i}" for i in range(40))
        req = _make_request(xff=noisy)
        assert resolve_client_ip(req, trusted_hops=1) == "10.0.0.39"
        # hops=32 なら、保持されている32件の左端（10.0.0.8）を返すはず。
        assert resolve_client_ip(req, trusted_hops=32) == "10.0.0.8"

    def test_high2_duplicate_xff_headers_are_joined_before_processing(self) -> None:
        """security review High-2（実機で再現確認済み）: Starlette の
        ``Headers.get()`` は同名ヘッダが複数あると先頭1件のみを返し、
        RFC 7230 のカンマ結合を行わない。上流が「別行として追加」する
        実装だと、結合しない限り攻撃者側の値だけが見え、右端保持（偽装
        耐性）が完全に失われる。``get_xff_raw()`` 経由で解決することで、
        重複ヘッダでも正しく右端（実クライアントIP）が取れることを固定化する。"""
        req = _make_request(xff=["9.9.9.9", "203.0.113.5"])
        assert resolve_client_ip(req, trusted_hops=1) == "203.0.113.5"

    def test_high1_short_xff_no_longer_falls_back_to_leftmost(self) -> None:
        """security review High-1: 要素数不足時の parts[0]（攻撃者が完全に
        制御できる左端）フォールバックを廃止し、None を返して既存の400
        フェイルクローズに合流させる。"""
        req = _make_request(xff="1.2.3.4")  # 1件のみ、hops=2 は不足
        assert resolve_client_ip(req, trusted_hops=2) is None


class TestIsPrivateOrLoopback:
    """security review 指摘C の判定関数。Python 標準の ``is_private`` は
    RFC 5737 のドキュメント/テスト用レンジ（テストで広く使う「実在しない
    公開IP」）まで True にしてしまうため、それらを誤検知しないことを固定化する。
    """

    @pytest.mark.parametrize(
        "ip",
        ["10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.1.1", "127.0.0.1", "::1"],
    )
    def test_genuine_private_or_loopback_returns_true(self, ip: str) -> None:
        from app.core.client_ip import is_private_or_loopback

        assert is_private_or_loopback(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "100.64.0.1",  # RFC6598 下端
            "100.127.255.254",  # RFC6598 上端
            "169.254.169.254",  # リンクローカル（クラウドメタデータ）
            "fe80::1",  # IPv6 リンクローカル
            "fd00::1",  # IPv6 ULA
        ],
    )
    def test_cloud_internal_ranges_return_true(self, ip: str) -> None:
        """RFC6598・リンクローカルも「内部プロキシIPを掴んでいる」判定に含める。

        RFC6598（100.64.0.0/10）は Kubernetes / クラウドがコンテナ間ネットワークに
        最も一般的に使う帯であり、本判定が守りたいケースの筆頭候補である。
        **Python 標準の ``is_private`` はこのレンジを False と判定する**ため、
        標準に委ねると全体障害の検知に失敗する。この回帰を固定化する。
        """
        from app.core.client_ip import is_private_or_loopback

        assert is_private_or_loopback(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "203.0.113.5",  # RFC5737 TEST-NET-3(テストで多用)
            "198.51.100.10",  # RFC5737 TEST-NET-2(テストで多用)
            "192.0.2.1",  # RFC5737 TEST-NET-1
            "8.8.8.8",  # 実在のグローバルIP
        ],
    )
    def test_documentation_and_global_ranges_return_false(self, ip: str) -> None:
        from app.core.client_ip import is_private_or_loopback

        assert is_private_or_loopback(ip) is False

    def test_invalid_value_returns_false(self) -> None:
        from app.core.client_ip import is_private_or_loopback

        assert is_private_or_loopback("not-an-ip") is False


class TestThrottledWarnings:
    """QA指摘 F-4 / security review Medium-2: 「プロセス内1回きり」の警告は
    攻撃者が起動直後に不正値を1回送るだけで永久に消費でき、以後本物の異常が
    起きても二度と出せなくなる。60秒スロットリングに統一したことと、
    スロットリングが実際に機能する（連続発火時は抑制、間隔経過後は再度出る）
    ことを固定化する。``monkeypatch`` 相当として ``ThrottledLogger.reset()``
    を使い、テスト間の順序に依存しないようにする。
    """

    def test_warn_unresolvable_xff_fires_and_is_throttled(self, caplog) -> None:
        import logging

        from app.api import rate_limit_deps

        rate_limit_deps._unresolvable_xff_throttle.reset()
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            rate_limit_deps._warn_unresolvable_xff("login")
            rate_limit_deps._warn_unresolvable_xff("login")  # 直後の2回目は抑制される
        messages = [r.getMessage() for r in caplog.records]
        assert sum("解決できませんでした" in m for m in messages) == 1

    def test_warn_ip_axis_skipped_fires_and_is_throttled(self, caplog) -> None:
        import logging

        from app.api import rate_limit_deps

        rate_limit_deps._ip_axis_skipped_throttle.reset()
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            rate_limit_deps._warn_ip_axis_skipped("signup")
            rate_limit_deps._warn_ip_axis_skipped("signup")
        messages = [r.getMessage() for r in caplog.records]
        assert sum("スキップしました" in m for m in messages) == 1

    def test_warn_private_ip_skip_fires_and_is_throttled(self, caplog) -> None:
        import logging

        from app.api import rate_limit_deps

        rate_limit_deps._private_ip_skip_throttle.reset()
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            rate_limit_deps._warn_private_ip_skip("login", "10.1.2.3")
            rate_limit_deps._warn_private_ip_skip("login", "10.1.2.3")
        messages = [r.getMessage() for r in caplog.records]
        assert sum("プライベート/ループバック" in m for m in messages) == 1
        # 生IPをログに書かない(/24丸め表記のみ)。
        assert not any("10.1.2.3" in m for m in messages)

    def test_throttle_fires_again_after_interval_elapses(self) -> None:
        """「1回きり」ではないことの直接証明: 偽クロックで間隔経過後は再度出る。"""
        from app.core.log_throttle import ThrottledLogger

        clock = FakeClock()
        throttle = ThrottledLogger(interval_seconds=60.0, clock=clock)
        fire_count = 0

        def _log() -> None:
            nonlocal fire_count
            fire_count += 1

        throttle.emit(_log)
        throttle.emit(_log)  # 抑制される
        assert fire_count == 1
        clock.advance(60.1)
        throttle.emit(_log)  # 間隔経過後は再度発火する
        assert fire_count == 2


class TestTruncateIpForLog:
    def test_tc19_ipv4_slash24_and_ipv6_slash48(self) -> None:
        assert truncate_ip_for_log("203.0.113.9") == "203.0.113.0/24"
        assert truncate_ip_for_log("2001:db8:abcd:1234::1") == "2001:db8:abcd::/48"
        assert truncate_ip_for_log("not-an-ip") == "invalid"


class TestTrustedProxyHopsValidator:
    """QA指摘 L-3: TRUSTED_PROXY_HOPS バリデータのテスト（security review M-5 の
    範囲チェックを含む）。

    上限は当初3だったが、実測（2026-07-18 本番）でプロキシ連鎖が
    client → Cloudflare → Render内部 の3段と判明し、実運用値が上限ぴったりに
    なった。CDN構成が1段増えるだけでインシデント中にコード変更が必要になるため
    8まで緩めている（過大設定は parts[0] フォールバック廃止により、静かな
    バイパスではなく即座に可視な400として現れる）。
    """

    @pytest.mark.parametrize("value", [0, 1, 2, 3, 8])
    def test_values_within_range_are_accepted(self, value: int) -> None:
        from app.config import Settings

        settings = Settings(_env_file=None, trusted_proxy_hops=value)
        assert settings.trusted_proxy_hops == value

    @pytest.mark.parametrize("value", [-1, -100])
    def test_negative_values_are_rejected(self, value: int) -> None:
        from pydantic import ValidationError

        from app.config import Settings

        with pytest.raises(ValidationError, match="TRUSTED_PROXY_HOPS"):
            Settings(_env_file=None, trusted_proxy_hops=value)

    @pytest.mark.parametrize("value", [9, 100])
    def test_values_above_upper_bound_are_rejected(self, value: int) -> None:
        """桁を間違えた設定値（例: 100）は起動時に弾く。"""
        from pydantic import ValidationError

        from app.config import Settings

        with pytest.raises(ValidationError, match="TRUSTED_PROXY_HOPS"):
            Settings(_env_file=None, trusted_proxy_hops=value)


class TestRateLimitFieldValidators:
    """security review F-2: RL_MAX_KEYS=0 や *_MAX=0 等でレート制限が事実上
    無効化されるのを防ぐための下限バリデーション。"""

    def test_rl_max_keys_below_100_is_rejected(self) -> None:
        from pydantic import ValidationError

        from app.config import Settings

        with pytest.raises(ValidationError, match="RL_MAX_KEYS"):
            Settings(_env_file=None, rl_max_keys=0)
        with pytest.raises(ValidationError, match="RL_MAX_KEYS"):
            Settings(_env_file=None, rl_max_keys=99)

    def test_rl_max_keys_default_is_100000(self) -> None:
        """security review Medium-1: 10000 → 100000 に引き上げ済み。"""
        from app.config import Settings

        assert Settings(_env_file=None).rl_max_keys == 100000

    def test_rl_max_keys_100_is_accepted(self) -> None:
        from app.config import Settings

        assert Settings(_env_file=None, rl_max_keys=100).rl_max_keys == 100

    @pytest.mark.parametrize(
        "field",
        [
            "rl_login_account_max",
            "rl_login_ip_max",
            "rl_sensitive_account_max",
            "rl_signup_ip_max",
            "rl_line_ip_max",
        ],
    )
    def test_rl_max_fields_reject_zero(self, field: str) -> None:
        from pydantic import ValidationError

        from app.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: 0})
        # 1は許容される。
        assert getattr(Settings(_env_file=None, **{field: 1}), field) == 1

    @pytest.mark.parametrize(
        "field",
        [
            "rl_login_window_sec",
            "rl_sensitive_window_sec",
            "rl_signup_window_sec",
            "rl_line_window_sec",
        ],
    )
    def test_rl_window_fields_reject_zero(self, field: str) -> None:
        from pydantic import ValidationError

        from app.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: 0})
        assert getattr(Settings(_env_file=None, **{field: 1}), field) == 1
