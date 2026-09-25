"""AI 解析（Gemini）へ送る案件写真のメタデータ除去（services/summary.py）のテスト。

2026-09-25 セキュリティレビューの残り（docs/TODO.md の⑤）: 受信時の除去（db002b2）より前に
保存された写真は Exif の GPS 等を含みうるが、``summary.photo_url_for_ai`` は保存済みの
バイト列をそのまま base64 化して Gemini（外部の AI サービス）へ送っていた。送る直前に配信時と
同じ ``strip_image_metadata`` を通し、除去できない写真はその 1 枚だけ解析対象から外す。

Gemini 呼び出し（``summary.analyze_image``）はモックし、実際に送られるデータ URL を復号して
検証する。写真は tmp_path をルートにしたローカルストレージへ実際に保存する
（tests/test_image_metadata_strip.py の配信テストと同じ作法）。
"""

from __future__ import annotations

import base64
import logging
import struct
import threading
import uuid

import pytest

from app.config import get_settings
from app.db.models.enums import CategoryTier, ItemCondition
from app.services import summary as summary_module
from app.services.vision import VisionResult

# ──────────────────────────── 合成画像 ────────────────────────────

# 出力（Gemini へ送るバイト列）に残ってはならない目印。
_MAKE_SENTINEL = b"SENTINEL-CAMERA-MAKE\x00"
_GPS_LATITUDE = struct.pack("<6I", 35, 1, 39, 1, 294057, 10000)  # 北緯 35°39'29.4057"


def _seg(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def _gps_exif_app1() -> bytes:
    """IFD0（Make・GPS IFD ポインタ）と GPS IFD（緯度）を持つ Exif APP1（リトルエンディアン）。"""
    gps_ifd_offset = 8 + 2 + 12 * 2 + 4
    make_offset = gps_ifd_offset + 2 + 12 * 2 + 4
    latitude_offset = make_offset + len(_MAKE_SENTINEL)
    tiff = (
        b"II*\x00\x08\x00\x00\x00"
        + struct.pack("<H", 2)
        + struct.pack("<HHII", 0x010F, 2, len(_MAKE_SENTINEL), make_offset)  # Make
        + struct.pack("<HHII", 0x8825, 4, 1, gps_ifd_offset)  # GPS IFD
        + struct.pack("<I", 0)
        + struct.pack("<H", 2)
        + struct.pack("<HHI4s", 0x0001, 2, 2, b"N")  # GPSLatitudeRef（"N\0" を左詰め）
        + struct.pack("<HHII", 0x0002, 5, 3, latitude_offset)  # GPSLatitude
        + struct.pack("<I", 0)
        + _MAKE_SENTINEL
        + _GPS_LATITUDE
    )
    return _seg(0xE1, b"Exif\x00\x00" + tiff)


_SOI, _EOI = b"\xff\xd8", b"\xff\xd9"
_DQT = _seg(0xDB, b"\x00" + bytes(range(1, 65)))
# 量子化表・フレーム・スキャン（スタッフィングを含むエントロピー符号データ）・EOI。
_JPEG_BODY = (
    _DQT
    + _seg(0xC0, b"\x08\x00\x10\x00\x10\x01\x01\x11\x00")
    + _seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    + b"\x12\x34\xff\x00\x56"
    + _EOI
)
# 除去後に送られるべきバイト列（Exif だけが消え、画像部分はバイト単位で同一）。
_CLEAN_JPEG = _SOI + _JPEG_BODY
# 対策前に保存された、GPS 付き Exif を持つ写真。
_GPS_JPEG = _SOI + _gps_exif_app1() + _JPEG_BODY
# 最初の SOS より前（GPS 付き Exif の直後の DQT の途中）で途切れた写真。除去を保証できない。
_BROKEN_GPS_JPEG = _SOI + _gps_exif_app1() + _DQT[:10]
_NOT_AN_IMAGE = b"not-an-image"


# ──────────────────────────── フィクスチャ・ヘルパー ────────────────────────────


@pytest.fixture
def tmp_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return tmp_path


def _store(tmp_storage, data: bytes) -> str:
    """ローカルストレージへ保存し、storage_key を返す。"""
    storage_key = f"{uuid.uuid4().hex}.jpg"
    (tmp_storage / storage_key).write_bytes(data)
    return storage_key


def _decode_data_url(ref: str) -> tuple[str, bytes]:
    """``data:<mime>;base64,<本体>`` を（mime, 復号したバイト列）に分ける。"""
    header, encoded = ref.split(",", 1)
    assert header.startswith("data:") and header.endswith(";base64")
    return header[len("data:") : -len(";base64")], base64.b64decode(encoded)


def _vision_result() -> VisionResult:
    return VisionResult(
        detected_name="テスト品目",
        detected_category_label=None,
        category_tier=CategoryTier.LOW_VALUE_DAILY,
        initial_condition=ItemCondition.GOOD,
        condition_confidence=0.9,
        attributes={},
        base_market_price_jpy=0,
        image_object_key="dummy-key",
    )


def _exclusion_messages(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "photo_url_for_ai" in record.getMessage() and "除去できない" in record.getMessage()
    ]


# ──────────────────────────── photo_url_for_ai ────────────────────────────


async def test_photo_url_for_ai_sends_bytes_without_gps(tmp_storage):
    """GPS 付きのまま保存された写真も、Gemini へは除去後のバイト列だけを送る（実体は書き換えない）。"""
    storage_key = _store(tmp_storage, _GPS_JPEG)

    ref = await summary_module.photo_url_for_ai(storage_key, None)

    assert ref is not None
    mime_type, sent = _decode_data_url(ref)
    assert mime_type == "image/jpeg"
    assert sent == _CLEAN_JPEG
    assert _GPS_LATITUDE not in sent
    assert b"SENTINEL" not in sent
    assert (tmp_storage / storage_key).read_bytes() == _GPS_JPEG


async def test_photo_url_for_ai_uses_mime_of_actual_bytes(tmp_storage):
    """拡張子 .jpg で保存された PNG は、実バイトから判定した image/png として送る
    （web は形式を判定できない写真を image/jpeg で presign するため、保存時の型は実体と
    食い違うことがある・security review Low）。"""
    import zlib

    def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
        + png_chunk(b"IEND", b"")
    )
    storage_key = _store(tmp_storage, png)  # 拡張子は .jpg（保存時の型は image/jpeg 扱い）

    ref = await summary_module.photo_url_for_ai(storage_key, None)

    assert ref is not None
    mime_type, sent = _decode_data_url(ref)
    assert mime_type == "image/png"
    assert sent == png


