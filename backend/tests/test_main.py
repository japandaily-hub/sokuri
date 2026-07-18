"""``app.main.create_app`` の本番起動ガード（fail-open 対策）の単体テスト。

``create_app(settings=...)`` へ ``Settings`` を直接注入することで、
実プロセスの環境変数や backend/.env に依存せず起動ガードのみを検証する。
``Settings(_env_file=None, ...)`` で .env の読み込みを遮断する。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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


# ──────────────────────────── /health（デプロイ検証用ビルド識別子） ────────────────────────────


async def test_health_returns_status_and_commit_keys():
    """/health のレスポンスは status と commit の両キーを持つ。"""
    settings = Settings(_env_file=None)
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "commit" in data


async def test_health_commit_is_none_when_render_git_commit_unset():
    """RENDER_GIT_COMMIT 未設定（ローカル開発等）では commit は None。"""
    settings = Settings(_env_file=None)
    assert settings.render_git_commit is None
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.json()["commit"] is None


async def test_health_commit_truncated_to_first_7_chars():
    """RENDER_GIT_COMMIT 設定時は commit が先頭7桁に短縮される。"""
    settings = Settings(_env_file=None, render_git_commit="abcdef1234567890")
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.json()["commit"] == "abcdef1"


async def test_health_commit_reads_render_git_commit_from_env_var(
    monkeypatch: pytest.MonkeyPatch,
):
    """RENDER_GIT_COMMIT 環境変数から render_git_commit が読み込まれる
    （コンストラクタ引数を経由しない、pydantic-settings のフィールド名→環境変数名
    自動マッピング経路の回帰確認）。/health の commit も先頭7桁に短縮されること。"""
    monkeypatch.setenv("RENDER_GIT_COMMIT", "deadbeefcafe1234567890")
    settings = Settings(_env_file=None)
    assert settings.render_git_commit == "deadbeefcafe1234567890"

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.json()["commit"] == "deadbee"
