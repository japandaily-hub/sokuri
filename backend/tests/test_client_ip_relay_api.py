"""署名付き中継IP（login/line_exchange限定）の HTTP 統合テスト。

``tests/test_rate_limit_api.py`` の ``create_test_app`` パターン・フィクスチャ
（``client`` / ``client_killswitch`` / ``fake_clock``）と、その他のヘルパー
（``_create_user`` / ``_create_operator`` / ``_signup_user`` / ``_mock_line_get``
等）をそのまま import して再利用する（同一のレート制限テスト用アプリ構成を
二重管理しないため）。

既存の ``test_rate_limit_api.py`` / ``test_rate_limit.py`` が全緑であることが、
``rate_limit_deps._apply_ip_axis`` 抽出（既存インライン実装のリファクタ）の
回帰網になる。
"""

from __future__ import annotations

import logging
import secrets
import time
from unittest.mock import patch

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import rate_limit_deps
from app.config import get_settings
from app.core.client_ip_relay import (
    RELAY_HEADER_NAME,
    _reset_relay_log_state_for_tests,
    build_relay_header_value,
    compute_relay_signature,
)
from tests.test_client_ip_relay import _clear_relay_secret_caches
from tests.test_rate_limit_api import (  # noqa: F401 -- フィクスチャ再エクスポート
    SMALL_LINE_MAX,
    SMALL_LOGIN_IP_MAX,
    _TEST_LINE_CLIENT_ID,
    _TEST_PUBLIC_IP_HEADERS,
    _create_operator,
    _create_user,
    _mock_line_get,
    _signup_user,
    client,
    client_killswitch,
    client_small_limits,
    fake_clock,
)

# ──────────────────────────── 中継用の鍵（HTTP統合テスト専用・固定ベクトルとは別） ────────────────────────────
# security review L-2: parse_relay_secrets / inspect_relay_secrets が既知の
# テスト鍵命名パターン（"katazuke-relay-test-"・"http-relay-test-key-" 接頭辞等）
# を明示的に拒否するようになったため、ここでは実際に parse を通す必要がある
# モジュール読み込み時生成のランダム鍵を使う（署名にも同じ鍵を使う）。
_RELAY_KEY_A_RAW = secrets.token_urlsafe(48)
_RELAY_KEY_B_RAW = secrets.token_urlsafe(48)
_RELAY_KEY_A = _RELAY_KEY_A_RAW.encode("ascii")
_RELAY_KEY_B = _RELAY_KEY_B_RAW.encode("ascii")


def _relay_headers(
    key: bytes,
    *,
    ip: str,
    method: str = "POST",
    path: str = "/api/v1/auth/login",
    timestamp: int | None = None,
) -> dict[str, str]:
    ts = timestamp if timestamp is not None else int(time.time())
    value = build_relay_header_value(key, method=method, path=path, timestamp=ts, ip=ip)
    return {RELAY_HEADER_NAME: value}


@pytest.fixture(autouse=True)
def _reset_relay_module_state():
    """テスト間の相互干渉を防ぐ（QA L-2）。

    - ``_clear_relay_secret_caches()``（``parse_relay_secrets`` /
      ``inspect_relay_secrets`` の ``@lru_cache`` を対で clear。QA L-A）:
      引数の生文字列自体をキーにするため、テストごとに異なる鍵文字列を
      使えば本来は不要だが、明示的に毎回クリアすることで「前のテストの
      キャッシュが残っていないか」を気にせず書けるようにする。
    - ``_reset_relay_log_state_for_tests()``: 起動後初回 WARNING 格上げの
      (scope, key_slot) 集合・スロットリング辞書をプロセス内グローバルとして
      持つため、テストごとに初期化しないと前のテストの状態が漏れる（例えば
      "login" scope・key_slot=0 が既に初回消費済みだと、本テストの最初の
      採用が WARNING ではなく INFO になり、ログ関連のアサーションが崩れる）。
    """
    _clear_relay_secret_caches()
    _reset_relay_log_state_for_tests()
    yield
    _clear_relay_secret_caches()
    _reset_relay_log_state_for_tests()


# ──────────────────────────── 1. 核心の回帰 ────────────────────────────


