"""署名付き中継IP（``app.core.client_ip_relay``）の単体テスト（HTTP なし・DB なし）。

- ``parse_relay_secrets``: CLIENT_IP_RELAY_SECRETS のカンマ区切り解析・
  バリデーション・上限キャップ。
- 既知ベクトル（V1〜V3・否定ケース）: web 側テストと共有する固定値。
  ここで固定化することで、双方の実装が同じ署名を生成・検証できることを
  設計時点で相互に確認できる。
- ``verify_client_ip_relay``: 全 ``RelayReason`` の判定順序・境界値。
- ``log_relay_outcome``: ログ文言・スロットリング・初回 WARNING 格上げ。
"""

from __future__ import annotations

import logging

import pytest

from app.core.client_ip_relay import (
    RELAY_VERSION,
    SIGNING_CONTEXT,
    RelayVerification,
    _reset_relay_log_state_for_tests,
    build_relay_header_value,
    canonical_relay_message,
    compute_relay_signature,
    log_relay_outcome,
    parse_relay_secrets,
    verify_client_ip_relay,
)

_LOGGER_NAME = "app.core.client_ip_relay"

# ──────────────────────────── 共通の既知ベクトル（web 側と共有） ────────────────────────────
KEY_A = "katazuke-relay-test-vector-A-0123456789abcdefghijklmnopqrstuvwxyz"
KEY_B = "katazuke-relay-test-vector-B-0123456789abcdefghijklmnopqrstuvwxyz"

_VALID_METHOD = "POST"
_VALID_PATH = "/api/v1/auth/login"
_VALID_TS = 1790000000
_VALID_IP = "203.0.113.9"
_VALID_KEY = KEY_A.encode("ascii")


def _valid_header() -> str:
    return build_relay_header_value(
        _VALID_KEY, method=_VALID_METHOD, path=_VALID_PATH, timestamp=_VALID_TS, ip=_VALID_IP
    )


def _verify(
    header_value: str | None,
    *,
    method: str = _VALID_METHOD,
    path: str = _VALID_PATH,
    now: int = _VALID_TS,
    keys: tuple[bytes, ...] = (_VALID_KEY,),
) -> RelayVerification:
    header_values: list[str] = [] if header_value is None else [header_value]
    return verify_client_ip_relay(
        header_values=header_values, method=method, path=path, now_epoch_seconds=now, keys=keys
    )


@pytest.fixture(autouse=True)
def _reset_log_state():
    """各テストの前後でプロセス内ログ状態（初回済みscope集合・スロットラ）を初期化する。"""
    _reset_relay_log_state_for_tests()
    yield
    _reset_relay_log_state_for_tests()


# ──────────────────────────── parse_relay_secrets ────────────────────────────


