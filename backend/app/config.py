"""アプリケーション設定の集約（pydantic-settings、ハンドオフ §5 の config.py 規約）。

注: ハンドオフ §5 は config.py が既存実装済みとしている。既存コードが提供され次第、
本モジュールと統合すること（現時点では既存コードはワークスペース未配置）。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数 / .env から読み込むアプリ全体設定。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL 接続 URL（asyncpg ドライバ）
    database_url: str = "postgresql+asyncpg://assetwise:assetwise@localhost:5432/assetwise"
    # Google AI Studio API キー（Gemini Vision 用）
    google_api_key: str = ""
    # SQLAlchemy のクエリエコー
    sql_echo: bool = False

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_postgres_url(cls, v: str) -> str:
        """Railway / Heroku 等のマネージド PaaS は ``DATABASE_URL`` を
        ``postgres://`` または ``postgresql://`` 形式（ドライバ指定なし）で
        払い出す。SQLAlchemy 非同期エンジン (``create_async_engine``) は
        ``postgresql+asyncpg://`` プレフィックスが必須のため、ここで自動補正する。

        影響範囲: ``Settings.database_url`` の最終値のみ。下流コード（session.py）は
        変更不要。

        変換規則:
            ``postgres://...``        → ``postgresql+asyncpg://...``
            ``postgresql://...``       → ``postgresql+asyncpg://...``  (ドライバ未指定時のみ)
            ``postgresql+asyncpg://`` → そのまま（ローカル / 既に正しい）
        """
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://") :]
        if v.startswith("postgresql://") and "+" not in v.split("://", 1)[0]:
            return "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v


@lru_cache
def get_settings() -> Settings:
    """設定オブジェクトのシングルトンを返す（プロセス内で 1 度だけ構築）。"""
    return Settings()
