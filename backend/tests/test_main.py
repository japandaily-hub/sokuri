"""``app.main.create_app`` の本番起動ガード（fail-open 対策）の単体テスト。

``create_app(settings=...)`` へ ``Settings`` を直接注入することで、
実プロセスの環境変数や backend/.env に依存せず起動ガードのみを検証する。
``Settings(_env_file=None, ...)`` で .env の読み込みを遮断する。
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import get_session
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


async def test_health_returns_storage_backend_name():
    """/health は現在有効なストレージバックエンド名（"local"|"r2"）を返す（秘密値は含まない）。"""
    settings = Settings(_env_file=None)
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["storage"] in ("local", "r2")


async def test_health_and_readyz_accept_head_for_external_monitors():
    """UptimeRobot 等は HEAD で叩く。GET 専用だと 405 で「Down」誤判定（2026-09-08 実測）。"""
    app = create_app(Settings(_env_file=None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.head("/health")).status_code == 200
        assert (await client.get("/health")).status_code == 200
        r = await client.head("/readyz")
        assert r.status_code in (200, 503)  # DB 到達性次第。405 でないことが要点


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


# ──────────────────────────── 422 バリデーションエラーの送信値反射防止 ────────────────────────────
# security review 2026-09-18 Medium: FastAPI 既定の RequestValidationError ハンドラは
# exc.errors() をそのまま返すため、各エラー要素の "input" キーに送信された生の値
# （例: signup の平文パスワード）がそのまま反射されていた。


def _app_with_test_db(db_session: AsyncSession) -> FastAPI:
    """``create_app()`` のカスタム例外ハンドラを含む実アプリに、テスト用 DB を注入する。"""
    settings = Settings(_env_file=None)
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    return app


async def test_signup_validation_error_does_not_reflect_submitted_password(
    db_session: AsyncSession,
):
    """短すぎるパスワードで signup すると 422 になるが、応答本文に平文パスワードが
    含まれない（"input" キーが落とされていること）。"""
    app = _app_with_test_db(db_session)
    submitted_password = "short1"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/signup",
            json={"email": "reflect-test@example.com", "password": submitted_password},
        )
    assert r.status_code == 422
    assert submitted_password not in r.text
    for error in r.json()["detail"]:
        assert set(error.keys()) == {"type", "loc", "msg"}


async def test_validation_error_response_keeps_loc_msg_type_for_web_compat(
    db_session: AsyncSession,
):
    """web 側（katadzuke-api.ts の throwHttpError）が参照する detail の形状
    （文字列、または {code, message} を持つオブジェクト）はこの応答に存在しない
    ため互換性への影響は無いが、診断に必要な loc/msg/type は維持されていること。"""
    app = _app_with_test_db(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/signup",
            json={"email": "not-an-email", "password": "validpassword123"},
        )
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], list) and body["detail"]
    error = body["detail"][0]
    assert error["loc"] == ["body", "email"]
    assert isinstance(error["msg"], str) and error["msg"]
    assert isinstance(error["type"], str) and error["type"]