class TestParseRelaySecrets:
    def test_empty_blank_and_comma_only_return_empty_tuple(self) -> None:
        assert parse_relay_secrets("") == ()
        assert parse_relay_secrets("   ") == ()
        assert parse_relay_secrets(",,,") == ()
        assert parse_relay_secrets(" , , ") == ()

    def test_single_key(self) -> None:
        assert parse_relay_secrets(KEY_A) == (KEY_A.encode("ascii"),)

    def test_two_keys_preserve_order_and_strip_whitespace(self) -> None:
        result = parse_relay_secrets(f"  {KEY_A}  ,  {KEY_B}  ")
        assert result == (KEY_A.encode("ascii"), KEY_B.encode("ascii"))

    def test_short_key_excluded_with_error_log_without_value_or_length(self, caplog) -> None:
        parse_relay_secrets.cache_clear()
        short_key = "a" * 31
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            result = parse_relay_secrets(short_key)
        assert result == ()
        # 除外ログ（値・長さ非開示）＋ 有効鍵0本のため無効化ログの計2件。
        assert len(caplog.records) == 2
        for record in caplog.records:
            message = record.getMessage()
            assert short_key not in message
            assert "31" not in message

    def test_non_ascii_key_excluded_with_error_log(self, caplog) -> None:
        parse_relay_secrets.cache_clear()
        non_ascii_key = "あ" * 32
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            result = parse_relay_secrets(non_ascii_key)
        assert result == ()
        assert len(caplog.records) == 2
        for record in caplog.records:
            assert non_ascii_key not in record.getMessage()

    def test_key_with_internal_whitespace_excluded_with_error_log(self, caplog) -> None:
        parse_relay_secrets.cache_clear()
        key_with_space = "a" * 20 + " " + "a" * 20
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            result = parse_relay_secrets(key_with_space)
        assert result == ()
        assert len(caplog.records) == 2
        for record in caplog.records:
            assert key_with_space not in record.getMessage()

    def test_duplicate_keys_are_deduplicated_preserving_order(self) -> None:
        result = parse_relay_secrets(f"{KEY_A},{KEY_B},{KEY_A}")
        assert result == (KEY_A.encode("ascii"), KEY_B.encode("ascii"))

    def test_five_keys_capped_to_four_with_error_log(self, caplog) -> None:
        parse_relay_secrets.cache_clear()
        keys = [f"key-{i:02d}-" + "x" * 60 for i in range(5)]
        raw = ",".join(keys)
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            result = parse_relay_secrets(raw)
        assert len(result) == 4
        assert result == tuple(k.encode("ascii") for k in keys[:4])
        assert any("上限" in r.getMessage() for r in caplog.records)

    def test_all_invalid_returns_empty_with_disable_error_log(self, caplog) -> None:
        parse_relay_secrets.cache_clear()
        raw = "short1,short2"
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            result = parse_relay_secrets(raw)
        assert result == ()
        messages = [r.getMessage() for r in caplog.records]
        assert any("無効化" in m for m in messages)


# ──────────────────────────── 既知ベクトル（V1〜V3・否定ケース） ────────────────────────────


class TestKnownVectors:
    def test_v1_message_signature_header_value_and_verify_ok(self) -> None:
        ts = "1790000000"
        ip = "203.0.113.9"
        message = canonical_relay_message(
            method="POST", path="/api/v1/auth/login", timestamp=ts, ip=ip
        )
        assert message == "\n".join((SIGNING_CONTEXT, "POST", "/api/v1/auth/login", ts, ip))

        sig = compute_relay_signature(
            KEY_A.encode("ascii"),
            method="POST",
            path="/api/v1/auth/login",
            timestamp=ts,
            ip=ip,
        )
        assert sig == "db454b34038592236a42de40f8976210cb44ebac8f44f9c8e973664636f1bbb6"

        header_value = build_relay_header_value(
            KEY_A.encode("ascii"),
            method="POST",
            path="/api/v1/auth/login",
            timestamp=1790000000,
            ip=ip,
        )
        assert header_value == f"v1;{ts};{ip};{sig}"

        result = verify_client_ip_relay(
            header_values=[header_value],
            method="POST",
            path="/api/v1/auth/login",
            now_epoch_seconds=1790000030,
            keys=(KEY_A.encode("ascii"),),
        )
        assert result == RelayVerification("203.0.113.9", "ok", key_slot=0, skew_seconds=30)

    def test_v2_ipv6_uppercase_signed_and_normalized_on_verify(self) -> None:
        ts = "1790000123"
        ip = "2001:DB8:85A3::8A2E:370:7334"
        sig = compute_relay_signature(
            KEY_B.encode("ascii"),
            method="POST",
            path="/api/v1/auth/line/exchange",
            timestamp=ts,
            ip=ip,
        )
        assert sig == "965799a5a9624f69e0d6de412169154e433f308bed94c5e001faeacc12df34b0"

        header_value = f"v1;{ts};{ip};{sig}"
        result = verify_client_ip_relay(
            header_values=[header_value],
            method="POST",
            path="/api/v1/auth/line/exchange",
            now_epoch_seconds=1790000123,
            keys=(KEY_A.encode("ascii"), KEY_B.encode("ascii")),
        )
        assert result.reason == "ok"
        assert result.ip == "2001:db8:85a3::8a2e:370:7334"
        assert result.key_slot == 1
        assert result.skew_seconds == 0

    def test_v3_ipv4_mapped_unwrapped_and_negative_skew(self) -> None:
        ts = "1790000059"
        ip = "::ffff:198.51.100.7"
        sig = compute_relay_signature(
            KEY_A.encode("ascii"),
            method="POST",
            path="/api/v1/auth/operator/login",
            timestamp=ts,
            ip=ip,
        )
        assert sig == "1f5c5681d5a2755ca5fce1f5c5441177ac956cfd0d9a9e547a9c28a9f8c07900"

        header_value = f"v1;{ts};{ip};{sig}"
        result = verify_client_ip_relay(
            header_values=[header_value],
            method="POST",
            path="/api/v1/auth/operator/login",
            now_epoch_seconds=1790000000,
            keys=(KEY_A.encode("ascii"),),
        )
        assert result.reason == "ok"
        assert result.ip == "198.51.100.7"
        assert result.skew_seconds == -59

    def test_negation_wrong_key_and_wrong_method_signatures_differ_from_v1(self) -> None:
        ts = "1790000000"
        ip = "203.0.113.9"
        sig_wrong_key = compute_relay_signature(
            KEY_B.encode("ascii"), method="POST", path="/api/v1/auth/login", timestamp=ts, ip=ip
        )
        assert sig_wrong_key == "329be44aab4c5b91e92246585f15d4e8f7b000f6e6b6d37a3677f9d8d35dc305"

        sig_wrong_method = compute_relay_signature(
            KEY_A.encode("ascii"), method="GET", path="/api/v1/auth/login", timestamp=ts, ip=ip
        )
        assert sig_wrong_method == "0216106b3f8b6cb4fcbd5403e633cdff4ef56bc000ba350e9d65dd3dbaca3a27"

        v1_sig = "db454b34038592236a42de40f8976210cb44ebac8f44f9c8e973664636f1bbb6"
        assert sig_wrong_key != v1_sig
        assert sig_wrong_method != v1_sig