class TestRelayCoreBehavior:
    async def test_relay_ip_a_blocks_after_20_then_ip_b_succeeds(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        # 同じ XFF（Vercel 相当の固定送信元）でも、中継ヘッダの利用者IPで数える。
        # QA M-1: ヘッダはループの外で1回だけ作らず、毎リクエスト作り直す
        # （タイムスタンプを含むため、ループの外で1回だけ作って使い回すと
        # 60秒を超えた瞬間に expired へ落ち偽陽性・偽陰性の原因になる）。
        vercel_xff = {"X-Forwarded-For": "198.51.100.200"}
        for i in range(20):
            email = f"relay-core-{i}@example.com"
            await _create_user(db_session, email)
            headers = {**vercel_xff, **_relay_headers(_RELAY_KEY_A, ip="203.0.113.50")}
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-core-final@example.com")
        headers_final = {**vercel_xff, **_relay_headers(_RELAY_KEY_A, ip="203.0.113.50")}
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-core-final@example.com", "password": "wrong-password"},
            headers=headers_final,
        )
        assert r.status_code == 429

        # 同じ XFF でも中継IPが別（B）なら正しいパスワードで200。
        await _create_user(
            db_session, "relay-core-b@example.com", password="correct-pass-core-b1"
        )
        headers_other_ip = {
            **vercel_xff,
            **_relay_headers(_RELAY_KEY_A, ip="203.0.113.51"),
        }
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-core-b@example.com", "password": "correct-pass-core-b1"},
            headers=headers_other_ip,
        )
        assert r.status_code == 200


# ──────────────────────────── 2. 直接アクセスと中継が同一バケットを共有 ────────────────────────────


class TestRelaySharesHopsBucketForSameIp:
    async def test_direct_and_relayed_same_ip_do_not_double_the_quota(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        shared_ip = "203.0.113.60"
        for i in range(10):
            email = f"relay-shared-direct-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers={"X-Forwarded-For": shared_ip},
            )
            assert r.status_code == 401
        for i in range(10):
            email = f"relay-shared-relayed-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=_relay_headers(_RELAY_KEY_A, ip=shared_ip),
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-shared-final@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-shared-final@example.com", "password": "wrong-password"},
            headers=_relay_headers(_RELAY_KEY_A, ip=shared_ip),
        )
        assert r.status_code == 429


# ──────────────────────────── 3. 中継は hops の枠を汚さない ────────────────────────────


class TestRelayDoesNotPolluteDirectHopsBucket:
    async def test_relayed_ip_does_not_pollute_direct_hops_bucket(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """中継が採用されている間、hops 方式が見る X-Forwarded-For
        （Vercel 相当の固定送信元）に同じ値を乗せていても、hops 側のバケット
        には一切カウントされないことを確かめる。

        QA 指摘（見かけ倒しの回帰網だった問題）: 以前はこの中継要求に
        X-Forwarded-For を付けていなかったため、hops 側の解決結果は
        ASGITransport の ``request.client.host``（127.0.0.1・ループバック）に
        なり、``is_private_or_loopback`` により IP軸そのものがスキップされて
        いた（``_TEST_PUBLIC_IP_HEADERS`` docstring 参照）。そのため最後の
        直接アクセスは「一度もカウントされていないバケット」への初回アクセス
        に過ぎず、「中継が hops の枠を汚さない」ことを実際には何も検証できて
        いなかった。中継要求にも同じ XFF を付けることで、hops 側のバケットが
        実在しうる状態を作った上で、それでも汚染されていないこと（中継ヘッダ
        無しの直接アクセスが200のまま）を確かめる。
        """
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        relay_ip = "203.0.113.70"
        for i in range(20):
            email = f"relay-nopollute-{i}@example.com"
            await _create_user(db_session, email)
            headers = {
                **_TEST_PUBLIC_IP_HEADERS,
                **_relay_headers(_RELAY_KEY_A, ip=relay_ip),
            }
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_user(
            db_session, "relay-nopollute-direct@example.com", password="correct-pass-np1"
        )
        # 中継ヘッダを付けず、同じ XFF・正しいパスワードで直接アクセスする。
        # hops 側のバケットが20回分カウントされていれば 429 になるはずだが、
        # 中継採用時は hops のカウントに一切触れないため 200 のまま。
        r = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "relay-nopollute-direct@example.com",
                "password": "correct-pass-np1",
            },
            headers=_TEST_PUBLIC_IP_HEADERS,
        )
        assert r.status_code == 200


# ──────────────────────────── 4. 不採用なら hops へフォールバック ────────────────────────────

_FALLBACK_XFF = "198.51.100.210"


def _headers_bad_signature(varying_ip: str) -> dict[str, str]:
    value = build_relay_header_value(
        _RELAY_KEY_B,
        method="POST",
        path="/api/v1/auth/login",
        timestamp=int(time.time()),
        ip=varying_ip,
    )
    return {"X-Forwarded-For": _FALLBACK_XFF, RELAY_HEADER_NAME: value}


