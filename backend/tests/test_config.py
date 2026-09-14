"""``app.config.Settings.allowed_origins`` の正規化ロジックの単体テスト。

``Settings(_env_file=None, ...)`` で backend/.env の読み込みを遮断し、
実行環境の環境変数や .env ファイルに依存せず純粋にコンストラクタ引数のみで検証する。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_allowed_origins_falls_back_when_unset():
    """ALLOWED_ORIGINS 未設定時は frontend_base_url + localhost 群にフォールバックする。"""
    settings = Settings(_env_file=None, frontend_base_url="https://example.com")
    assert settings.allowed_origins == [
        "https://example.com",
        "http://localhost:3000",
        "http://localhost:3100",
    ]


def test_allowed_origins_falls_back_when_blank():
    """ALLOWED_ORIGINS が空白のみの場合も未設定と同様にフォールバックする。"""
    settings = Settings(
        _env_file=None,
        frontend_base_url="https://example.com",
        ALLOWED_ORIGINS="   ",
    )
    assert settings.allowed_origins == [
        "https://example.com",
        "http://localhost:3000",
        "http://localhost:3100",
    ]


def test_allowed_origins_parses_comma_separated_preserving_order():
    """カンマ区切り複数値は順序を維持して返す。"""
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="https://a.example.com,https://b.example.com,https://c.example.com",
    )
    assert settings.allowed_origins == [
        "https://a.example.com",
        "https://b.example.com",
        "https://c.example.com",
    ]


def test_allowed_origins_deduplicates():
    """重複するオリジンは1件に集約される。"""
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="https://a.example.com,https://a.example.com,https://b.example.com",
    )
    assert settings.allowed_origins == ["https://a.example.com", "https://b.example.com"]


def test_allowed_origins_trims_whitespace():
    """各値の前後空白は trim される。"""
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="  https://a.example.com  , https://b.example.com ",
    )
    assert settings.allowed_origins == ["https://a.example.com", "https://b.example.com"]


def test_allowed_origins_strips_trailing_slash():
    """末尾スラッシュは除去される（CORS判定の不一致による全滅事故を予防）。"""
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="https://a.example.com/,https://b.example.com//",
    )
    assert settings.allowed_origins == ["https://a.example.com", "https://b.example.com"]


def test_allowed_origins_excludes_wildcard_and_falls_back():
    """"*" のみが指定された場合は fail-open を避けるため除外し、フォールバックへ倒す。"""
    settings = Settings(
        _env_file=None,
        frontend_base_url="https://example.com",
        ALLOWED_ORIGINS="*",
    )
    assert settings.allowed_origins == [
        "https://example.com",
        "http://localhost:3000",
        "http://localhost:3100",
    ]


def test_allowed_origins_excludes_wildcard_with_surrounding_whitespace():
    """前後空白付きの "  *  " も除外され、フォールバックへ倒す。"""
    settings = Settings(
        _env_file=None,
        frontend_base_url="https://example.com",
        ALLOWED_ORIGINS="  *  ",
    )
    assert settings.allowed_origins == [
        "https://example.com",
        "http://localhost:3000",
        "http://localhost:3100",
    ]


def test_allowed_origins_excludes_wildcard_subdomain_and_null_keeping_valid_entries():
    """ワイルドカードサブドメイン（"*" 含有）と "null" は除外され、正規オリジンのみ残る。"""
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="https://*.evil.com,null,https://ok.example.com",
    )
    assert settings.allowed_origins == ["https://ok.example.com"]


def test_allowed_origins_production_unset_returns_frontend_base_url_only():
    """production かつ ALLOWED_ORIGINS 未設定時は frontend_base_url のみ（localhost は含まない）。"""
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        frontend_base_url="https://sokuri.vercel.app",
    )
    assert settings.allowed_origins == ["https://sokuri.vercel.app"]


# ──────────────────────────── ストレージ（R2 移行） ────────────────────────────


def _r2_creds() -> dict[str, str]:
    return {
        "r2_access_key_id": "AKIAEXAMPLE",
        "r2_secret_access_key": "secret-value",
        "r2_bucket": "katadzuke-photos",
        "r2_account_id": "0123456789abcdef0123456789abcdef",
    }


def test_resolved_storage_backend_auto_without_r2_credentials_is_local():
    """R2 認証情報が一切無い状態では、STORAGE_BACKEND=auto（既定）は必ず local になる。

    ``storage_backend`` は明示的に "auto" を渡す（tests/conftest.py がプロセス
    全体で ``STORAGE_BACKEND=local`` を環境変数にセットしているため、
    コンストラクタ引数を省略すると "auto" 既定値の検証にならない）。
    """
    settings = Settings(_env_file=None, storage_backend="auto")
    assert settings.storage_backend == "auto"
    assert settings.r2_configured is False
    assert settings.resolved_storage_backend == "local"


def test_resolved_storage_backend_auto_with_full_r2_credentials_is_r2():
    settings = Settings(_env_file=None, storage_backend="auto", **_r2_creds())
    assert settings.r2_configured is True
    assert settings.resolved_storage_backend == "r2"


@pytest.mark.parametrize(
    "missing_field",
    ["r2_access_key_id", "r2_secret_access_key", "r2_bucket"],
)
def test_resolved_storage_backend_auto_falls_back_to_local_if_any_required_field_missing(
    missing_field: str,
):
    """r2_account_id/endpoint 以外のいずれか1つでも欠けていれば local にフォールバックする。"""
    creds = _r2_creds()
    creds[missing_field] = ""
    settings = Settings(_env_file=None, storage_backend="auto", **creds)
    assert settings.r2_configured is False
    assert settings.resolved_storage_backend == "local"


def test_resolved_storage_backend_explicit_local_overrides_r2_credentials():
    """STORAGE_BACKEND=local を明示指定した場合、R2 認証情報が揃っていても local を使う。"""
    settings = Settings(_env_file=None, storage_backend="local", **_r2_creds())
    assert settings.resolved_storage_backend == "local"


def test_resolved_storage_backend_explicit_r2_without_credentials_is_still_r2():
    """STORAGE_BACKEND=r2 を明示指定した場合、認証情報の有無に関わらず r2 を返す
    （実際の呼び出し時に失敗するのは R2Backend 側の責務。設定解決自体は素直に従う）。"""
    settings = Settings(_env_file=None, storage_backend="r2")
    assert settings.resolved_storage_backend == "r2"


def test_invalid_storage_backend_raises_validation_error():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_backend="s3")


def test_r2_key_prefix_strips_leading_slash_and_adds_trailing_slash():
    settings = Settings(_env_file=None, r2_key_prefix="case-photos")
    assert settings.r2_key_prefix == "case-photos/"

    settings = Settings(_env_file=None, r2_key_prefix="/case-photos/")
    assert settings.r2_key_prefix == "case-photos/"


def test_r2_key_prefix_empty_stays_empty():
    settings = Settings(_env_file=None, r2_key_prefix="")
    assert settings.r2_key_prefix == ""


def test_r2_key_prefix_rejects_path_traversal():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, r2_key_prefix="../etc")


def test_r2_endpoint_url_derived_from_account_id_when_unset():
    settings = Settings(_env_file=None, r2_account_id="myaccount")
    assert settings.r2_endpoint_url == "https://myaccount.r2.cloudflarestorage.com"


def test_r2_endpoint_url_requires_https_when_explicit():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, r2_endpoint_url="http://insecure.example.com")


def test_storage_max_concurrent_reads_out_of_range_raises():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_max_concurrent_reads=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_max_concurrent_reads=65)


def test_r2_secret_access_key_repr_does_not_leak_plaintext():
    """SecretStr の repr は平文を出さない（ログ・例外メッセージへの意図しない混入対策）。"""
    settings = Settings(_env_file=None, r2_secret_access_key="super-secret-value")
    assert "super-secret-value" not in repr(settings.r2_secret_access_key)
    assert "super-secret-value" not in str(settings.r2_secret_access_key)
    assert settings.r2_secret_access_key.get_secret_value() == "super-secret-value"


def test_config_readiness_storage_r2_is_false_when_backend_r2_without_credentials():
    """security/qa review 指摘対応: ``_config_readiness`` の既存テスト

    （test_admin_notifications_r6.py の ``test_config_readiness_flags_are_bool_only``）は
    ``storage_r2`` キーの**存在**と型（bool）しか検証しておらず、値そのものの
    真偽は未検証だった。STORAGE_BACKEND=r2 を明示指定したにも関わらず R2
    認証情報が空（``r2_configured`` が False）の場合、readyz が Warning を
    出さず本番写真配信の恒久 503 を見逃す事故になり得るため、値まで固定する。
    """
    from app.main import _config_readiness

    settings = Settings(_env_file=None, storage_backend="r2")
    assert settings.resolved_storage_backend == "r2"
    assert settings.r2_configured is False
    assert _config_readiness(settings)["storage_r2"] is False


def test_config_readiness_storage_r2_is_true_when_local_backend():
    """R2 を使わない構成（ローカルディスク運用）では ``storage_r2`` は常に True
    （劣化ではないため）。"""
    from app.main import _config_readiness

    settings = Settings(_env_file=None, storage_backend="local")
    assert _config_readiness(settings)["storage_r2"] is True
