"""Gemini へ送る画像の単一の関門（vision.analyze_image）でメタデータを除く回帰テスト。

security review Low: ``POST /api/v1/analyze`` は利用者が送った画像（data URL）を、位置情報
（Exif の GPS 等）を含んだまま Gemini へ渡していた。案件フロー（summary.photo_url_for_ai）は
送る前に除去済みだが、全ての Gemini 送信が通る ``analyze_image`` で除去し、MIME も申告ではなく
実バイトから判定する。除去を保証できない画像は送らず ImageInputError（ValueError の派生。
/analyze は 422 で固定文言を返す）にする。入力に起因しない ValueError は固定文言で返す。
"""

from __future__ import annotations

import base64
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import vision as vision_module
from tests.test_summary_photo_metadata import (
    _BROKEN_GPS_JPEG,
    _CLEAN_JPEG,
    _GPS_JPEG,
    _GPS_LATITUDE,
    _NOT_AN_IMAGE,
)


def _data_url(data: bytes, declared_mime: str = "image/jpeg") -> str:
    return f"data:{declared_mime};base64,{base64.b64encode(data).decode('ascii')}"


def _gemini_response() -> MagicMock:
    response = MagicMock()
    response.text = (
        '{"detected_name": "テスト品目", "detected_category_label": null, '
        '"category_tier": "low_value_daily", "initial_condition": "good", '
        '"condition_confidence": 0.8, "attributes": {}, "base_market_price_jpy": 1000}'
    )
    return response


@pytest.fixture(autouse=True)
def _reset_gemini_semaphore(monkeypatch: pytest.MonkeyPatch) -> None:
    """モジュールレベルの Semaphore をテストごとにリセットする（test_vision_retry.py と同じ理由）。"""
    monkeypatch.setattr(vision_module, "_gemini_semaphore", None)


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """genai.Client と Part.from_bytes を差し替え、Gemini へ渡るバイト列と MIME を記録する。"""
    sent: dict[str, Any] = {}
    generate_content = AsyncMock(return_value=_gemini_response())
    fake_client = MagicMock()
    fake_client.aio.models.generate_content = generate_content
    monkeypatch.setattr(vision_module.genai, "Client", MagicMock(return_value=fake_client))

    def fake_from_bytes(*, data: bytes, mime_type: str) -> object:
        sent["data"] = data
        sent["mime_type"] = mime_type
        return object()

    monkeypatch.setattr(vision_module.types.Part, "from_bytes", staticmethod(fake_from_bytes))
    sent["generate_content"] = generate_content
    return sent


async def test_analyze_image_sends_bytes_without_gps(gemini: dict[str, Any]):
    """GPS 付き JPEG を渡しても、Gemini へは除去後のバイト列だけが渡る。"""
    result = await vision_module.analyze_image(_data_url(_GPS_JPEG))

    assert result.detected_name == "テスト品目"
    assert gemini["data"] == _CLEAN_JPEG
    assert _GPS_LATITUDE not in gemini["data"]
    assert b"SENTINEL" not in gemini["data"]
    assert gemini["mime_type"] == "image/jpeg"


async def test_analyze_image_uses_mime_of_actual_bytes(gemini: dict[str, Any]):
    """data URL の申告（image/png）ではなく、実バイトから判定した形式（JPEG）で送る。"""
    await vision_module.analyze_image(_data_url(_GPS_JPEG, declared_mime="image/png"))

    assert gemini["mime_type"] == "image/jpeg"


@pytest.mark.parametrize(
    "payload",
    [_NOT_AN_IMAGE, _BROKEN_GPS_JPEG],
    ids=["not_an_image", "broken_jpeg_before_scan"],
)
async def test_analyze_image_rejects_images_that_cannot_be_stripped(
    gemini: dict[str, Any], payload: bytes
):
    """JPEG / PNG / WebP でない画像・構造を解釈できない画像は、元のバイト列へフォールバック
    せず ImageInputError（/analyze は 422）。Gemini は呼ばれない。"""
    with pytest.raises(vision_module.ImageInputError):
        await vision_module.analyze_image(_data_url(payload))

    gemini["generate_content"].assert_not_called()
    assert "data" not in gemini