def _headers_expired(varying_ip: str) -> dict[str, str]:
    value = build_relay_header_value(
        _RELAY_KEY_A,
        method="POST",
        path="/api/v1/auth/login",
        timestamp=int(time.time()) - 1000,
        ip=varying_ip,
    )
    return {"X-Forwarded-For": _FALLBACK_XFF, RELAY_HEADER_NAME: value}


def _headers_malformed(varying_ip: str) -> dict[str, str]:
    return {"X-Forwarded-For": _FALLBACK_XFF, RELAY_HEADER_NAME: f"garbage-{varying_ip}"}


def _headers_unsupported_version(varying_ip: str) -> dict[str, str]:
    ts = int(time.time())
    sig = compute_relay_signature(
        _RELAY_KEY_A, method="POST", path="/api/v1/auth/login", timestamp=str(ts), ip=varying_ip
    )
    return {
        "X-Forwarded-For": _FALLBACK_XFF,
        RELAY_HEADER_NAME: f"v2;{ts};{varying_ip};{sig}",
    }


def _headers_private_relay_ip(varying_ip: str) -> dict[str, str]:
    value = build_relay_header_value(
        _RELAY_KEY_A,
        method="POST",
        path="/api/v1/auth/login",
        timestamp=int(time.time()),
        ip=varying_ip,
    )
    return {"X-Forwarded-For": _FALLBACK_XFF, RELAY_HEADER_NAME: value}


_FALLBACK_CASES = [
    pytest.param(_headers_bad_signature, "public", id="bad_signature"),
    pytest.param(_headers_expired, "public", id="expired"),
    pytest.param(_headers_malformed, "public", id="malformed"),
    pytest.param(_headers_unsupported_version, "public", id="unsupported_version"),
    pytest.param(_headers_private_relay_ip, "private", id="private_relay_ip"),
]


class TestUnacceptedRelayFallsBackToHops:
    @pytest.mark.parametrize("header_builder,ip_kind", _FALLBACK_CASES)
    async def test_fallback_to_hops_after_login_ip_max(
        self,
        client_small_limits: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
        header_builder,
        ip_kind: str,
    ) -> None:
        """QA M-4: しきい値到達だけを確認するテストのため、login_ip_max を
        小さくした ``client_small_limits`` を使い試験時間を短縮する（本番値
        20 での核心の回帰は ``TestRelayCoreBehavior`` に別途残している）。"""
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )

        def _ip_for(i: int) -> str:
            return f"10.9.{i}.1" if ip_kind == "private" else f"203.0.113.{i}"

        case_id = header_builder.__name__
        for i in range(SMALL_LOGIN_IP_MAX):
            email = f"relay-fb-{case_id}-{i}@example.com"
            await _create_user(db_session, email)
            r = await client_small_limits.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=header_builder(_ip_for(i)),
            )
            assert r.status_code == 401

        await _create_user(db_session, f"relay-fb-{case_id}-final@example.com")
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={
                "email": f"relay-fb-{case_id}-final@example.com",
                "password": "wrong-password",
            },
            headers=header_builder(_ip_for(99)),
        )
        assert r.status_code == 429

    async def test_duplicate_relay_header_falls_back_to_hops(
        self, client_small_limits: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """重複した中継ヘッダ（malformed）でも hops へフォールバックする。

        httpx の ``headers`` はリスト形式で重複キーを送れる（辞書だと後勝ちで
        1本に潰れてしまうため、この検証にはリスト形式が必須）。QA M-4:
        ``client_small_limits`` でしきい値到達までの試行回数を減らす。
        """
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )

        def _dup_headers(varying_ip: str) -> list[tuple[str, str]]:
            value = build_relay_header_value(
                _RELAY_KEY_A,
                method="POST",
                path="/api/v1/auth/login",
                timestamp=int(time.time()),
                ip=varying_ip,
            )
            return [
                ("X-Forwarded-For", _FALLBACK_XFF),
                (RELAY_HEADER_NAME, value),
                (RELAY_HEADER_NAME, value),
            ]

        for i in range(SMALL_LOGIN_IP_MAX):
            email = f"relay-fb-dup-{i}@example.com"
            await _create_user(db_session, email)
            r = await client_small_limits.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=_dup_headers(f"203.0.113.{i}"),
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-fb-dup-final@example.com")
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={"email": "relay-fb-dup-final@example.com", "password": "wrong-password"},
            headers=_dup_headers("203.0.113.199"),
        )
        assert r.status_code == 429


# ──────────────────────────── 5. 対象外 scope は無視 ────────────────────────────


