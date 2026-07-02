"""アプリケーション設定の集約（pydantic-settings、ハンドオフ §5 の config.py 規約）。

注: ハンドオフ §5 は config.py が既存実装済みとしている。既存コードが提供され次第、
本モジュールと統合すること（現時点では既存コードはワークスペース未配置）。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数 / .env から読み込むアプリ全体設定。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # PostgreSQL 接続 URL（asyncpg ドライバ）
    database_url: str = "postgresql+asyncpg://assetwise:assetwise@localhost:5432/assetwise"
    # Google AI Studio API キー（Gemini Vision 用）
    google_api_key: str = ""
    # SQLAlchemy のクエリエコー
    sql_echo: bool = False

    # ── カタヅケ: 認証 / ストレージ / メール ──────────────────────────
    # JWT 署名鍵（本番では必ず環境変数 JWT_SECRET で上書きする）
    jwt_secret: str = "dev-secret-change-me"
    # JWT 有効期限（分）。デフォルト 7 日。
    jwt_expire_minutes: int = 60 * 24 * 7
    # 管理者ロールで登録される email（カンマ区切り）。signup 時に role='admin' を付与。
    admin_emails_raw: str = Field(default="", alias="ADMIN_EMAILS")
    # 写真ファイルの保存ディレクトリ（Render Free はエフェメラル。βでは許容）
    storage_dir: str = "./uploads_storage"
    # Brevo（メール通知）。未設定時は送信をスキップする。
    brevo_api_key: str = ""
    mail_from: str = "noreply@katadzuke.jp"
    mail_from_name: str = "カタヅケ"
    # フロントエンドの基点 URL（メール内リンク用）
    frontend_base_url: str = "http://localhost:3000"
    # 機微データ（振込先口座情報等）の対称鍵暗号化キー（Fernet, urlsafe base64 32byte）。
    # 未設定時は app.core.crypto の呼び出し時にエラーで落ちる（鍵欠如を握りつぶさない）。
    app_encryption_key: str = ""
    # LINE Messaging API のチャネルアクセストークン（Push通知送信用）。未設定時は送信をスキップする。
    line_channel_access_token: str = ""
    # LINE Login チャネル ID（フロントの LINE_CLIENT_ID と同一値）。
    # /auth/line/exchange でアクセストークンの発行元チャネルを検証（audience 検証）するために使用する。
    # 未設定時は LINE ログイン機能自体を未構成とみなし 503 を返す（セキュリティ上、検証をスキップしない）。
    line_client_id: str = ""
    # CORS で許可するオリジン（カンマ区切り）。未設定時は frontend_base_url とローカル開発用ポートを許可する。
    allowed_origins_raw: str = Field(default="", alias="ALLOWED_ORIGINS")
    # 実行環境（"development" | "production"）。本番起動時の fail-open ガードに使用する。
    app_env: str = Field(default="development", alias="APP_ENV")

    @property
    def admin_emails(self) -> list[str]:
        """ADMIN_EMAILS をカンマ区切りで正規化して返す（小文字化）。"""
        return [e.strip().lower() for e in self.admin_emails_raw.split(",") if e.strip()]

    @property
    def _default_allowed_origins(self) -> list[str]:
        """ALLOWED_ORIGINS 未設定時のフォールバック。

        production では frontend_base_url のみを返す（localhost を本番の
        暗黙許可オリジンに含めると、開発者のローカル環境から本番 API への
        意図しないクロスオリジンアクセスを許してしまうため）。
        development / それ以外ではローカル開発用ポートも併せて返す。
        """
        if self.app_env == "production":
            return [self.frontend_base_url]
        return [self.frontend_base_url, "http://localhost:3000", "http://localhost:3100"]

    @staticmethod
    def _is_dangerous_origin_token(token: str) -> bool:
        """fail-open を招く危険なオリジントークンかどうかを判定する。

        - ``"*"`` を含むトークン（厳密一致の ``"*"`` に加え、``https://*.evil.com``
          のようなワイルドカードサブドメイン混入も含む）。
        - 小文字化して ``"null"`` と一致するトークン（sandboxed iframe 等が
          送信する ``Origin: null`` を許可すると任意サイトからの偽装を許すため）。
        """
        stripped = token.strip()
        return "*" in stripped or stripped.lower() == "null"

    @property
    def allowed_origins(self) -> list[str]:
        """ALLOWED_ORIGINS をカンマ区切りで正規化して返す。

        - 各値は前後空白 trim ＋ 末尾スラッシュ除去（``rstrip("/")``）。
          末尾スラッシュ付き設定は CORS 判定が一致せず全滅する事故があるため予防する。
        - ``"*"`` を含むトークン、および ``"null"``（大小無視）は
          fail-open を招くため常に除外する。除外した結果 origins が空に
          なった場合はフォールバックへ倒す。
        - 未設定時（空文字）は ``_default_allowed_origins`` を返す。
        """
        if self.allowed_origins_raw.strip():
            origins = [
                o.strip().rstrip("/")
                for o in self.allowed_origins_raw.split(",")
                if o.strip() and not self._is_dangerous_origin_token(o)
            ]
            if not origins:
                origins = self._default_allowed_origins
        else:
            origins = self._default_allowed_origins
        seen: set[str] = set()
        deduped: list[str] = []
        for origin in origins:
            if origin not in seen:
                seen.add(origin)
                deduped.append(origin)
        return deduped

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_postgres_url(cls, v: str) -> str:
        """マネージド PaaS（Render / Heroku 等）は ``DATABASE_URL`` を
        ``postgres://`` または ``postgresql://`` 形式（ドライバ指定なし）で
        払い出す。SQLAlchemy 非同期エンジン (``create_async_engine``) は
        ``postgresql+asyncpg://`` プレフィックスが必須のため、ここで自動補正する。

        変換規則:
            ``postgres://...``        → ``postgresql+asyncpg://...``
            ``postgresql://...``       → ``postgresql+asyncpg://...``  (ドライバ未指定時のみ)
            ``postgresql+asyncpg://`` → そのまま（既に正しい）
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
