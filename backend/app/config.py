"""アプリケーション設定の集約（pydantic-settings、ハンドオフ §5 の config.py 規約）。

注: ハンドオフ §5 は config.py が既存実装済みとしている。既存コードが提供され次第、
本モジュールと統合すること（現時点では既存コードはワークスペース未配置）。
"""

from __future__ import annotations

from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    """設定オブジェクトのシングルトンを返す（プロセス内で 1 度だけ構築）。"""
    return Settings()
