"""Integration tests for FastAPI endpoints using httpx.AsyncClient."""
from __future__ import annotations
import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.router import api_router
from app.config import Settings
from app.db.models.assessment import Assessment, AssessmentRecommendation
from app.db.models.defect import DefectEvidence
from app.db.models.enums import AssessmentStatus, CategoryTier, ItemCondition
from app.db.models.item import Item
from app.db.session import get_session
from app.main import create_app
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup_and_auth(client: AsyncClient, email: str = "analyze-user@example.com") -> dict[str, str]:
    """/analyze は認証必須（R3-operator ADD-1対応）のため、テスト用ユーザーを作成する。"""
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return _auth(r.json()["access_token"])

# --- /health ---
async def test_health_200(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200

async def test_health_status_ok(client: AsyncClient):
    r = await client.get("/health")
    assert r.json() == {"status": "ok"}

# --- /analyze ---
async def test_analyze_requires_authentication_401(client: AsyncClient):
    """R3-operator ADD-1対応: 無認証での /analyze 呼び出しは401（従来は無認証で200）。"""
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        r = await client.post("/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc"})
    assert r.status_code == 401
    m.assert_not_awaited()

async def test_analyze_200(client: AsyncClient):
    headers = await _signup_and_auth(client)
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        r = await client.post(
            "/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc"}, headers=headers
        )
    assert r.status_code == 200

async def test_analyze_returns_item_id(client: AsyncClient):
    headers = await _signup_and_auth(client, "analyze-user-id@example.com")
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        r = await client.post(
            "/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc"}, headers=headers
        )
    data = r.json()
    assert "item_id" in data
    uuid.UUID(data["item_id"])

async def test_analyze_response_fields(client: AsyncClient):
    headers = await _signup_and_auth(client, "analyze-user-fields@example.com")
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        r = await client.post(
            "/api/v1/analyze", json={"base_image": "data:image/jpeg;base64,abc"}, headers=headers
        )
    data = r.json()
    assert data["detected_name"] == "iPhone 15 Pro 256GB Space Black"
    assert data["category_tier"] == "high_value_standard"
    assert data["initial_condition"] == "good"

@pytest.mark.parametrize(
    "base_image",
    ["https://example.com/item.jpg", "http://example.com/item.jpg", "HTTPS://EXAMPLE.COM/item.jpg"],
)
async def test_analyze_rejects_external_url_422(client: AsyncClient, base_image: str):
    """security review M-5対応: 外部URL（http/https）は422で拒否し、base64のみ受理する。"""
    headers = await _signup_and_auth(client, "analyze-user-url-reject@example.com")
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        r = await client.post(
            "/api/v1/analyze", json={"base_image": base_image}, headers=headers
        )
    assert r.status_code == 422, r.text
    m.assert_not_awaited()


async def test_analyze_vision_called_with_image(client: AsyncClient):
    headers = await _signup_and_auth(client, "analyze-user-called@example.com")
    with patch("app.api.v1.endpoints.analyze.analyze_image", new_callable=AsyncMock) as m:
        m.return_value = _vision_result()
        await client.post(
            "/api/v1/analyze",
            json={"base_image": "data:image/jpeg;base64,abc123"},
            headers=headers,
        )
    m.assert_awaited_once_with("data:image/jpeg;base64,abc123")

# --- 旧 AssetWise 査定 API（2026-09-27 撤去）---
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


async def _create_assessment(db_session: AsyncSession, item: Item) -> Assessment:
    """撤去済み /estimate が従来生成していたのと同じ形の Assessment を直接 DB に作る。"""
    assessment = Assessment(
        item_id=item.id,
        status=AssessmentStatus.COMPLETED,
        estimated_price_min=64000,
        estimated_price_max=64000,
        price_currency="JPY",
    )
    db_session.add(assessment)
    await db_session.commit()
    await db_session.refresh(assessment)
    return assessment


async def _count_rows(db_session: AsyncSession, model: type) -> int:
    return await db_session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/estimate"),
        ("GET", "/api/v1/assessments/{assessment_id}"),
        ("POST", "/api/v1/assessments/{assessment_id}/defects"),
    ],
)
async def test_removed_assetwise_routes_return_404(client: AsyncClient, method: str, path: str):
    """2026-09-27 に撤去した3エンドポイントは、401/405/422 ではなく404（ルート不在）を返す。"""
    resolved_path = path.format(assessment_id=uuid.uuid4())
    r = await client.request(method, resolved_path, json={} if method != "GET" else None)
    assert r.status_code == 404, r.text


async def test_removed_estimate_endpoint_404_and_no_rows_created_for_existing_item(
    client: AsyncClient, db_session: AsyncSession
):
    """実在する item_id・正しい形式のJSONで送っても404になり、assessments/recommendationsは増えない。"""
    item = await _create_item(db_session)
    assessments_before = await _count_rows(db_session, Assessment)
    recommendations_before = await _count_rows(db_session, AssessmentRecommendation)

    r = await client.post(
        "/api/v1/estimate", json={"item_id": str(item.id), "condition": "good"}
    )

    assert r.status_code == 404, r.text
    assert await _count_rows(db_session, Assessment) == assessments_before
    assert await _count_rows(db_session, AssessmentRecommendation) == recommendations_before


async def test_removed_defects_endpoint_404_and_no_rows_created_for_existing_assessment(
    client: AsyncClient, db_session: AsyncSession
):
    """実在する assessment_id・正しい形式のJSONで送っても404になり、defect_evidencesは増えない。"""
    item = await _create_item(db_session)
    assessment = await _create_assessment(db_session, item)
    defects_before = await _count_rows(db_session, DefectEvidence)

    r = await client.post(
        f"/api/v1/assessments/{assessment.id}/defects",
        json={"defect_image": "data:image/jpeg;base64,abc", "description": "左側面に傷"},
    )

    assert r.status_code == 404, r.text
    assert await _count_rows(db_session, DefectEvidence) == defects_before


def test_removed_assetwise_paths_absent_from_production_openapi_and_routes():
    """本番相当設定のアプリで /estimate・/assessments 系のパスが OpenAPI・routes のいずれにも無い。"""
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        jwt_secret="a" * 64,
        ALLOWED_ORIGINS="https://sokuri.vercel.app",
    )
    app = create_app(settings)

    def _is_removed_path(path: str) -> bool:
        return path == "/api/v1/estimate" or path.startswith("/api/v1/assessments")

    openapi_paths = app.openapi()["paths"]
    assert not any(_is_removed_path(p) for p in openapi_paths)

    route_paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert not any(_is_removed_path(p) for p in route_paths)
