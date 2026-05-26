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

    新規フィールド（ハルシネーション抑制 & UX 強化）:
    - reasoning: CoT 推論プロセス（ログ・品質モニタリング用）
    - condition_evidence: 状態判定の視覚的根拠（UI 表示・業者見積もり時の補足）
    - identity_confidence: 型番特定の信頼度（< 0.7 で追加撮影 UI を出す）
    - recommended_additional_photos: ユーザーへの追加撮影提案（精度ループ）

    既存呼び出し側との互換性のため、新規フィールドは全てデフォルト値付き。
    """

    detected_name: str
    detected_category_label: str | None = None
    category_tier: CategoryTier
    initial_condition: ItemCondition
    condition_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    identity_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    condition_evidence: str | None = None
    reasoning: str | None = None
    recommended_additional_photos: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    base_market_price_jpy: int = Field(ge=0, description="AI 推定の基準相場（JPY）")
    image_object_key: str = Field(description="入力画像のオブジェクトストレージキー（モック）")


# ---------------------------------------------------------------------------
# Gemini Structured Outputs 用抽出スキーマ
# ---------------------------------------------------------------------------

class _ProductAttributes(BaseModel):
    """Tier 固有の製品属性。未確定のフィールドは None。

    精度向上ポイント:
    - 識別子系（brand / manufacturer / model_name / model_number / serial_visible）を分離。
      ロゴから読み取れる「ブランド」と背面シールから読み取る「型番」を別フィールドにし、
      モデルが両者を混同するのを防ぐ。
    - year は西暦 4 桁固定。製造年・モデル年式を「画像内に証拠がある場合のみ」記入させる。
    - 各推論には evidence（証拠文）を残し、ハルシネーション抑止と運用時の品質モニタリングを可能にする。
    """

    brand: str | None = Field(
        default=None,
        description="商標 / ロゴから判定したブランド名（例: 'Apple', 'Sony', 'Louis Vuitton'）。ロゴ未確認なら null",
    )
    manufacturer: str | None = Field(
        default=None,
        description="メーカー正式社名（ブランドと一致する場合は同値）",
    )
    model_name: str | None = Field(
        default=None,
        description="モデルの一般名称（例: 'iPhone 15 Pro', 'WH-1000XM5'）",
    )
    model_number: str | None = Field(
        default=None,
        description="本体・シール・刻印から読み取れる型番（例: 'A2890', 'WH-1000XM5/B'）。読み取れない場合は null",
    )
    serial_number_visible: bool = Field(
        default=False,
        description="シリアル番号やバーコードが画像内で可読か",
    )
    color: str | None = None
    storage_gb: int | None = None       # スマートフォン・PC 等
    ram_gb: int | None = None           # PC 等
    year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="製造年式（西暦 4 桁）。画像内に手がかりがある場合のみ。推測は禁止",
    )
    mileage_km: int | None = None       # 車
    area_sqm: float | None = None       # 不動産
    material: str | None = None         # 貴金属・ブランド品
    extraction_evidence: str | None = Field(
        default=None,
        description="ブランド・モデル・型番をどこから読み取ったかの根拠（例: '前面下部 Apple ロゴ + 背面 RoHS シール「A2890」'）",
    )


class _VisionExtractSchema(BaseModel):
    """Gemini が返す構造化抽出スキーマ。

    ``category_tier`` / ``initial_condition`` は Literal で固定し、
    response_schema の enum 制約でハルシネーションを抑制する。

    精度向上のため:
    - ``reasoning`` フィールドを先頭に置き、CoT（chain-of-thought）で推論プロセスを強制
    - ``condition_evidence`` で状態判定の視覚的根拠を必須記述
    - ``recommended_additional_photos`` で追加撮影を提案（精度ループ）
    - ``identity_confidence`` で型番識別の信頼度を独立評価
    """

    reasoning: str = Field(
        description=(
            "識別の思考プロセス（80-200 文字）。"
            "(1) 画像内で確認できた視覚的手がかり → "
            "(2) それらから導いたブランド・モデル・型番 → "
            "(3) 状態判定の根拠 の順で記述する。"
        ),
    )
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
        description="コンディション推定（ルブリックに厳密に従う）"
    )
    condition_evidence: str = Field(
        description=(
            "状態判定の視覚的根拠（30-150 文字）。"
            "例: '画面に微細な擦り傷 2 本、背面・側面はキレイ。"
            "シリアル刻印やボタン部に摩耗無し → like_new ではなく good'"
        ),
    )
    condition_confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = Field(
        default=None,
        description="コンディション判定の信頼度 0.0–1.0",
    )
    identity_confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = Field(
        default=None,
        description=(
            "型番・モデル特定の信頼度 0.0–1.0。"
            "0.7 未満なら recommended_additional_photos で型番ラベルの撮影を促す。"
        ),
    )
    attributes: _ProductAttributes = Field(default_factory=_ProductAttributes)
    base_market_price_jpy: int = Field(
        ge=0,
        description=(
            "現在の日本市場における中立な基準相場（JPY、状態 'good' 基準）。"
            "不明な場合は 0。楽観値・悲観値ではなく中央値を出すこと。"
        ),
    )
    recommended_additional_photos: list[str] = Field(
        default_factory=list,
        description=(
            "ユーザーに追加撮影を提案するリスト（最大 3 件）。"
            "例: ['本体背面の型番ラベル', '画面に傷がある箇所の接写', '付属品（箱・充電器）']"
        ),
    )


# ---------------------------------------------------------------------------
# メインロジック
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """
あなたは日本の中古品買取業界で 20 年の経験を持つ鑑定士です。
画像 1 枚から品目を特定し、指定の JSON スキーマで回答してください。

