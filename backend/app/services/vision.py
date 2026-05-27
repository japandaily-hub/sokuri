"""AI Vision サービス — Gemini Vision + Structured Outputs で画像から製品情報を抽出する。

設計判断:
- ``google-genai`` SDK の ``client.aio.models.generate_content`` で全体を async 統一。
- ``response_schema`` に Pydantic モデルを直接渡し、型安全な構造化抽出を実現。
- 入力画像は base64 data URI・HTTPS URL の両方を受け付ける（AnalyzeRequest 契約通り）。
- ``image_object_key`` はオブジェクトストレージキーのモック（Phase 4 以降で実ストレージに置換）。
- ``base_market_price_jpy`` を含む完全な ``VisionResult`` を返し、呼び出し側が Item に保存する。
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Annotated, Any, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db.models.enums import CategoryTier, ItemCondition

# ---------------------------------------------------------------------------
# 内部 DTO
# ---------------------------------------------------------------------------

class VisionResult(BaseModel):
    """vision サービスが返す内部転送オブジェクト。

    ``attributes`` は Tier 固有の可変フィールドを収容する。
    ``base_market_price_jpy`` は AI が推定した基準相場であり、
    Item.attributes["base_market_price_jpy"] として永続化する。
    """

    detected_name: str
    detected_category_label: str | None = None
    category_tier: CategoryTier
    initial_condition: ItemCondition
    condition_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    base_market_price_jpy: int = Field(ge=0, description="AI 推定の基準相場（JPY）")
    image_object_key: str = Field(description="入力画像のオブジェクトストレージキー（モック）")


# ---------------------------------------------------------------------------
# Gemini Structured Outputs 用抽出スキーマ
# ---------------------------------------------------------------------------

class _ProductAttributes(BaseModel):
    """Tier 固有の製品属性。未確定のフィールドは None。"""

    brand: str | None = None
    model_name: str | None = None
    color: str | None = None
    storage_gb: int | None = None       # スマートフォン・PC 等
    ram_gb: int | None = None           # PC 等
    year: int | None = None             # 車・家電等
    mileage_km: int | None = None       # 車
    area_sqm: float | None = None       # 不動産
    material: str | None = None         # 貴金属・ブランド品


class _VisionExtractSchema(BaseModel):
    """Gemini が返す構造化抽出スキーマ。

    ``category_tier`` / ``initial_condition`` は Literal で固定し、
    response_schema の enum 制約でハルシネーションを抑制する。
    """

    detected_name: str = Field(
        description="品目の正式名称（例: 'iPhone 15 Pro 256GB Space Black'）"
    )
    detected_category_label: str | None = Field(
        default=None,
        description="細分類ラベル（例: 'スマートフォン'、'ブランドバッグ'、'普通乗用車'）",
    )
    category_tier: Literal[
        "high_value_standard",
        "low_value_daily",
        "vehicle",
        "real_estate",
    ] = Field(description="粗カテゴリ: high_value_standard / low_value_daily / vehicle / real_estate")
    initial_condition: Literal["new", "like_new", "good", "fair", "poor", "unknown"] = Field(
        description="コンディション推定"
    )
    condition_confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = Field(
        default=None,
        description="コンディション判定の信頼度 0.0–1.0",
    )
    attributes: _ProductAttributes = Field(default_factory=_ProductAttributes)
    base_market_price_jpy: int = Field(
        ge=0,
        description="現在の日本市場における中立な基準相場（JPY）。不明な場合は 0。",
    )


# ---------------------------------------------------------------------------
# メインロジック
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """
あなたは中古品鑑定の専門家です。
与えられた画像から品目を特定し、指定の JSON スキーマで回答してください。

ルール:
1. detected_name は "ブランド + モデル + スペック" の形式で具体的に記述する。
2. category_tier は以下の定義に従う:
   - high_value_standard: スマートフォン・PC・カメラ・ブランドバッグ・貴金属・腕時計など
   - low_value_daily: 家電・家具・生活雑貨・書籍・衣類（ブランド品以外）
   - vehicle: 自動車・バイクなど
   - real_estate: 土地・建物
3. base_market_price_jpy は中立な基準相場。楽観的でも悲観的でもない中央値を推定する。
4. 不確実な属性は null にする。
""".strip()

# Gemini 2.5 Flash: 2.0 Flash は新規ユーザー向け提供終了のため切替必須。
# 元コードに対する唯一の差分。
_MODEL = "gemini-2.5-flash"


async def analyze_image(base_image: str) -> VisionResult:
    """画像を Gemini Vision で解析し :class:`VisionResult` を返す。

    Args:
        base_image: base64 エンコード文字列（``data:image/...;base64,...`` 形式）
                    または HTTPS URL。

    Returns:
        AI が抽出した製品情報の内部 DTO。

    Raises:
        google.genai.errors.APIError: Gemini サービスとの通信に失敗した場合。
        ValueError: 画像フォーマットが不正な場合 / レスポンスが空の場合。
    """
    settings = get_settings()
    client = genai.Client(api_key=settings.google_api_key)

    # --- 入力画像を genai Part に変換 ---
    if base_image.startswith("data:image/"):
        # "data:image/jpeg;base64,/9j/..." → mime_type + bytes
        header, b64data = base_image.split(",", 1)
        mime_type = header.split(":")[1].split(";")[0]  # e.g. "image/jpeg"
        image_bytes = base64.b64decode(b64data)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    elif base_image.startswith("https://"):
        # 公開 HTTPS URL は file_data 経由で渡す
        image_part = types.Part(
            file_data=types.FileData(file_uri=base_image, mime_type="image/jpeg")
        )
    else:
        raise ValueError(
            "base_image は 'data:image/...' の base64 文字列または 'https://' の URL である必要があります。"
        )

    response = await client.aio.models.generate_content(
        model=_MODEL,
        contents=[
            image_part,
            "この品目を鑑定し、指定のスキーマで回答してください。",
        ],
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_VisionExtractSchema,
        ),
    )

    response_text = response.text
    if not response_text:
        raise ValueError("Gemini からの Structured Output が空でした。")

    parsed_dict: dict = json.loads(response_text)
    parsed = _VisionExtractSchema(**parsed_dict)

    # Tier 固有属性を dict に変換（None 値は除外して attributes を軽量化）
    raw_attrs = parsed.attributes.model_dump(exclude_none=True)

    # モック用の image_object_key を生成（Phase 4 で実ストレージのキーに置換）
    mock_key = f"items/{uuid.uuid4()}.jpg"  # TODO(Phase 4): 実オブジェクトストレージのキー

    return VisionResult(
        detected_name=parsed.detected_name,
        detected_category_label=parsed.detected_category_label,
        category_tier=CategoryTier(parsed.category_tier),
        initial_condition=ItemCondition(parsed.initial_condition),
        condition_confidence=parsed.condition_confidence,
        attributes=raw_attrs,
        base_market_price_jpy=parsed.base_market_price_jpy,
        image_object_key=mock_key,
    )