# ──────────────────────────── verify_client_ip_relay: absent/unconfigured ────────────────────────────


class TestVerifyAbsentAndUnconfigured:
    def test_absent_regardless_of_keys(self) -> None:
        assert _verify(None, keys=()).reason == "absent"
        assert _verify(None, keys=(_VALID_KEY,)).reason == "absent"

    def test_unconfigured_when_header_present_but_no_keys(self) -> None:
        result = _verify(_valid_header(), keys=())
        assert result.reason == "unconfigured"
        assert result.ip is None


# ──────────────────────────── verify_client_ip_relay: malformed ────────────────────────────


class TestVerifyMalformed:
    def test_duplicate_header_lines(self) -> None:
        header_value = _valid_header()
        result = verify_client_ip_relay(
            header_values=[header_value, header_value],
            method=_VALID_METHOD,
            path=_VALID_PATH,
            now_epoch_seconds=_VALID_TS,
            keys=(_VALID_KEY,),
        )
        assert result.reason == "malformed"

    def test_header_containing_comma_is_malformed(self) -> None:
        result = _verify("v1;1790000000;203.0.113.9,extra;" + "a" * 64)
        assert result.reason == "malformed"

    def test_header_too_long(self) -> None:
        assert _verify("a" * 129).reason == "malformed"

    def test_field_count_three(self) -> None:
        assert _verify("v1;1790000000;203.0.113.9").reason == "malformed"

    def test_field_count_five(self) -> None:
        assert _verify("v1;1790000000;203.0.113.9;" + "a" * 64 + ";extra").reason == "malformed"

    @pytest.mark.parametrize("bad_ts", ["179000000", "17900000000", "-790000000"])
    def test_timestamp_digit_count(self, bad_ts: str) -> None:
        sig = compute_relay_signature(
            _VALID_KEY, method=_VALID_METHOD, path=_VALID_PATH, timestamp=bad_ts, ip=_VALID_IP
        )
        result = _verify(f"v1;{bad_ts};{_VALID_IP};{sig}")
        assert result.reason == "malformed"

    @pytest.mark.parametrize("bad_ip", ["1.2.3.4 ", "[::1]", "fe80::1%eth0"])
    def test_ip_charset_rejected_before_ip_parsing(self, bad_ip: str) -> None:
        sig = compute_relay_signature(
            _VALID_KEY, method=_VALID_METHOD, path=_VALID_PATH, timestamp=str(_VALID_TS), ip=bad_ip
        )
        result = _verify(f"v1;{_VALID_TS};{bad_ip};{sig}")
        assert result.reason == "malformed"

    def test_uppercase_signature_hex_is_malformed(self) -> None:
        header_value = _valid_header()
        parts = header_value.split(";")
        parts[3] = parts[3].upper()
        assert _verify(";".join(parts)).reason == "malformed"

    def test_63_digit_signature_is_malformed(self) -> None:
        header_value = _valid_header()
        parts = header_value.split(";")
        parts[3] = parts[3][:-1]
        assert _verify(";".join(parts)).reason == "malformed"

    def test_uppercase_version_prefix_is_malformed(self) -> None:
        header_value = _valid_header()
        assert _verify("V1" + header_value[2:]).reason == "malformed"

    def test_path_with_disallowed_characters_is_malformed(self) -> None:
        bad_path = "/api/v1/auth/login?x=1"
        sig = compute_relay_signature(
            _VALID_KEY, method=_VALID_METHOD, path=bad_path, timestamp=str(_VALID_TS), ip=_VALID_IP
        )
        header_value = f"v1;{_VALID_TS};{_VALID_IP};{sig}"
        result = _verify(header_value, path=bad_path)
        assert result.reason == "malformed"

    def test_invalid_method_is_malformed(self) -> None:
        bad_method = "P0ST"
        sig = compute_relay_signature(
            _VALID_KEY, method=bad_method, path=_VALID_PATH, timestamp=str(_VALID_TS), ip=_VALID_IP
        )
        header_value = f"v1;{_VALID_TS};{_VALID_IP};{sig}"
        result = _verify(header_value, method=bad_method)
        assert result.reason == "malformed"


