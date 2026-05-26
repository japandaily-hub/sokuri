"""API 層の Pydantic スキーマ定義（Phase 2 — API 契約設計）。

エンドポイント責務（ハンドオフ §5 未解決不整合の確定版）:
- POST /api/v1/analyze  : AI による製品特定（カテゴリ・モデル・コンディション初期推定）
- POST /api/v1/estimate : ユーザー確定コンディション × 乗数による減価後価格算出 + チャネル推奨
- POST /api/v1/assessments/{assessment_id}/defects : 瑕疵エビデンス写真の添付

コンディション乗数は :data:`CONDITION_CONFIG` に集約。
DB 層の :class:`~app.db.models.enums.ItemCondition` と 1:1 に対応する。
UNKNOWN は estimate API では受け付けない（ユーザーが必ずコンディションを選択する）。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.db.models.enums import CategoryTier, ChannelType, ItemCondition, RoutingMethod

# ---------------------------------------------------------------------------
# コンディション設定テーブル（§2 のマルチプライヤー定義）
# ---------------------------------------------------------------------------

class ConditionConfig(BaseModel):
    """1 コンディションの表示定義と減価乗数。"""

    label: str
    """UI 表示ラベル（日本語）。"""

    multiplier: float = Field(gt=0.0, le=2.0)
    """base_market_price に乗ずる係数。1.0 = 基準価格。"""

    defect_evidence_required: bool
    """True の場合、estimate 後に瑕疵写真のアップロードが必要。"""


CONDITION_CONFIG: dict[ItemCondition, ConditionConfig] = {
    ItemCondition.NEW: ConditionConfig(
        label="新品同様",
        multiplier=1.1,
        defect_evidence_required=False,
    ),
    ItemCondition.LIKE_NEW: ConditionConfig(
        label="美品",
        multiplier=1.0,
        defect_evidence_required=False,
    ),
    ItemCondition.GOOD: ConditionConfig(
        label="軽い傷あり",
        multiplier=0.8,
        defect_evidence_required=False,
    ),
    ItemCondition.FAIR: ConditionConfig(
        label="目立つ傷あり",
        multiplier=0.5,
        defect_evidence_required=True,
    ),
    ItemCondition.POOR: ConditionConfig(
        label="ジャンク",
        multiplier=0.1,
        defect_evidence_required=True,
    ),
}
"""コンディション → 乗数・UI設定のマスタ。"""


# ---------------------------------------------------------------------------
# POST /api/v1/analyze
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """写真投稿による製品スペック特定リクエスト。"""

    base_image: str = Field(
        description="撮影画像。base64 エンコード文字列 または HTTPS URL を受け付ける。",
        examples=["data:image/jpeg;base64,/9j/4AAQ...", "https://example.com/item.jpg"],
    )


class AnalyzeResponse(BaseModel):
    """AI による製品特定結果。"""

    item_id: uuid.UUID = Field(description="生成された Item の UUID。/estimate に渡す。")
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
        description="AI の初期コンディション推定。ユーザーが /estimate で上書き可能。"
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
# POST /api/v1/estimate
# ---------------------------------------------------------------------------

class EstimateRequest(BaseModel):
    """コンディション確定後の減価計算リクエスト。"""

    item_id: uuid.UUID = Field(description="/analyze が返した item_id。")
    condition: ItemCondition = Field(
        description=(
            "ユーザーが確定したコンディション。"
            "UNKNOWN は受け付けない（バリデーションエラー）。"
        )
    )

    @model_validator(mode="after")
    def _condition_must_not_be_unknown(self) -> "EstimateRequest":
        if self.condition == ItemCondition.UNKNOWN:
            raise ValueError(
                "condition に UNKNOWN は指定できません。"
                "ユーザーが明示的なコンディションを選択してください。"
            )
        return self


class ConditionDetail(BaseModel):
    """1 コンディションの見積もり詳細（全選択肢を一覧表示するために使用）。"""

    label: str
    multiplier: float
    estimated_price: int = Field(description="base_market_price × multiplier を整数化した値（JPY）。")
    defect_evidence_required: bool


class RecommendationResponse(BaseModel):
    """チャネル推奨の 1 件分。"""

    rank: int = Field(ge=1, description="推奨順位（1 = 最優先）。")
    channel_code: str = Field(description="チャネルの安定識別子（例: 'mota_car'）。")
    channel_name: str
    channel_type: ChannelType
    reason: str | None = Field(default=None, description="中立な推奨理由。")
    outbound_url: str | None = Field(
        default=None,
        description="Phase 4 以降で生成される送客 URL。Phase 2 時点では None。",
    )
    is_sponsored: bool = Field(
        description="有料送客枠。True の場合 UI で PR 表記必須（ステマ規制 §3）。"
    )


class EstimateResponse(BaseModel):
    """減価後価格と推奨チャネル一覧。"""

    assessment_id: uuid.UUID = Field(
        description="生成された Assessment の UUID。/defects に渡す。"
    )
    base_market_price: int = Field(ge=0, description="AI が推定した基準相場（JPY、中立値）。")
    price_currency: str = Field(default="JPY", pattern="^[A-Z]{3}$")
    conditions: dict[str, ConditionDetail] = Field(
        description=(
            "全コンディション選択肢とそれぞれの見積もり額。"
            "キーは ItemCondition の value 文字列（例: 'like_new'）。"
        )
    )
    selected_condition: ItemCondition
    estimated_price: int = Field(ge=0, description="選択コンディション適用後の見積もり額（JPY）。")
    defect_evidence_required: bool = Field(
        description=(
            "True の場合、この assessment_id に対して"
            " POST /assessments/{id}/defects で瑕疵写真のアップロードが必要。"
        )
    )
    routing_method: RoutingMethod
    recommendations: list[RecommendationResponse] = Field(
        description="推奨チャネル一覧（rank 昇順）。"
    )


# ---------------------------------------------------------------------------
# GET /api/v1/assessments/{assessment_id}
# ---------------------------------------------------------------------------

class AssessmentGetResponse(BaseModel):
    """GET /assessments/{id} — 既存 Assessment の参照レスポンス。

    フロントエンドの /result?assessment_id=... フォールバック用。
    EstimateResponse と同じキーを持つが、リクエスト不要な軽量版。
    """

    assessment_id: uuid.UUID
    item_id: uuid.UUID
    estimated_price: int = Field(ge=0)
    defect_evidence_required: bool
    recommendations: list[RecommendationResponse]


# ---------------------------------------------------------------------------
# POST /api/v1/assessments/{assessment_id}/defects
# ---------------------------------------------------------------------------

class DefectUploadRequest(BaseModel):
    """瑕疵エビデンス写真のアップロードリクエスト。"""

    defect_image: str = Field(
        description="瑕疵部位の写真。base64 エンコード文字列 または HTTPS URL。",
        examples=["data:image/jpeg;base64,/9j/4AAQ...", "https://example.com/scratch.jpg"],
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="瑕疵の補足説明（任意）。例: '左側面に 2cm 程度の傷'。",
    )


class DefectUploadResponse(BaseModel):
    """瑕疵エビデンス登録結果。"""

    defect_id: uuid.UUID = Field(description="登録された瑕疵エビデンスの UUID。")
    assessment_id: uuid.UUID
    image_object_key: str = Field(description="オブジェクトストレージのキー（内部参照用）。")
    status: str = Field(
        default="accepted",
        description="'accepted' = 登録完了。査定結果への反映は非同期。",
    )


# ---------------------------------------------------------------------------
# 共通エラーレスポンス
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """全エンドポイント共通のエラーレスポンス。"""

    code: str = Field(description="機械可読なエラーコード（例: 'ITEM_NOT_FOUND'）。")
    message: str = Field(description="人間可読なエラーメッセージ。")
    detail: Any | None = Field(default=None, description="追加のデバッグ情報（開発環境のみ）。")