class TestRelayIgnoredForIneligibleScopes:
    async def test_signup_ignores_relay_header_even_with_valid_signature(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """鍵が漏洩していても signup 等（login/line_exchange 以外）は動かせない。"""
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        fixed_xff = {"X-Forwarded-For": "198.51.100.220"}

        def _headers(varying_ip: str) -> dict[str, str]:
            value = build_relay_header_value(
                _RELAY_KEY_A,
                method="POST",
                path="/api/v1/auth/signup",
                timestamp=int(time.time()),
                ip=varying_ip,
            )
            return {**fixed_xff, RELAY_HEADER_NAME: value}

        for i in range(10):
            r = await _signup_user(
                client,
                f"relay-signup-ignored-{i}@example.com",
                headers=_headers(f"203.0.113.{150 + i}"),
            )
            assert r.status_code == 201, r.text
        r = await _signup_user(
            client,
            "relay-signup-ignored-final@example.com",
            headers=_headers("203.0.113.199"),
        )
        assert r.status_code == 429


# ──────────────────────────── 6. 鍵の入れ替え ────────────────────────────


class TestKeyRotation:
    async def test_rotating_from_a_and_b_to_b_only_drops_a(
        self, client_small_limits: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """QA M-4: しきい値到達の確認は具体的に20回である必要が無いため、
        ``client_small_limits``（login_ip_max=3）で試験時間を短縮する。"""
        settings = get_settings()
        monkeypatch.setattr(
            settings,
            "client_ip_relay_secrets",
            SecretStr(f"{_RELAY_KEY_A_RAW},{_RELAY_KEY_B_RAW}"),
        )
        await _create_user(
            db_session, "relay-rotate-a@example.com", password="correct-pass-rot1"
        )
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={"email": "relay-rotate-a@example.com", "password": "correct-pass-rot1"},
            headers=_relay_headers(_RELAY_KEY_A, ip="203.0.113.80"),
        )
        assert r.status_code == 200

        await _create_user(
            db_session, "relay-rotate-b@example.com", password="correct-pass-rot2"
        )
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={"email": "relay-rotate-b@example.com", "password": "correct-pass-rot2"},
            headers=_relay_headers(_RELAY_KEY_B, ip="203.0.113.81"),
        )
        assert r.status_code == 200

        # B のみに切り替えると、A の署名は不採用になり hops へフォールバックする。
        monkeypatch.setattr(settings, "client_ip_relay_secrets", SecretStr(_RELAY_KEY_B_RAW))
        fixed_xff = {"X-Forwarded-For": "198.51.100.230"}
        for i in range(SMALL_LOGIN_IP_MAX):
            email = f"relay-rotate-afterB-{i}@example.com"
            await _create_user(db_session, email)
            headers = {
                **fixed_xff,
                **_relay_headers(_RELAY_KEY_A, ip=f"203.0.113.{160 + i}"),
            }
            r = await client_small_limits.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-rotate-afterB-final@example.com")
        headers_final = {**fixed_xff, **_relay_headers(_RELAY_KEY_A, ip="203.0.113.199")}
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={
                "email": "relay-rotate-afterB-final@example.com",
                "password": "wrong-password",
            },
            headers=headers_final,
        )
        assert r.status_code == 429


# ──────────────────────────── 7. line_exchange ────────────────────────────


class TestRelayLineExchange:
    async def test_line_exchange_relay_ip_a_blocks_then_b_succeeds(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "line_client_id", _TEST_LINE_CLIENT_ID)
        monkeypatch.setattr(settings, "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW))
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get()):
            # QA M-1: ヘッダはループの外で1回だけ作らず、毎リクエスト作り直す
            # （タイムスタンプを含むため、使い回すと60秒経過時に expired へ
            # 落ちて偽陽性・偽陰性の原因になる）。
            for _ in range(20):
                headers_a = _relay_headers(
                    _RELAY_KEY_A, ip="203.0.113.90", path="/api/v1/auth/line/exchange"
                )
                r = await client.post(
                    "/api/v1/auth/line/exchange",
                    json={"line_access_token": "dummy-line-token"},
                    headers=headers_a,
                )
                assert r.status_code == 200
            headers_a_final = _relay_headers(
                _RELAY_KEY_A, ip="203.0.113.90", path="/api/v1/auth/line/exchange"
            )
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=headers_a_final,
            )
            assert r.status_code == 429

            headers_b = _relay_headers(
                _RELAY_KEY_A, ip="203.0.113.91", path="/api/v1/auth/line/exchange"
            )
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=headers_b,
            )
            assert r.status_code == 200


