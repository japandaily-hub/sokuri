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
import time
from unittest.mock import patch

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.client_ip_relay import (
    RELAY_HEADER_NAME,
    build_relay_header_value,
    compute_relay_signature,
    parse_relay_secrets,
)
from tests.test_rate_limit_api import (  # noqa: F401 -- フィクスチャ再エクスポート
    _TEST_LINE_CLIENT_ID,
    _TEST_PUBLIC_IP_HEADERS,
    _create_operator,
    _create_user,
    _mock_line_get,
    _signup_user,
    client,
    client_killswitch,
    fake_clock,
)

# ──────────────────────────── 中継用の鍵（HTTP統合テスト専用・固定ベクトルとは別） ────────────────────────────
_RELAY_KEY_A_RAW = "http-relay-test-key-A-" + "1" * 20
_RELAY_KEY_B_RAW = "http-relay-test-key-B-" + "2" * 20
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
def _clear_relay_secrets_cache():
    """テスト間で ``parse_relay_secrets`` のキャッシュが干渉しないようにする。

    ``@lru_cache`` は引数の生文字列自体をキーにするため、テストごとに異なる
    鍵文字列を使えば本来は不要だが、明示的に毎回クリアすることで「前のテストの
    キャッシュが残っていないか」を気にせず書けるようにする。
    """
    parse_relay_secrets.cache_clear()
    yield
    parse_relay_secrets.cache_clear()


# ──────────────────────────── 1. 核心の回帰 ────────────────────────────


class TestRelayCoreBehavior:
    async def test_relay_ip_a_blocks_after_20_then_ip_b_succeeds(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        # 同じ XFF（Vercel 相当の固定送信元）でも、中継ヘッダの利用者IPで数える。
        vercel_xff = {"X-Forwarded-For": "198.51.100.200"}
        headers = {**vercel_xff, **_relay_headers(_RELAY_KEY_A, ip="203.0.113.50")}
        for i in range(20):
            email = f"relay-core-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-core-final@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-core-final@example.com", "password": "wrong-password"},
            headers=headers,
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
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )
        relay_ip = "203.0.113.70"
        for i in range(20):
            email = f"relay-nopollute-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=_relay_headers(_RELAY_KEY_A, ip=relay_ip),
            )
            assert r.status_code == 401
        await _create_user(
            db_session, "relay-nopollute-direct@example.com", password="correct-pass-np1"
        )
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
    async def test_fallback_to_hops_after_20(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
        header_builder,
        ip_kind: str,
    ) -> None:
        monkeypatch.setattr(
            get_settings(), "client_ip_relay_secrets", SecretStr(_RELAY_KEY_A_RAW)
        )

        def _ip_for(i: int) -> str:
            return f"10.9.{i}.1" if ip_kind == "private" else f"203.0.113.{i}"

        case_id = header_builder.__name__
        for i in range(20):
            email = f"relay-fb-{case_id}-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=header_builder(_ip_for(i)),
            )
            assert r.status_code == 401

        await _create_user(db_session, f"relay-fb-{case_id}-final@example.com")
        r = await client.post(
            "/api/v1/auth/login",
            json={
                "email": f"relay-fb-{case_id}-final@example.com",
                "password": "wrong-password",
            },
            headers=header_builder(_ip_for(99)),
        )
        assert r.status_code == 429

    async def test_duplicate_relay_header_falls_back_to_hops(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        """重複した中継ヘッダ（malformed）でも hops へフォールバックする。

        httpx の ``headers`` はリスト形式で重複キーを送れる（辞書だと後勝ちで
        1本に潰れてしまうため、この検証にはリスト形式が必須）。
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

        for i in range(20):
            email = f"relay-fb-dup-{i}@example.com"
            await _create_user(db_session, email)
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=_dup_headers(f"203.0.113.{i}"),
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-fb-dup-final@example.com")
        r = await client.post(
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
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ) -> None:
        settings = get_settings()
        monkeypatch.setattr(
            settings,
            "client_ip_relay_secrets",
            SecretStr(f"{_RELAY_KEY_A_RAW},{_RELAY_KEY_B_RAW}"),
        )
        await _create_user(
            db_session, "relay-rotate-a@example.com", password="correct-pass-rot1"
        )
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-rotate-a@example.com", "password": "correct-pass-rot1"},
            headers=_relay_headers(_RELAY_KEY_A, ip="203.0.113.80"),
        )
        assert r.status_code == 200

        await _create_user(
            db_session, "relay-rotate-b@example.com", password="correct-pass-rot2"
        )
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "relay-rotate-b@example.com", "password": "correct-pass-rot2"},
            headers=_relay_headers(_RELAY_KEY_B, ip="203.0.113.81"),
        )
        assert r.status_code == 200

        # B のみに切り替えると、A の署名は不採用になり hops へフォールバックする。
        monkeypatch.setattr(settings, "client_ip_relay_secrets", SecretStr(_RELAY_KEY_B_RAW))
        fixed_xff = {"X-Forwarded-For": "198.51.100.230"}
        for i in range(20):
            email = f"relay-rotate-afterB-{i}@example.com"
            await _create_user(db_session, email)
            headers = {
                **fixed_xff,
                **_relay_headers(_RELAY_KEY_A, ip=f"203.0.113.{160 + i}"),
            }
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_user(db_session, "relay-rotate-afterB-final@example.com")
        headers_final = {**fixed_xff, **_relay_headers(_RELAY_KEY_A, ip="203.0.113.199")}
        r = await client.post(
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
        headers_a = _relay_headers(
            _RELAY_KEY_A, ip="203.0.113.90", path="/api/v1/auth/line/exchange"
        )
        with patch.object(httpx.AsyncClient, "get", new=_mock_line_get()):
            for _ in range(20):
                r = await client.post(
                    "/api/v1/auth/line/exchange",
                    json={"line_access_token": "dummy-line-token"},
                    headers=headers_a,
                )
                assert r.status_code == 200
            r = await client.post(
                "/api/v1/auth/line/exchange",
                json={"line_access_token": "dummy-line-token"},
                headers=headers_a,
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
        headers = _relay_headers(
            _RELAY_KEY_A, ip="203.0.113.95", path="/api/v1/auth/operator/login"
        )
        for i in range(20):
            email = f"relay-op-{i}@example.com"
            await _create_operator(db_session, email)
            r = await client.post(
                "/api/v1/auth/operator/login",
                json={"email": email, "password": "wrong-password"},
                headers=headers,
            )
            assert r.status_code == 401
        await _create_operator(db_session, "relay-op-final@example.com")
        r = await client.post(
            "/api/v1/auth/operator/login",
            json={"email": "relay-op-final@example.com", "password": "wrong-password"},
            headers=headers,
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
        with caplog.at_level(logging.INFO, logger="app.core.client_ip_relay"):
            for _ in range(100):
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