# 推論プロセス（必ず reasoning フィールドに残すこと）

ステップ 1: 画像内の **視覚的証拠** を列挙する
  - ロゴ・刻印・シール・型番ラベルの位置と読み取れる文字列
  - 形状・色・素材・サイズ感
  - 状態の手がかり（傷・汚れ・摩耗・付属品の有無）

ステップ 2: 証拠から品目を **演繹** する（推測で穴埋めしない）
  - ブランドはロゴが見えた場合のみ確定
  - 型番（model_number）は刻印・シールが読めた場合のみ記入、不可なら null
  - 年式（year）はモデル年式情報や製造年印字がある場合のみ記入、外観から推測しない

ステップ 3: コンディションをルブリックに従って判定する（次節）

ステップ 4: 信頼度を 2 軸で評価する
  - identity_confidence: 型番特定の確度
  - condition_confidence: 状態判定の確度

# 出力フィールドのルール

## detected_name
"ブランド + モデル + スペック" 形式。ブランド不明なら一般名のみ。
例: 'iPhone 15 Pro 256GB Space Black' / 'SONY WH-1000XM5 ブラック' / '木製ダイニングチェア 4 脚'

## category_tier
- high_value_standard: スマホ・PC・カメラ・ブランド品・貴金属・腕時計（単価 1 万円以上想定）
- low_value_daily: 家電（白物含む）・家具・生活雑貨・書籍・衣類（ブランド品以外）
- vehicle: 自動車・バイク・原付
- real_estate: 土地・建物

## initial_condition ルブリック（厳守）

| ラベル | 基準 |
|--------|------|
| new | 未開封、シュリンク・封印あり、付属品完全揃い |
| like_new | 開封済みだが使用感ほぼなし、傷ゼロ、付属品ほぼ揃い |
| good | 普通使用感、目立たない小傷あり、機能正常、付属品の一部欠落可 |
| fair | 明らかな傷・汚れ・色褪せあり、機能正常、付属品多くが欠落 |
| poor | 大きな破損・故障・大量の汚れ、修理または部品取り前提 |
| unknown | 画像から判定不能（写真ボケ・暗所・部分写りなど） |