# ──────────────────────────── 8. operator/login ────────────────────────────


class TestRelayOperatorLogin:
    async def test_operator_login_counted_by_relay_ip(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        # QA M-1: ヘッダはループの外で1回だけ作らず、毎リクエスト作り直す。
        for i in range(20):
            email = f"relay-op-{i}@example.com"
            await _create_operator(db_session, email)
            headers = _relay_headers(
                _RELAY_KEY_A, ip="203.0.113.95", path="/api/v1/auth/operator/login"
            )
            r = await client.post(
                "/api/v1/auth/operator/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_operator(db_session, "relay-op-final@example.com")
        headers_final = _relay_headers(
            _RELAY_KEY_A, ip="203.0.113.95", path="/api/v1/auth/operator/login"
        )
        r = await client.post(
            "/api/v1/auth/operator/login",
            json={"email": "relay-op-final@example.com", "password": "wrong-password"},
            headers=headers_final,
        )
        assert r.status_code == 429


# ──────────────────────────── 9. 鍵未設定は現行と同一 ────────────────────────────


class TestRelayUnconfiguredMatchesBaseline:
    async def test_no_keys_configured_behaves_like_hops_only(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "client_ip_relay_secrets", SecretStr(""))
        fixed_xff = {"X-Forwarded-For": "198.51.100.240"}
        headers = {**fixed_xff, **_relay_headers(_RELAY_KEY_A, ip="203.0.113.96")}
        for i in range(20):
            email = f"relay-unconf-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-unconf-final@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-unconf-final@example.com", "password": "wrong-password"},
            headers=headers,
        )
        assert r.status_code == 429


# ──────────────────────────── 10. 採用時は XFF 不正でも 400 にならない ────────────────────────────


class TestRelayAcceptedBypassesHopsValidation:
    async def test_relay_accepted_with_malformed_xff_not_400(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        await _create_user(db_session, "relay-malformed-xff@example.com")
        headers = {
            "X-Forwarded-For": "; DROP TABLE",
            **_relay_headers(_RELAY_KEY_A, ip="203.0.113.97"),
        }
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-malformed-xff@example.com", "password": "wrong-password"},
            headers=headers,
        )
        assert r.status_code == 401
        assert r.status_code != 400


# ──────────────────────────── 11. 採用時は hops 用 WARNING が出ない ────────────────────────────


class TestRelayAcceptedEmitsNoHopsWarning:
    async def test_relay_accepted_with_private_xff_emits_no_hops_warning(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        await _create_user(db_session, "relay-private-xff@example.com")
        headers = {
            "X-Forwarded-For": "10.0.0.5",
            **_relay_headers(_RELAY_KEY_A, ip="203.0.113.98"),
        }
        with caplog.at_level(logging.WARNING, logger="app.api.rate_limit_deps"):
            r = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "relay-private-xff@example.com",
                    "password": "wrong-password",
                },
                headers=headers,
            )
        assert r.status_code == 401
        assert not any("プライベート" in rec.getMessage() for rec in caplog.records)


# ──────────────────────────── 12. キルスイッチ中は中継を読まない ────────────────────────────


class TestRelayIgnoredWhenKillswitchOn:
    async def test_killswitch_never_reads_relay_header_or_logs(
        self, client_killswitch: AsyncClient, db_session: AsyncSession, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        await _create_user(db_session, "relay-killswitch@example.com")
        headers = _relay_headers(_RELAY_KEY_A, ip="203.0.113.99")
        # QA M-4: キルスイッチONではレート制限自体が働かないため、繰り返し
        # 回数はログが一切出ないことの確認材料に過ぎない（本番値20や100で
        # ある必要が無い）。5回に減らして試験時間を短縮する。
        with caplog.at_level(logging.INFO, logger="app.core.client_ip_relay"):
            for _ in range(5):
                r = await client_killswitch.post(
                    "/api/v1/auth/login",
                    json={
                        "email": "relay-killswitch@example.com",
                        "password": "wrong-password",
                    },
                    headers=headers,
                )
                assert r.status_code == 401
        assert len(caplog.records) == 0


# ──────────────────────────── 13. 不採用の中継は 400 のフェイルクローズを回避できない ────────────────────────────


class TestRejectedRelayCannotBypassFailClosedXff:
    async def test_bad_signature_relay_with_malformed_xff_still_400(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """security review L-6: 不採用（この例では鍵違いによる bad_signature）の
        中継ヘッダは、XFF 不正時のフェイルクローズ（400）を回避する経路には
        ならない（中継ヘッダを付与するだけで 400 を潜り抜けられないことの固定。
        ``TestRelayAcceptedBypassesHopsValidation`` の「採用時は400にならない」
        と対になる、不採用側の固定）。"""
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        headers = {
            "X-Forwarded-For": "; DROP TABLE",
            # 設定されている鍵は A のみだが、B で署名する→ bad_signature で不採用。
            **_relay_headers(_RELAY_KEY_B, ip="203.0.113.120"),
        }
        r = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "relay-rejected-badsig-xff@example.com",
                "password": "wrong-password",
            },
            headers=headers,
        )
        assert r.status_code == 400


