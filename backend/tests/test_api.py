"""Integration tests for FastAPI endpoints using httpx.AsyncClient."""
from __future__ import annotations
import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.router import api_router
from app.db.models.enums import CategoryTier, ItemCondition, RoutingMethod
from app.db.models.item import Item
from app.db.session import get_session
from app.services.vision import VisionResult

def create_test_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    return app

@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    test_app = create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac

def _vision_result():
    return VisionResult(
        detected_name="iPhone 15 Pro 256GB Space Black",
        detected_category_label="Smartphone",
        category_tier=CategoryTier.HIGH_VALUE_STANDARD,
        initial_condition=ItemCondition.GOOD,
        condition_confidence=0.85,
        attributes={"brand": "Apple"},
        base_market_price_jpy=80000,
        image_object_key="mock/key.jpg",
    )

# --- /health ---
async def test_health_200(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200

async def test_health_status_ok(client: AsyncClient):
    r = await client.get("/health")
    assert r.json() == {"status": "ok"}

# --- /analyze ---
async def test_analyze_200(client: AsyncClient):
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        r = await client.post("/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc"})
    assert r.status_code == 200

async def test_analyze_returns_item_id(client: AsyncClient):
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        r = await client.post("/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc"})
    data = r.json()
    assert "item_id" in data
    uuid.UUID(data["item_id"])

async def test_analyze_response_fields(client: AsyncClient):
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        r = await client.post("/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc"})
    data = r.json()
    assert data["detected_name"] == "iPhone 15 Pro 256GB Space Black"
    assert data["category_tier"] == "high_value_standard"
    assert data["initial_condition"] == "good"

async def test_analyze_vision_called_with_image(client: AsyncClient):
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        await client.post("/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc123"})
    m.assert_awaited_once_with("data:image/jpeg;base64,abc123")

# --- /estimate ---
async def _create_item(db_session: AsyncSession) -> Item:
    item = Item(
        category_tier=CategoryTier.HIGH_VALUE_STANDARD,
        detected_name="iPhone 15 Pro",
        detected_category_label="Smartphone",
        condition=ItemCondition.GOOD,
        image_object_key="mock/key.jpg",
        attributes={"base_market_price_jpy": 80000},
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item

async def test_estimate_200(client: AsyncClient, db_session: AsyncSession):
    item = await _create_item(db_session)
    r = await client.post("/api/v1/estimate", json={"item_id": str(item.id), "condition": "good"})
    assert r.status_code == 200

async def test_estimate_has_assessment_id(client: AsyncClient, db_session: AsyncSession):
    item = await _create_item(db_session)
    r = await client.post("/api/v1/estimate", json={"item_id": str(item.id), "condition": "good"})
    data = r.json()
    assert "assessment_id" in data
    uuid.UUID(data["assessment_id"])

async def test_estimate_price_calculation(client: AsyncClient, db_session: AsyncSession):
    item = await _create_item(db_session)
    r = await client.post("/api/v1/estimate", json={"item_id": str(item.id), "condition": "good"})
    data = r.json()
    assert data["base_market_price"] == 80000
    assert data["estimated_price"] == 64000  # 80000 * 0.8

async def test_estimate_404_unknown_item(client: AsyncClient):
    r = await client.post("/api/v1/estimate", json={"item_id": str(uuid.uuid4()), "condition": "good"})
    assert r.status_code == 404

async def test_estimate_422_unknown_condition(client: AsyncClient, db_session: AsyncSession):
    item = await _create_item(db_session)
    r = await client.post("/api/v1/estimate", json={"item_id": str(item.id), "condition": "unknown"})
    assert r.status_code == 422

async def test_estimate_recommendations_is_list(client: AsyncClient, db_session: AsyncSession):
    item = await _create_item(db_session)
    r = await client.post("/api/v1/estimate", json={"item_id": str(item.id), "condition": "like_new"})
    assert isinstance(r.json()["recommendations"], list)

async def test_estimate_with_mocked_routing(client: AsyncClient, db_session: AsyncSession):
    from app.services.routing import RoutingResult
    item = await _create_item(db_session)
    mock_result = RoutingResult(method=RoutingMethod.RULE, recommendations=[])
    with patch("app.api.v1.endpoints.estimate.evaluate_routing_rules", new_callable=AsyncMock) as m:
        m.return_value = mock_result
        r = await client.post("/api/v1/estimate", json={"item_id": str(item.id), "condition": "good"})
    assert r.status_code == 200
    assert r.json()["routing_method"] == "rule"
    m.assert_awaited_once()