判定は **画像内に確認できる範囲のみ**。
例: 「裏面が見えていないので like_new ではなく good」← OK
例: 「画像はキレイだが古いモデルだから fair」← NG（外観劣化の証拠がないので不可）

## base_market_price_jpy
- 状態 good を基準とした中央値（中古市場の中間値）。
- 楽観的見積もり（メルカリ高値）でも悲観的見積もり（買取最低）でもなく **mid**。
- 不明な品目は 0 を返す（推測で数値を出さない）。
- 単位は日本円（整数）。

## attributes.year（年式）
- 西暦 4 桁。
- **画像内に証拠がある場合のみ** 記入（型番から推定可・モデル年式の刻印・新車登録ステッカー等）。
- 「見た目が古いから」で記入しない。

## attributes.model_number（型番）
- メーカー型番。本体シール・背面刻印・銘板から読み取れる文字列のみ。
- ロゴから推測で書かない。読み取れなければ null。

## recommended_additional_photos
identity_confidence < 0.7 または condition_confidence < 0.7 の場合、
追加撮影を 1〜3 件提案する。具体的なアングルで:
- 良い例: '背面下部の型番シール接写', '画面表面の傷の真上から接写'
- 悪い例: 'もっと良い写真'（抽象的）

# 出力例（few-shot）

入力画像が iPhone のみ正面写真（背面シール見えず）:
{
  "reasoning": "前面下部に Apple ロゴ、ホームボタン無し・Dynamic Island あり → iPhone 14/15/16 Pro 系統。背面・型番シール見えず正確なモデル特定不可。画面割れなし、ベゼル損傷なし。",
  "detected_name": "Apple iPhone Pro 系統（モデル要確認）",
  "detected_category_label": "スマートフォン",
  "category_tier": "high_value_standard",
  "initial_condition": "like_new",
  "condition_evidence": "前面ガラスに擦り傷・割れなし、ベゼル損傷なし。背面・側面は未確認。",
  "condition_confidence": 0.6,
  "identity_confidence": 0.4,
  "attributes": {
    "brand": "Apple",
    "manufacturer": "Apple Inc.",
    "model_name": "iPhone Pro 系（要確認）",
    "model_number": null,
    "serial_number_visible": false,
    "color": null,
    "year": null,
    "extraction_evidence": "前面 Apple ロゴと Dynamic Island のみ確認。型番シール非可視。"
  },
  "base_market_price_jpy": 0,
  "recommended_additional_photos": [
    "本体背面（型番シールが読める明るさで）",
    "電源を入れた状態の画面（ロック画面でも可）",
    "側面・コーナーの傷の有無を確認できる斜め写真"
  ]
}

# 注意

- 「Apple っぽい」「たぶん 2022 年式」のような推測は禁止
- 不明はためらわずに null か 0 か unknown を使う
- ハルシネーションは買取業者への送信時にユーザーの信頼を破壊する
""".strip()

# Gemini 2.0 Flash: 速度・コスト・精度のバランス（中古品識別ユースケースに最適）
_MODEL = "gemini-2.0-flash"
# 推論温度は構造化抽出向けに低く固定（決定性重視）
_TEMPERATURE = 0.2


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
            temperature=_TEMPERATURE,
            # CoT(reasoning) を含むため出力上限を引き上げ。
            # 単一画像あたり 1500 トークンを超えることはまずないが安全側に。
            max_output_tokens=2048,
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
        identity_confidence=parsed.identity_confidence,
        condition_evidence=parsed.condition_evidence,
        reasoning=parsed.reasoning,
        recommended_additional_photos=parsed.recommended_additional_photos,
        attributes=raw_attrs,
        base_market_price_jpy=parsed.base_market_price_jpy,
        image_object_key=mock_key,
    )