# ──────────────────────────── 14. 検証・ログ処理の例外はフォールバックし判定へ影響しない ────────────────────────────


class TestRelayVerificationExceptionsDoNotBreakAuth:
    async def test_verify_exception_falls_back_to_401_not_500(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch, caplog
    ) -> None:
        """QA M-3 固定: 検証本体（verify_request_client_ip_relay）が例外を
        送出しても 500 化せず、hops 方式へフォールバックして通常どおり 401 に
        なる（本機能の障害が認証系全体を巻き込まないという設計契約の直接
        検証）。WARNING/ERROR ログも出る。"""
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("boom-verify")

        monkeypatch.setattr(rate_limit_deps, "verify_request_client_ip_relay", _boom)
        await _create_user(db_session, "relay-verify-exc@example.com")
        with caplog.at_level(logging.WARNING):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": "relay-verify-exc@example.com", "password": "wrong-password"},
                headers=_relay_headers(_RELAY_KEY_A, ip="203.0.113.121"),
            )
        assert r.status_code == 401
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    async def test_log_relay_outcome_exception_does_not_change_verdict(
        self, client_small_limits: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """QA M-3 固定: ログ出力（log_relay_outcome）が例外を送出しても判定
        結果（採用可否・カウント）は変わらない。中継IPで login_ip_max 回
        失敗させると、ログが壊れていても次の1回は429になる（＝正しく中継IPで
        カウントされ続けたことの証明）。"""
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("boom-log")

        monkeypatch.setattr(rate_limit_deps, "log_relay_outcome", _boom)
        relay_ip = "203.0.113.122"
        fixed_xff = {"X-Forwarded-For": "198.51.100.250"}
        for i in range(SMALL_LOGIN_IP_MAX):
            email = f"relay-log-exc-{i}@example.com"
            await _create_user(db_session, email)
            headers = {**fixed_xff, **_relay_headers(_RELAY_KEY_A, ip=relay_ip)}
            r = await client_small_limits.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-log-exc-final@example.com")
        headers_final = {**fixed_xff, **_relay_headers(_RELAY_KEY_A, ip=relay_ip)}
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={"email": "relay-log-exc-final@example.com", "password": "wrong-password"},
            headers=headers_final,
        )
        assert r.status_code == 429


# ──────────────────────────── 15. 対象 scope の固定 ────────────────────────────


def test_relay_eligible_scopes_is_fixed_to_login_and_line_exchange() -> None:
    """QA: 中継の対象 scope（login/line_exchange の2つのみ）が変更されて
    いないことを固定する。signup・case_create 等へ誤って拡大されると、鍵
    漏洩時の悪用範囲が構造的に広がってしまうため、変更時は必ず設計判断を
    経ること（``app.core.client_ip_relay`` モジュール docstring 参照）。"""
    assert rate_limit_deps._RELAY_ELIGIBLE_SCOPES == frozenset({"login", "line_exchange"})


# ──────────────────────────── 16. 既知の割り切り（v1）: 再送は受理される ────────────────────────────


class TestReplayWithinWindowIsAcceptedKnownV1Tradeoff:
    async def test_replaying_same_header_within_60s_is_counted_each_time(
        self, client_small_limits: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """既知の割り切り（v1）: 同一の中継ヘッダ値を60秒以内に再送すると、
        タイムスタンプ・署名とも有効なままのため何度でも中継IPとして採用・
        カウントされる（リプレイ対策を持たない）。理由と将来（v2）の対策
        （ノンス・リクエスト本文ハッシュを署名に加え1回限りにする）は
        ``app.core.client_ip_relay`` モジュール冒頭の docstring と
        ``docs/ops/admin-operations.md`` の「署名付き中継IPの鍵」節に記載する。
        ヘッダは TLS 内のみを流れどこにも記録しない前提のため実務上のリスクは
        小さいと判断した上での意図的な割り切りであり、この固定テストは将来
        v2 でノンスを導入した際にこの挙動が変わることを検知する回帰網も兼ねる。
        """
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        # 意図的に1回だけ作り、以降すべての送信で使い回す（再送そのものの検証のため）。
        replayed_headers = _relay_headers(_RELAY_KEY_A, ip="203.0.113.123")

        for i in range(SMALL_LOGIN_IP_MAX):
            email = f"relay-replay-{i}@example.com"
            await _create_user(db_session, email)
            r = await client_small_limits.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=replayed_headers,
            )
            assert r.status_code == 401

        await _create_user(db_session, "relay-replay-final@example.com")
        r_final = await client_small_limits.post(
            "/api/v1/auth/login",
            json={"email": "relay-replay-final@example.com", "password": "wrong-password"},
            headers=replayed_headers,  # 同じヘッダをもう一度再送
        )
        assert r_final.status_code == 429