async def test_photo_url_for_ai_strips_off_the_event_loop_thread(tmp_storage, monkeypatch):
    """除去（CPU 処理）はイベントループのスレッドではなく、base64 化と同じワーカースレッドで行う。"""
    strip_threads: list[threading.Thread] = []
    original_strip = summary_module.strip_image_metadata

    def spy(data: bytes, ext: str) -> bytes:
        strip_threads.append(threading.current_thread())
        return original_strip(data, ext)

    monkeypatch.setattr(summary_module, "strip_image_metadata", spy)
    storage_key = _store(tmp_storage, _GPS_JPEG)

    assert await summary_module.photo_url_for_ai(storage_key, None) is not None
    assert len(strip_threads) == 1
    assert strip_threads[0] is not threading.current_thread()


@pytest.mark.parametrize(
    "stored",
    [_BROKEN_GPS_JPEG, _NOT_AN_IMAGE],
    ids=["jpeg-cut-before-scan-with-gps", "not-an-image"],
)
async def test_photo_url_for_ai_excludes_photo_that_cannot_be_stripped(
    tmp_storage, caplog, stored: bytes
):
    """除去できない写真は元のバイト列を送らず除外し（raw_url にも逃がさない）、マスク済みの
    storage_key で warning を 1 行出す。"""
    storage_key = _store(tmp_storage, stored)
    caplog.set_level(logging.WARNING, logger="app.services.summary")

    ref = await summary_module.photo_url_for_ai(storage_key, "https://example.com/raw.jpg")

    assert ref is None
    messages = _exclusion_messages(caplog)
    assert len(messages) == 1
    assert f"storage_key={storage_key[:8]}..." in messages[0]
    assert storage_key not in messages[0]
    assert "ImageMetadataError" in messages[0]


# ──────────────────────────── 案件の AI 解析（generate_case_ai） ────────────────────────────


async def test_generate_case_ai_sends_only_stripped_photos_and_skips_broken_ones(
    tmp_storage, monkeypatch, caplog
):
    """商品写真・未分類写真とも、Gemini へ送るのは除去後のバイト列だけ。壊れた写真はその 1 枚
    だけ外れ、同じ商品の 2 枚目・他の商品・未分類の他の写真は従来どおり解析される。"""
    sent: list[str] = []

    async def fake_analyze_image(ref: str) -> VisionResult:
        sent.append(ref)
        return _vision_result()

    monkeypatch.setattr(summary_module, "analyze_image", fake_analyze_image)
    caplog.set_level(logging.WARNING, logger="app.services.summary")
    broken_item_key = _store(tmp_storage, _BROKEN_GPS_JPEG)
    broken_ungrouped_key = _store(tmp_storage, _NOT_AN_IMAGE)

    case_summary, item_results = await summary_module.generate_case_ai(
        purpose="不用品処分",
        housing_type=None,
        floor_plan=None,
        items=[
            summary_module.ItemAnalysisInput(
                name=None, photo_refs=[(_store(tmp_storage, _GPS_JPEG), None)]
            ),
            # 1 枚目（代表）が壊れていても、2 枚目は送られる。
            summary_module.ItemAnalysisInput(
                name=None,
                photo_refs=[(broken_item_key, None), (_store(tmp_storage, _GPS_JPEG), None)],
            ),
        ],
        ungrouped_refs=[(broken_ungrouped_key, None), (_store(tmp_storage, _GPS_JPEG), None)],
    )

    assert len(sent) == 3  # 正常な写真 3 枚（商品 1・商品 2 の 2 枚目・未分類の 2 枚目）
    for ref in sent:
        mime_type, body = _decode_data_url(ref)
        assert mime_type == "image/jpeg"
        assert body == _CLEAN_JPEG
        assert _GPS_LATITUDE not in body
    assert [result.ai_detected_name for result in item_results] == ["テスト品目", "テスト品目"]
    assert "AI 検出品目: テスト品目。" in case_summary

    messages = _exclusion_messages(caplog)
    assert len(messages) == 2
    for storage_key in (broken_item_key, broken_ungrouped_key):
        assert any(f"storage_key={storage_key[:8]}..." in message for message in messages)
        assert all(storage_key not in message for message in messages)