# ──────────────────────────── verify_client_ip_relay: unsupported_version ────────────────────────────


class TestVerifyUnsupportedVersion:
    def test_v2_prefix_is_unsupported_version(self) -> None:
        sig = compute_relay_signature(
            _VALID_KEY, method=_VALID_METHOD, path=_VALID_PATH, timestamp=str(_VALID_TS), ip=_VALID_IP
        )
        result = _verify(f"v2;{_VALID_TS};{_VALID_IP};{sig}")
        assert result.reason == "unsupported_version"
        assert result.ip is None


# ──────────────────────────── verify_client_ip_relay: bad_signature ────────────────────────────


class TestVerifyBadSignature:
    def test_one_bit_flip_in_signature(self) -> None:
        header_value = _valid_header()
        last_char = header_value[-1]
        replacement = "0" if last_char != "0" else "1"
        flipped = header_value[:-1] + replacement
        assert _verify(flipped).reason == "bad_signature"

    def test_wrong_key(self) -> None:
        header_value = build_relay_header_value(
            KEY_B.encode("ascii"),
            method=_VALID_METHOD,
            path=_VALID_PATH,
            timestamp=_VALID_TS,
            ip=_VALID_IP,
        )
        assert _verify(header_value).reason == "bad_signature"

    def test_method_mismatch_post_signed_get_sent(self) -> None:
        header_value = _valid_header()
        result = _verify(header_value, method="GET")
        assert result.reason == "bad_signature"

    @pytest.mark.parametrize(
        "signed_path,actual_path",
        [
            ("/api/v1/auth/login", "/api/v1/auth/operator/login"),
            ("/api/v1/auth/operator/login", "/api/v1/auth/line/exchange"),
            ("/api/v1/auth/line/exchange", "/api/v1/auth/login"),
        ],
    )
    def test_path_confusion_across_scopes(self, signed_path: str, actual_path: str) -> None:
        header_value = build_relay_header_value(
            _VALID_KEY, method=_VALID_METHOD, path=signed_path, timestamp=_VALID_TS, ip=_VALID_IP
        )
        result = _verify(header_value, path=actual_path)
        assert result.reason == "bad_signature"

    def test_ip_field_tampering(self) -> None:
        header_value = _valid_header()
        parts = header_value.split(";")
        parts[2] = "203.0.113.99"
        assert _verify(";".join(parts)).reason == "bad_signature"

    def test_timestamp_field_tampering(self) -> None:
        header_value = _valid_header()
        parts = header_value.split(";")
        parts[1] = "1790000001"
        assert _verify(";".join(parts)).reason == "bad_signature"

    def test_forged_and_expired_returns_bad_signature_not_expired(self) -> None:
        """判定順序の固定: 署名照合が時刻チェックより先のため、偽物かつ
        期限切れでも "bad_signature" になる（"expired" にはならない）。"""
        header_value = build_relay_header_value(
            KEY_B.encode("ascii"),
            method=_VALID_METHOD,
            path=_VALID_PATH,
            timestamp=_VALID_TS,
            ip=_VALID_IP,
        )
        result = _verify(header_value, now=_VALID_TS + 10_000, keys=(_VALID_KEY,))
        assert result.reason == "bad_signature"


