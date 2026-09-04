"""app.services.summary.generate_case_summary の単体テスト。

QAレビュー指摘対応: brand/model_name/initial_condition をai_summaryへ反映する新規
ロジック(summary.py)は、既存の統合テストでは非実在storage_keyのためAI解析経路
自体を通過しておらず(photo_url_for_ai()がNoneを返し即フォールバック)、実質未検証
だった。ここではanalyze_imageをmonkeypatchし、AI解析経路そのものを直接検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.db.models.enums import CategoryTier, ItemCondition
from app.services import summary as summary_module
from app.services.vision import VisionResult


def _result(
    *,
    detected_name: str = "テスト品目",
    detected_category_label: str | None = None,
    initial_condition: ItemCondition = ItemCondition.GOOD,
    attributes: dict | None = None,
) -> VisionResult:
    return VisionResult(
        detected_name=detected_name,
        detected_category_label=detected_category_label,
        category_tier=CategoryTier.LOW_VALUE_DAILY,
        initial_condition=initial_condition,
        condition_confidence=0.9,
        attributes=attributes or {},
        base_market_price_jpy=0,
        image_object_key="dummy-key",
    )


async def _generate(monkeypatch: pytest.MonkeyPatch, results: list) -> str:
    """analyze_image を順番にresultsを返すAsyncMockに差し替えて呼び出す。"""
    mock = AsyncMock(side_effect=results)
    monkeypatch.setattr(summary_module, "analyze_image", mock)
    return await summary_module.generate_case_summary(
        purpose="不用品処分",
        housing_type="マンション",
        floor_plan="2LDK",
        photo_urls=["https://example.com/dummy.jpg"] * len(results),
    )


async def test_brand_and_model_name_appended_without_notable_condition(monkeypatch):
    """brand/model_nameが取れていれば括弧書きで付記され、GOODでは状態注記が付かない。"""
    result = _result(
        detected_name="ノートPC",
        attributes={"brand": "Apple", "model_name": "MacBookAir"},
        initial_condition=ItemCondition.GOOD,
    )
    text = await _generate(monkeypatch, [result])
    assert "AI 検出品目: ノートPC（Apple、MacBookAir）。" in text
    assert "状態:" not in text


async def test_notable_condition_appends_state_note(monkeypatch):
    """FAIR/POORの場合のみ「状態: 傷・使用感あり」が付記される。"""
    fair = await _generate(monkeypatch, [_result(initial_condition=ItemCondition.FAIR)])
    assert "状態: 傷・使用感あり" in fair


async def test_poor_condition_appends_state_note(monkeypatch):
    poor = await _generate(monkeypatch, [_result(initial_condition=ItemCondition.POOR)])
    assert "状態: 傷・使用感あり" in poor


async def test_good_condition_no_state_note(monkeypatch):
    good = await _generate(monkeypatch, [_result(initial_condition=ItemCondition.GOOD)])
    assert "状態:" not in good


async def test_no_attributes_no_parentheses(monkeypatch):
    """brand/model_nameがともにNoneなら括弧注記なしでラベルのみ。"""
    text = await _generate(
        monkeypatch,
        [_result(detected_name="不用品A", attributes={}, initial_condition=ItemCondition.GOOD)],
    )
    assert "AI 検出品目: 不用品A。" in text
    assert "（" not in text.split("AI 検出品目:")[1]


async def test_empty_label_photo_is_skipped(monkeypatch):
    """detected_name/detected_category_labelがともに空の写真はスキップされる。"""
    empty = _result(detected_name="", detected_category_label=None)
    named = _result(detected_name="椅子", attributes={}, initial_condition=ItemCondition.GOOD)
    text = await _generate(monkeypatch, [empty, named])
    assert "AI 検出品目: 椅子。" in text


async def test_analyze_failure_on_one_photo_does_not_drop_others(monkeypatch):
    """複数枚のうち1枚が解析失敗しても、残りの検出結果はai_summaryに反映される。"""
    ok = _result(detected_name="テーブル", attributes={}, initial_condition=ItemCondition.GOOD)
    mock = AsyncMock(side_effect=[RuntimeError("boom"), ok])
    monkeypatch.setattr(summary_module, "analyze_image", mock)
    text = await summary_module.generate_case_summary(
        purpose="不用品処分",
        housing_type=None,
        floor_plan=None,
        photo_urls=["https://example.com/a.jpg", "https://example.com/b.jpg"],
    )
    assert "AI 検出品目: テーブル。" in text


async def test_all_photos_fail_returns_fallback_only(monkeypatch):
    """全写真が解析失敗した場合はフォールバック文のみを返す(AI検出品目セクションなし)。"""
    mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(summary_module, "analyze_image", mock)
    text = await summary_module.generate_case_summary(
        purpose="不用品処分",
        housing_type=None,
        floor_plan=None,
        photo_urls=["https://example.com/a.jpg"],
    )
    assert "AI 検出品目" not in text
    assert "利用目的: 不用品処分。" in text


class TestSafeAttr:
    """_safe_attr: 画像内の偽装テキストをai_summaryへ混入させないためのサニタイザ。"""

    def test_plain_brand_name_passes(self):
        assert summary_module._safe_attr("Apple") == "Apple"

    def test_japanese_brand_name_passes(self):
        assert summary_module._safe_attr("ソニー") == "ソニー"

    def test_none_returns_none(self):
        assert summary_module._safe_attr(None) is None

    def test_empty_string_returns_none(self):
        assert summary_module._safe_attr("") is None

    def test_url_is_rejected(self):
        assert summary_module._safe_attr("https://evil.example/phish") is None

    def test_www_domain_is_rejected(self):
        assert summary_module._safe_attr("www.evil-example.com") is None

    def test_email_like_string_is_rejected(self):
        assert summary_module._safe_attr("contact@evil.example") is None

    def test_overlong_value_is_rejected(self):
        assert summary_module._safe_attr("A" * 200) is None

    def test_control_characters_are_stripped_then_validated(self):
        # 制御文字除去後に許容パターンへ一致すれば通過する。
        assert summary_module._safe_attr("Apple\x00\x01") == "Apple"


async def test_suspicious_attribute_is_not_embedded_in_summary(monkeypatch):
    """_safe_attrで弾かれた値はai_summaryに現れない(セキュリティレビューMedium-1対応の回帰テスト)。"""
    result = _result(
        detected_name="家電A",
        attributes={"brand": "https://evil.example/phish", "model_name": None},
        initial_condition=ItemCondition.GOOD,
    )
    text = await _generate(monkeypatch, [result])
    assert "evil.example" not in text
    assert "AI 検出品目: 家電A。" in text


async def test_photo_url_for_ai_skips_https_raw_url_without_calling_vision(
    monkeypatch, caplog
):
    """R3再レビュー Medium対応: ローカル保存ファイルが解決できず raw_url が
    https:// の場合、vision.analyze_image は N-7対応で https を全面拒否する
    設計になっているため、そのまま渡さず None を返して AI 解析をスキップする
    （案件作成自体は失敗させない）。
    """
    import logging

    monkeypatch.setattr(summary_module.storage, "file_path", lambda storage_key: None)

    with caplog.at_level(logging.WARNING):
        ref = await summary_module.photo_url_for_ai(
            "some-storage-key", "https://example.com/photo.jpg"
        )
    assert ref is None
    assert any(
        "photo_url_for_ai" in rec.message and "https" in rec.message
        for rec in caplog.records
    )


async def test_photo_url_for_ai_returns_none_when_no_local_file_and_no_raw_url(
    monkeypatch,
):
    """raw_url も無い（None）場合も同様に None を返す（従来通りの挙動を維持）。"""
    monkeypatch.setattr(summary_module.storage, "file_path", lambda storage_key: None)
    ref = await summary_module.photo_url_for_ai("some-storage-key", None)
    assert ref is None
