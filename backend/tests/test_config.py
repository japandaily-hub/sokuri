"""``app.config.Settings.allowed_origins`` の正規化ロジックの単体テスト。

``Settings(_env_file=None, ...)`` で backend/.env の読み込みを遮断し、
実行環境の環境変数や .env ファイルに依存せず純粋にコンストラクタ引数のみで検証する。
"""

from __future__ import annotations

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
