"""案件 AI サマリー生成 — 既存 vision.analyze_image（Gemini Vision）を流用する。

案件写真（最大 4 枚）をそれぞれ解析し、検出された品目を集約して
業者向けの日本語サマリーを組み立てる。AI 失敗時は住居情報ベースの
フォールバック文を返す（案件作成自体は失敗させない）。
"""

from __future__ import annotations

import logging

from app.services import storage
from app.services.vision import analyze_image

logger = logging.getLogger(__name__)

_MAX_PHOTOS_FOR_AI = 4


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
) -> str:
    """写真群から案件サマリーを生成する。

    Args:
        photo_urls: 解析対象の画像（HTTPS URL または base64 データ URL）。

    Returns:
        業者の入札判断に使う日本語サマリー。AI 不可時もフォールバック文を返す。
    """
    detected: list[str] = []
    for url in photo_urls[:_MAX_PHOTOS_FOR_AI]:
        try:
            result = await analyze_image(url)
            label = result.detected_name or result.detected_category_label
            if label:
                detected.append(label)
        except Exception as exc:  # AI 失敗は案件作成を止めない
            logger.warning("summary: 写真解析に失敗（continue）- %s", exc)
            continue

    base = _fallback_summary(purpose, housing_type, floor_plan, len(photo_urls))
    if not detected:
        return base
    items = "、".join(dict.fromkeys(detected))  # 重複除去・順序保持
    return f"{base} AI 検出品目: {items}。"


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