# ──────────────────────────── verify_client_ip_relay: 時刻境界（expired） ────────────────────────────


class TestVerifyClockSkewBoundary:
    @pytest.mark.parametrize(
        "delta,expected_reason", [(60, "ok"), (61, "expired"), (-60, "ok"), (-61, "expired")]
    )
    def test_clock_skew_boundary(self, delta: int, expected_reason: str) -> None:
        header_value = _valid_header()
        result = _verify(header_value, now=_VALID_TS + delta)
        assert result.reason == expected_reason
        if expected_reason == "expired":
            assert result.key_slot == 0
            assert result.skew_seconds == delta


# ──────────────────────────── verify_client_ip_relay: ip_unparseable ────────────────────────────


class TestVerifyIpUnparseable:
    @pytest.mark.parametrize("bad_ip", ["1.2.3", "01.2.3.4", "1.2.3.4:80"])
    def test_ip_unparseable(self, bad_ip: str) -> None:
        header_value = build_relay_header_value(
            _VALID_KEY, method=_VALID_METHOD, path=_VALID_PATH, timestamp=_VALID_TS, ip=bad_ip
        )
        result = _verify(header_value)
        assert result.reason == "ip_unparseable"
        assert result.ip is None


# ──────────────────────────── verify_client_ip_relay: ip_not_public ────────────────────────────


class TestVerifyIpNotPublic:
    @pytest.mark.parametrize(
        "private_ip",
        [
            "10.0.0.1",
            "172.16.0.1",
            "192.168.0.1",
            "100.64.0.1",
            "169.254.0.1",
            "127.0.0.1",
            "::1",
            "fc00::1",
            "fe80::1",
            "0.0.0.0",
            "::",
            "224.0.0.1",
            "240.0.0.1",
            "::ffff:10.0.0.1",
        ],
    )
    def test_ip_not_public(self, private_ip: str) -> None:
        header_value = build_relay_header_value(
            _VALID_KEY, method=_VALID_METHOD, path=_VALID_PATH, timestamp=_VALID_TS, ip=private_ip
        )
        result = _verify(header_value)
        assert result.reason == "ip_not_public"
        assert result.ip is None
        assert result.rejected_ip_net is not None


# ──────────────────────────── verify_client_ip_relay: ok の追加ケース ────────────────────────────


class TestVerifyOk:
    def test_cloudflare_range_ip_is_ok_not_special_cased(self) -> None:
        """中継の検証は CFレンジを特別扱いしない（署名検証済みの中継IPを
        そのまま信頼するため）。hops 方式側の CFレンジ WARNING とは無関係。"""
        header_value = build_relay_header_value(
            _VALID_KEY, method=_VALID_METHOD, path=_VALID_PATH, timestamp=_VALID_TS, ip="172.68.10.20"
        )
        result = _verify(header_value)
        assert result.reason == "ok"
        assert result.ip == "172.68.10.20"


