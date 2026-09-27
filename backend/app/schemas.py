"""API 層の Pydantic スキーマ定義（Phase 2 — API 契約設計）。

エンドポイント責務:
- POST /api/v1/analyze  : AI による製品特定（カテゴリ・モデル・コンディション初期推定）

旧 AssetWise の査定 API（/estimate・/assessments/*。コンディション乗数テーブル
CONDITION_CONFIG を含む）は 2026-09-27 に撤去した（認証・回数制限の無い書き込み口で、
web からの呼び出し元も本番の利用も無かったため）。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.db.models.enums import CategoryTier, ItemCondition

# ---------------------------------------------------------------------------
# POST /api/v1/analyze
# ---------------------------------------------------------------------------

_ANALYZE_BASE_IMAGE_MAX_CHARS = 10 * 1024 * 1024 * 4 // 3 + 256


class AnalyzeRequest(BaseModel):
    """写真投稿による製品スペック特定リクエスト。"""

    base_image: str = Field(
        description="撮影画像。base64 エンコード文字列（data: URL）のみ受け付ける（外部URLは不可）。",
        examples=["data:image/jpeg;base64,/9j/4AAQ..."],
        # 復号後 10MB（写真アップロードと同じ上限・storage.MAX_UPLOAD_BYTES）を base64 にした長さ
        # ＋ data URL の接頭辞の余裕。上限が無いと巨大な JSON でワーカーのメモリが跳ねる
        # （security / QA review。復号後のサイズは vision._decode_image_for_ai でも検査する）。
        max_length=_ANALYZE_BASE_IMAGE_MAX_CHARS,
    )

    @field_validator("base_image")
    @classmethod
    def _reject_external_url(cls, value: str) -> str:
        """外部 URL（http(s)://）を拒否し、base64 / data: URL のみ受理する（security review M-5）。

        ``app.services.vision`` の内部実装は HTTPS URL も file_uri として
        Gemini へ素通しできるが、任意の外部URLを公開APIの入力としてそのまま
        受け付けると、内部/私設アドレスの探索や第三者リソースへの帯域消費の
        踏み台にされ得る（SSRF系の悪用面）。vision.py 自体（案件フローが
        別途利用）は変更せず、この公開エンドポイントの契約としてのみ制限する。
        """
        stripped = value.strip().lower()
        if stripped.startswith("http://") or stripped.startswith("https://"):
            raise ValueError(
                "画像は base64 エンコード文字列（data: URL）で送信してください。外部URLは指定できません。"
            )
        return value


class AnalyzeResponse(BaseModel):
    """AI による製品特定結果。"""

    item_id: uuid.UUID = Field(description="生成された Item の UUID。")
    detected_name: str = Field(
        description="AI が判定した品目名（例: 'iPhone 15 Pro 256GB Space Black'）。"
    )
    detected_category_label: str | None = Field(
        default=None,
        description="AI が判定した細分類ラベル（例: 'スマートフォン'）。",
    )
    category_tier: CategoryTier = Field(
        description="ルーティング判定の基軸となる粗カテゴリ。"
    )
    initial_condition: ItemCondition = Field(
        description="AI の初期コンディション推定。"
    )
    condition_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="コンディション判定の信頼度（0.0–1.0）。",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Tier 固有の可変属性。"
            "例: {'brand': 'Apple', 'model': 'iPhone 15 Pro', 'storage_gb': 256}"
        ),
    )


# ---------------------------------------------------------------------------
# 共通エラーレスポンス
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """全エンドポイント共通のエラーレスポンス。"""

    code: str = Field(description="機械可読なエラーコード（例: 'ITEM_NOT_FOUND'）。")
    message: str = Field(description="人間可読なエラーメッセージ。")
    detail: Any | None = Field(default=None, description="追加のデバッグ情報（開発環境のみ）。")
