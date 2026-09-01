"""案件 AI サマリー生成 — 既存 vision.analyze_image（Gemini Vision）を流用する。"""

from __future__ import annotations

import logging
import re
import unicodedata

from app.db.models.enums import ItemCondition
from app.services import storage
from app.services.vision import analyze_image

logger = logging.getLogger(__name__)

_MAX_PHOTOS_FOR_AI = 4
# ai_summary は全業者（承認前アカウント含む）に配信されるため、単一属性値の長さと
# 最終文字列の長さの両方に上限を設ける（security review Medium-2対応: 画像内に
# 長文を印字してアップロードするとGemini経由でDBカラム・UIが肥大化しうる）。
_MAX_ATTR_LEN = 40
_MAX_SUMMARY_LEN = 500

# 傷・色あせ・凹みなど状態注記が必要なコンディション。
_NOTABLE_CONDITIONS = {ItemCondition.FAIR, ItemCondition.POOR}

# 属性値として許容する文字種（日本語・英数字・空白・一般的な記号のみ）。
_ATTR_ALLOWED_RE = re.compile(r"^[\w\s぀-ヿ一-鿿\-.()/]{1,%d}$" % _MAX_ATTR_LEN)
# URL・連絡先・命令文らしき文字列を弾くための簡易シグナル。
_ATTR_SUSPICIOUS_RE = re.compile(r"https?://|www\.|@|\.(com|net|jp|org|io)\b", re.IGNORECASE)


def _safe_attr(value: object) -> str | None:
    """Gemini由来の属性値(brand/model_name)を業者表示用に無害化する。

    画像内に印字された任意の文字列（偽装ブランドラベル等）がGeminiの構造化
    出力を経由してそのまま「AI要約」として全業者に配信されるのを防ぐ
    （security review Medium-1対応: 間接プロンプトインジェクション/なりすまし
    コンテンツ注入の緩和）。プロンプト側の指示（vision.pyのrule 6）だけに
    依存せず、ここでも機械的に検証する多層防御とする。
    """
    if not value:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    # 制御文字・Unicode双方向制御文字を除去(表示崩れ・なりすまし対策)。
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    if not text:
        return None
    if not _ATTR_ALLOWED_RE.match(text):
        return None
    if _ATTR_SUSPICIOUS_RE.search(text):
        return None
    return text


def _fallback_summary(
    purpose: str,
    housing_type: str | None,
    floor_plan: str | None,
    photo_count: int,
) -> str:
    parts = [f"利用目的: {purpose}。"]
    if housing_type:
        parts.append(f"住居: {housing_type}")
        if floor_plan:
            parts.append(f"（{floor_plan}）")
        parts.append("。")
    parts.append(f"写真 {photo_count} 枚。詳細は写真を確認してください。")
    return "".join(parts)


async def generate_case_summary(
    *,
    purpose: str,
    housing_type: str | None,
    floor_plan: str | None,
    photo_urls: list[str],
    photo_count: int | None = None,
) -> str:
    """写真群から案件サマリーを生成する。AI 不可時もフォールバック文を返す。"""
    detected: list[str] = []
    for url in photo_urls[:_MAX_PHOTOS_FOR_AI]:
        try:
            result = await analyze_image(url)
            label = result.detected_name or result.detected_category_label
            if not label:
                continue
            notes: list[str] = []
            for raw_value in (result.attributes.get("brand"), result.attributes.get("model_name")):
                value = _safe_attr(raw_value)
                if value and value not in label and value not in notes:
                    notes.append(value)
            if result.initial_condition in _NOTABLE_CONDITIONS:
                notes.append("状態: 傷・使用感あり")
            if notes:
                label = f"{label}（{'、'.join(notes)}）"
            detected.append(label)
        except Exception as exc:
            # 例外オブジェクトを直接%sで文字列化しない（SDKの例外に画像データや
            # リクエスト内容が含まれる可能性を考慮し、型名+切り詰めのみ記録）。
            logger.warning(
                "summary: 写真解析に失敗（continue）- %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            continue

    base = _fallback_summary(
        purpose, housing_type, floor_plan,
        photo_count if photo_count is not None else len(photo_urls),
    )
    if not detected:
        return base
    items = "、".join(dict.fromkeys(detected))
    summary = f"{base} AI 検出品目: {items}。"
    if len(summary) > _MAX_SUMMARY_LEN:
        summary = summary[:_MAX_SUMMARY_LEN].rstrip() + "…"
    return summary


def photo_url_for_ai(storage_key: str, raw_url: str | None) -> str | None:
    """AI に渡す画像参照を決める。ローカル保存ファイルは base64 データ URL 化する。"""
    path = storage.file_path(storage_key)
    if path is not None:
        import base64

        ext = path.suffix.lstrip(".").lower()
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{data}"
    if raw_url and raw_url.startswith("https://"):
        return raw_url
    return None