@pytest.mark.parametrize(
    "base_image",
    [
        "data:image/jpeg;base64,",  # 中身が空
        "data:image/jpeg;base64,@@@not-base64@@@",  # base64 でない文字
        "data:image/jpeg;base64",  # カンマが無い（data URL として壊れている）
    ],
    ids=["empty", "not_base64", "no_comma"],
)
async def test_analyze_image_rejects_malformed_data_urls(gemini: dict[str, Any], base_image: str):
    with pytest.raises(vision_module.ImageInputError):
        await vision_module.analyze_image(base_image)
    gemini["generate_content"].assert_not_called()


async def test_analyze_image_rejects_oversized_image(
    gemini: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """復号後のサイズが写真アップロードと同じ上限（MAX_UPLOAD_BYTES）を超えたら送らない。"""
    monkeypatch.setattr(vision_module, "MAX_UPLOAD_BYTES", len(_CLEAN_JPEG) - 1)
    with pytest.raises(vision_module.ImageInputError, match="大きすぎます"):
        await vision_module.analyze_image(_data_url(_CLEAN_JPEG))
    gemini["generate_content"].assert_not_called()


@pytest.mark.parametrize(("fmt", "mime_type"), [("png", "image/png"), ("webp", "image/webp")])
async def test_analyze_image_strips_png_and_webp_metadata(
    gemini: dict[str, Any], fmt: str, mime_type: str
):
    """PNG・WebP もメタデータを除いたバイト列と、実バイトから判定した MIME で送る。"""
    from tests.test_image_metadata_strip import _png_with_metadata, _webp_with_metadata

    original, expected = _png_with_metadata() if fmt == "png" else _webp_with_metadata()
    await vision_module.analyze_image(_data_url(original, declared_mime="image/jpeg"))

    assert gemini["data"] == expected
    assert gemini["mime_type"] == mime_type


def test_analyze_request_limits_base_image_length():
    """/analyze の入力は復号後 10MB（写真アップロードと同じ上限）相当の長さまでに制限する。"""
    from app.schemas import AnalyzeRequest
    from app.services.storage import MAX_UPLOAD_BYTES

    max_length = next(
        m.max_length for m in AnalyzeRequest.model_fields["base_image"].metadata if hasattr(m, "max_length")
    )
    assert MAX_UPLOAD_BYTES * 4 // 3 <= max_length <= MAX_UPLOAD_BYTES * 4 // 3 + 1024


# ──────────────────────────── /api/v1/analyze（エンドポイント経由） ────────────────────────────


async def _analyze_via_api(db_session, base_image: str):
    """実物の analyze_image を通して /analyze を呼び、応答を返す（Gemini は gemini フィクスチャで差し替え）。"""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.v1.router import api_router
    from app.db.session import get_session

    app = FastAPI()

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/signup",
            json={"email": f"analyze-{uuid.uuid4().hex[:8]}@example.com", "password": "password123", "name": "解析 太郎"},
        )
        assert r.status_code == 201, r.text
        token = r.json()["access_token"]
        return await client.post(
            "/api/v1/analyze",
            json={"base_image": base_image},
            headers={"Authorization": f"Bearer {token}"},
        )


async def test_analyze_endpoint_rejects_non_image_without_creating_item(db_session, gemini):
    """画像でない入力は 422（固定文言）で、Item は作られず Gemini も呼ばれない。"""
    from sqlalchemy import func, select

    from app.db.models.item import Item

    r = await _analyze_via_api(db_session, _data_url(_NOT_AN_IMAGE))

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "対応していない画像形式です（JPEG・PNG・WebP のみ）。"
    assert await db_session.scalar(select(func.count()).select_from(Item)) == 0
    gemini["generate_content"].assert_not_called()


async def test_analyze_endpoint_hides_internal_value_error_messages(db_session, monkeypatch):
    """入力に起因しない ValueError（Gemini 応答の解析失敗など）は、生のメッセージを返さず固定文言。"""
    monkeypatch.setattr(
        "app.api.v1.endpoints.analyze.analyze_image",
        AsyncMock(side_effect=ValueError("internal detail: raw model output {...}")),
    )

    r = await _analyze_via_api(db_session, _data_url(_CLEAN_JPEG))

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "画像を解析できませんでした。別の写真でお試しください。"
    assert "internal detail" not in r.text