# ──────────────────────────── log_relay_outcome ────────────────────────────


class TestLogRelayOutcome:
    def test_ok_first_time_warning_then_info_scopes_independent(self, caplog) -> None:
        v = RelayVerification("203.0.113.9", "ok", key_slot=0, skew_seconds=5)
        with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)
            log_relay_outcome("login", v)
            log_relay_outcome("line_exchange", v)
        records = caplog.records
        assert len(records) == 3
        assert records[0].levelname == "WARNING"
        assert records[1].levelname == "INFO"
        assert records[2].levelname == "WARNING"  # line_exchange は独立して初回扱い
        for record in records:
            message = record.getMessage()
            assert "203.0.113.9" not in message
            assert "key_slot=" in message
        assert "/24" in records[0].getMessage()

    def test_ok_second_time_same_scope_is_info_and_throttled(self, caplog) -> None:
        v = RelayVerification("203.0.113.9", "ok", key_slot=0, skew_seconds=5)
        with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)  # 初回 WARNING
            log_relay_outcome("login", v)  # 2回目 INFO
            log_relay_outcome("login", v)  # スロットリングされ無出力
        assert len(caplog.records) == 2

    def test_unconfigured_warning_throttled_to_once(self, caplog) -> None:
        v = RelayVerification(None, "unconfigured")
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)
            log_relay_outcome("login", v)
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"

    def test_bad_signature_warning_throttled_to_once(self, caplog) -> None:
        v = RelayVerification(None, "bad_signature")
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)
            log_relay_outcome("login", v)
        assert len(caplog.records) == 1
        assert "鍵の食い違い" in caplog.records[0].getMessage() or "偽造" in caplog.records[0].getMessage()

    def test_expired_warning_includes_skew_sec_and_throttled(self, caplog) -> None:
        v = RelayVerification(None, "expired", key_slot=0, skew_seconds=75)
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)
            log_relay_outcome("login", v)
        assert len(caplog.records) == 1
        assert "skew_sec=75" in caplog.records[0].getMessage()

    def test_ip_not_public_warning_contains_rounded_net_only(self, caplog) -> None:
        v = RelayVerification(
            None, "ip_not_public", key_slot=0, skew_seconds=0, rejected_ip_net="10.0.0.0/24"
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "10.0.0.0/24" in message
        assert "10.0.0.1" not in message

    def test_malformed_and_ip_unparseable_do_not_record_values(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_relay_outcome("login", RelayVerification(None, "malformed"))
            log_relay_outcome("login", RelayVerification(None, "ip_unparseable"))
        assert len(caplog.records) == 2
        for record in caplog.records:
            assert "値は記録しません" in record.getMessage()

    def test_absent_emits_nothing(self, caplog) -> None:
        v = RelayVerification(None, "absent")
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)
        assert len(caplog.records) == 0

    def test_reason_throttles_are_independent_per_reason(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_relay_outcome("login", RelayVerification(None, "unconfigured"))
            log_relay_outcome("login", RelayVerification(None, "bad_signature"))
        # unconfigured と bad_signature は独立したスロットリングのため両方出る。
        assert len(caplog.records) == 2

    def test_reason_throttles_are_independent_per_scope(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            log_relay_outcome("login", RelayVerification(None, "unconfigured"))
            log_relay_outcome("line_exchange", RelayVerification(None, "unconfigured"))
        # 同じ reason でも scope が異なれば独立してスロットリングされる。
        assert len(caplog.records) == 2

    def test_header_value_signature_and_key_never_logged(self, caplog) -> None:
        header_value = _valid_header()
        v = _verify(header_value)
        assert v.reason == "ok"
        with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
            log_relay_outcome("login", v)
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert header_value not in message
        assert KEY_A not in message
        assert "203.0.113.9" not in message