# ──────────────────────────── 17. scope をまたいだ署名の使い回しは不採用（HTTP） ────────────────────────────


class TestSignedForOneScopeRejectedOnAnother:
    async def test_login_signed_header_sent_to_line_exchange_falls_back_to_hops(
        self, client_small_limits: AsyncClient, monkeypatch
    ) -> None:
        """/auth/login 向けに署名したヘッダをそのまま /auth/line/exchange に
        送っても、署名対象に含まれる PATH が一致しないため bad_signature で
        不採用になり、line_exchange は hops（XFFベース）で数えられる
        （``tests/test_client_ip_relay.py`` の単体テスト
        ``test_path_confusion_across_scopes`` と対になる HTTP 経由の固定）。"""
        settings = get_settings()
        monkeypatch.setattr(settings, "line_client_id", _TEST_LINE_CLIENT_ID)
        monkeypatch.setattr(settings, "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW))
        fixed_xff = {"X-Forwarded-For": "198.51.100.245"}

        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get()):
            for _ in range(SMALL_LINE_MAX):
                # /auth/login 用に署名したヘッダ（path が食い違うため bad_signature）。
                mismatched_headers = {
                    **fixed_xff,
                    **_relay_headers(
                        _RELAY_KEY_A, ip="203.0.113.130", path="/api/v1/auth/login"
                    ),
                }
                r = await client_small_limits.post(
                    "/api/v1/auth/line/exchange",
                    json={"line_access_token": "dummy-line-token"},
                    headers=mismatched_headers,
                )
                assert r.status_code == 200
            mismatched_headers_final = {
                **fixed_xff,
                **_relay_headers(_RELAY_KEY_A, ip="203.0.113.130", path="/api/v1/auth/login"),
            }
            r = await client_small_limits.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=mismatched_headers_final,
            )
            assert r.status_code == 429


# ──────────────────────────── 18. IPv6 の段と中継の結合（security review M-1） ────────────────────────────


