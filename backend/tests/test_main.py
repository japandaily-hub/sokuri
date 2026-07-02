"""``app.main.create_app`` の本番起動ガード（fail-open 対策）の単体テスト。

``create_app(settings=...)`` へ ``Settings`` を直接注入することで、
実プロセスの環境変数や backend/.env に依存せず起動ガードのみを検証する。
``Settings(_env_file=None, ...)`` で .env の読み込みを遮断する。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app

_STRONG_JWT_SECRET = "a" * 64  # 64桁のダミー強鍵（本物のランダム鍵の代替として長さのみ検証）


def test_production_with_default_jwt_secret_raises():
    """production × デフォルト鍵（dev-secret-change-me）は RuntimeError。"""
    settings = Settings(_env_file=None, APP_ENV="production", jwt_secret="dev-secret-change-me")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(settings)


def test_production_with_env_example_placeholder_secret_raises():
    """production × .env.example の例示鍵（change-me-to-random-64-hex）は RuntimeError。"""
    settings = Settings(
        _env_file=None, APP_ENV="production", jwt_secret="change-me-to-random-64-hex"
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(settings)


def test_production_with_short_secret_raises():
    """production × 32文字未満の短鍵は RuntimeError。"""
    settings = Settings(_env_file=None, APP_ENV="production", jwt_secret="short-secret-key")
    assert len(settings.jwt_secret) < 32
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(settings)


def test_production_with_strong_secret_succeeds():
    """production × 強鍵（64文字）は例外なく FastAPI インスタンスを取得できる。"""
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        jwt_secret=_STRONG_JWT_SECRET,
        ALLOWED_ORIGINS="https://sokuri.vercel.app",
    )
    app = create_app(settings)
    assert isinstance(app, FastAPI)


def test_development_with_default_secret_succeeds():
    """development × デフォルト鍵は例外なし（開発体験を損なわない）。"""
    settings = Settings(_env_file=None, APP_ENV="development", jwt_secret="dev-secret-change-me")
    app = create_app(settings)
    assert isinstance(app, FastAPI)


def test_production_with_wildcard_allowed_origins_raises():
    """production × ALLOWED_ORIGINS="*" は fail-open のため RuntimeError。"""
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        jwt_secret=_STRONG_JWT_SECRET,
        ALLOWED_ORIGINS="*",
    )
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        create_app(settings)


def test_production_with_wildcard_mixed_into_valid_origins_raises():
    """production × ALLOWED_ORIGINS に正規オリジンと "*" が空白付きで混在していても RuntimeError。"""
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        jwt_secret=_STRONG_JWT_SECRET,
        ALLOWED_ORIGINS="https://sokuri.vercel.app, *",
    )
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        create_app(settings)