class TestRelayIpv6TierIntegration:
    """署名付き中継の利用者IPがIPv6の場合も、hops方式と同じ /64・/56・/48 の
    3段（``rate_limit_deps._apply_ip_axis`` / ``_ip_axis_buckets``）で数えられる
    ことの結合テスト（security review M-1）。中継の検証本体
    （``verify_client_ip_relay``）はIPv6アドレスを正規化して返すのみで、
    段への分解は ``_apply_ip_axis`` に完全に委ねている（中継専用の別実装を
    持たない）ため、この委譲が壊れていないことを別途固定する。

    段の上限倍率は /64 が1倍（``_IPV6_TIERS`` 参照）のため、狭い段（/64）の
    上限は ``login_ip_max`` そのもの（``SMALL_LOGIN_IP_MAX``）で判定できる。
    """

    async def test_relay_two_different_ipv6_addresses_in_same_slash64_share_bucket(
        self, client_small_limits: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """(a) 中継で来た同じ /64 内の別々の IPv6 アドレス（要求ごとに違う値）
        でもバケットは共有され、失敗が合算されて login_ip_max（＝/64 の上限）
        で 429 になる（中継側だけ /64 集約が効かず要求ごとに新しいバケットが
        生成されるような分岐が紛れ込んでいないことの固定）。"""
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        for i in range(SMALL_LOGIN_IP_MAX):
            email = f"relay-ipv6-64-{i}@example.com"
            await _create_user(db_session, email)
            ip = f"2001:db8:1:1::{i + 1:x}"
            r = await client_small_limits.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=_relay_headers(_RELAY_KEY_A, ip=ip),
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-ipv6-64-final@example.com")
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={
                "email": "relay-ipv6-64-final@example.com",
                "password": "wrong-password",
            },
            headers=_relay_headers(_RELAY_KEY_A, ip="2001:db8:1:1::ff"),
        )
        assert r.status_code == 429

        # 同じ /48 内でも別の /64 からは影響を受けない（IPv4版
        # TestRelayCoreBehavior の「別IPなら成功」に相当する対照）。
        await _create_user(
            db_session, "relay-ipv6-64-other@example.com", password="correct-pass-v6-64"
        )
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={
                "email": "relay-ipv6-64-other@example.com",
                "password": "correct-pass-v6-64",
            },
            headers=_relay_headers(_RELAY_KEY_A, ip="2001:db8:1:2::1"),
        )
        assert r.status_code == 200

    async def test_relay_and_direct_hops_share_bucket_for_same_slash64(
        self, client_small_limits: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """(b) 同じ /64 の IPv6 について、直接アクセス（XFF）と中継で数えた分が
        1つのバケットに合算される（中継用と hops 用でバケット実体が別に
        分岐していないことの固定。IPv4 版の
        ``TestRelaySharesHopsBucketForSameIp`` に対応する）。"""
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        direct_count = SMALL_LOGIN_IP_MAX - 1
        for i in range(direct_count):
            email = f"relay-ipv6-shared-direct-{i}@example.com"
            await _create_user(db_session, email)
            r = await client_small_limits.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers={"X-Forwarded-For": f"2001:db8:1:9::{i + 1:x}"},
            )
            assert r.status_code == 401

        email_relayed = "relay-ipv6-shared-relayed-0@example.com"
        await _create_user(db_session, email_relayed)
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={"email": email_relayed, "password": "wrong-password"},
            headers=_relay_headers(_RELAY_KEY_A, ip=f"2001:db8:1:9::{direct_count + 1:x}"),
        )
        assert r.status_code == 401

        await _create_user(db_session, "relay-ipv6-shared-final@example.com")
        r = await client_small_limits.post(
            "/api/v1/auth/login",
            json={
                "email": "relay-ipv6-shared-final@example.com",
                "password": "wrong-password",
            },
            headers=_relay_headers(_RELAY_KEY_A, ip="2001:db8:1:9::ff"),
        )
        assert r.status_code == 429


# ──────────────────────────── 19. 鍵ありで中継ヘッダ無しの absent WARNING（HTTP 統合） ────────────────────────────


class TestAbsentWithKeysConfiguredEmitsWarningHttp:
    """鍵（CLIENT_IP_RELAY_SECRETS）が設定されているのに中継ヘッダの無い要求を
    実際に HTTP 経由で送ると、``log_relay_outcome`` の absent_with_keys WARNING
    （2回目 security review L-A）が実際に配線されて出ることを確かめる。

    ``tests/test_client_ip_relay.py`` の同名の単体テストは
    ``log_relay_outcome`` を直接呼ぶため、``rate_limit_deps._relayed_client_ip``
    の ``keys_configured=bool(keys)`` という配線（``get_settings()`` から鍵を
    読み出し・``bool(keys)`` を計算して渡す部分）自体が外れても検知できない。
    この HTTP 統合テストはその配線ごと固定する。
    """

    async def test_keys_configured_without_relay_header_emits_warning(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        await _create_user(db_session, "relay-absent-with-keys@example.com")
        with caplog.at_level(logging.WARNING, logger="app.core.client_ip_relay"):
            r = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "relay-absent-with-keys@example.com",
                    "password": "wrong-password",
                },
                headers={"X-Forwarded-For": "198.51.100.201"},
            )
        assert r.status_code == 401
        assert any(
            "鍵（CLIENT_IP_RELAY_SECRETS）が設定されているのに" in rec.getMessage()
            for rec in caplog.records
        )

    async def test_no_keys_configured_without_relay_header_emits_nothing(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch, caplog
    ) -> None:
        """鍵が1本も無い場合は同じ要求（XFF あり・中継ヘッダ無し）でも無音の
        まま（absent_with_keys WARNING は鍵が設定されている場合限定）。"""
        monkeypatch.setattr(get_settings(), "client_ip_relay_secrets", SecretStr(""))
        await _create_user(db_session, "relay-absent-no-keys@example.com")
        with caplog.at_level(logging.WARNING, logger="app.core.client_ip_relay"):
            r = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "relay-absent-no-keys@example.com",
                    "password": "wrong-password",
                },
                headers={"X-Forwarded-For": "198.51.100.202"},
            )
        assert r.status_code == 401
        assert not any(
            "鍵（CLIENT_IP_RELAY_SECRETS）が設定されているのに" in rec.getMessage()
            for rec in caplog.records
        )
