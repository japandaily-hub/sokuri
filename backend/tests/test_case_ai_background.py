"""案件作成の AI 解析バックグラウンド化・冪等キー・業者一覧のページングの統合テスト。

対象: r6-backend.md H-1（リクエスト内 AI 解析による二重案件）/ r6-verify-backend.md ADD-1
（AI 解析中の DB コネクション占有）/ M-5（業者向け案件一覧の LIMIT なし）/
r6-verify-web.md A1（案件登録完了通知が notify 直呼びで LINE 専用ユーザーに届かない）。

前提: ASGITransport は BackgroundTasks の完了まで待つため、``POST /cases`` の応答を
受け取った時点で解析タスクは既に走り終えている。作成応答（ai_status="pending"）と
その後の詳細取得（"done"/"failed"）を同一テスト内で検証できる。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.session import get_session
from app.services import summary as summary_module


def create_test_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _case_payload(**overrides: object) -> dict:
    payload: dict = {
        "purpose": "片付け整理",
        "prefecture": "神奈川県",
        "city": "横浜市青葉区",
        "address_detail": "桜丘1-2-3",
        "housing_type": "マンション",
        "floor_plan": "2LDK",
        "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0}],
    }
    payload.update(overrides)
    return payload


async def _signup_user(client: AsyncClient, email: str = "ai_bg_user@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "password123"}
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


# ──────────────── H-1 / ADD-1: AI 解析のバックグラウンド化 ────────────────


async def test_create_case_returns_pending_and_completes_in_background(
    client: AsyncClient,
):
    """作成応答は ai_status="pending"、解析完了後の詳細取得は "done" になる。"""
    token = await _signup_user(client)
    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    assert r.status_code == 201, r.text
    created = r.json()
    # 応答は解析を待たない。要約欄は暫定のフォールバック文で埋まっている。
    assert created["ai_status"] == "pending"
    assert created["ai_summary"]

    r = await client.get(f"/api/v1/cases/{created['id']}", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "done"


async def test_ai_analysis_failure_marks_case_failed_but_keeps_case_usable(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """解析が例外で落ちても案件は有効なまま残り、ai_status="failed" になる。"""
    token = await _signup_user(client, "ai_fail_user@example.com")

    async def _boom(**_kwargs: object) -> tuple[str, list]:
        raise RuntimeError("gemini exploded")

    # items 経路（generate_case_ai）を失敗させる。
    monkeypatch.setattr("app.api.v1.endpoints.cases.generate_case_ai", _boom)

    payload = _case_payload(
        photos=[],
        items=[{"name": "冷蔵庫", "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg"}]}],
    )
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]

    r = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["ai_status"] == "failed"
    # 案件自体は open のまま有効で、フォールバック要約が残っている。
    assert detail["status"] == "open"
    assert detail["ai_summary"]

    row = await db_session.scalar(select(Case).where(Case.id == uuid.UUID(case_id)))
    assert row is not None
    assert "RuntimeError" in (row.ai_failed_reason or "")


async def test_ai_analysis_respects_overall_deadline(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """全体デッドラインを超過した解析は failed に落ち、案件作成自体は成功のまま。

    本番のデッドラインは 120 秒。テストでは 50ms に縮め、解析側を意図的に遅くして
    「デッドラインが実際に効いていること」を実時間を待たずに確認する。
    """
    token = await _signup_user(client, "ai_deadline_user@example.com")

    async def _slow(**_kwargs: object) -> str:
        await asyncio.sleep(5)
        return "遅すぎる要約"

    monkeypatch.setattr("app.api.v1.endpoints.cases._AI_ANALYSIS_DEADLINE_SEC", 0.05)
    monkeypatch.setattr("app.api.v1.endpoints.cases.generate_case_summary", _slow)

    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]

    r = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ai_status"] == "failed"
    row = await db_session.scalar(select(Case).where(Case.id == uuid.UUID(case_id)))
    assert row is not None and "TimeoutError" in (row.ai_failed_reason or "")


async def test_create_case_notifies_via_dispatch_not_direct_mail(
    client: AsyncClient, monkeypatch
):
    """案件登録完了通知は notify_dispatch 経由で送られる（r6-verify-web A1）。"""
    token = await _signup_user(client, "ai_notify_user@example.com")
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_case_created", dispatch_mock
    )

    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    assert r.status_code == 201, r.text
    dispatch_mock.assert_awaited_once()
    # 第1引数=line_user_id / 第2引数=email（notify_dispatch の引数規約）。
    args = dispatch_mock.await_args.args
    assert args[0] is None
    assert args[1] == "ai_notify_user@example.com"
    assert args[2] == r.json()["id"]


# ──────────────── H-1: 冪等キー ────────────────


async def test_same_idempotency_key_returns_existing_case_with_200(client: AsyncClient):
    """同一 idempotency_key の再送信は新規作成せず 200 で同じ案件を返す。"""
    token = await _signup_user(client, "idem_user@example.com")
    key = str(uuid.uuid4())

    first = await client.post(
        "/api/v1/cases", json=_case_payload(idempotency_key=key), headers=_auth(token)
    )
    assert first.status_code == 201, first.text

    # 写真キーは新しいものにする（DB の storage_key UNIQUE を踏まないため）。
    # 冪等キー一致の時点で写真を見ずに既存案件を返すことの確認でもある。
    second = await client.post(
        "/api/v1/cases", json=_case_payload(idempotency_key=key), headers=_auth(token)
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    r = await client.get("/api/v1/cases", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


async def test_idempotency_key_is_scoped_per_user(client: AsyncClient):
    """他人が同じ冪等キーを送っても、その人の案件は新規作成される。"""
    key = str(uuid.uuid4())
    token_a = await _signup_user(client, "idem_a@example.com")
    token_b = await _signup_user(client, "idem_b@example.com")

    r1 = await client.post(
        "/api/v1/cases", json=_case_payload(idempotency_key=key), headers=_auth(token_a)
    )
    assert r1.status_code == 201, r1.text
    r2 = await client.post(
        "/api/v1/cases", json=_case_payload(idempotency_key=key), headers=_auth(token_b)
    )
    assert r2.status_code == 201, r2.text
    assert r1.json()["id"] != r2.json()["id"]


async def test_without_idempotency_key_duplicate_posts_create_two_cases(
    client: AsyncClient,
):
    """冪等キー未指定時は従来どおり毎回新規作成する（既存クライアント互換）。"""
    token = await _signup_user(client, "no_idem_user@example.com")
    r1 = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    r2 = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


# ──────────────── M-5: 業者向け案件一覧のページング ────────────────


async def test_operator_case_list_supports_limit_and_offset(
    client: AsyncClient, db_session: AsyncSession
):
    """業者一覧に limit/offset が効き、応答形状（list）は変わらない。"""
    token = await _signup_user(client, "list_user@example.com")
    created_ids: list[str] = []
    for _ in range(3):
        r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
        assert r.status_code == 201, r.text
        created_ids.append(r.json()["id"])

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "一覧テスト業者",
            "email": "list_op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    op_token = r.json()["access_token"]
    operator = await db_session.scalar(
        select(Operator).where(Operator.contact_email == "list_op@example.com")
    )
    assert operator is not None

    r = await client.get("/api/v1/cases?limit=2", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    page1 = r.json()
    assert isinstance(page1, list) and len(page1) == 2

    r = await client.get("/api/v1/cases?limit=2&offset=2", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    page2 = r.json()
    assert len(page2) == 1
    # ページ跨ぎで重複・取りこぼしが無い（created_at desc, id desc の安定順）。
    assert {c["id"] for c in page1}.isdisjoint({c["id"] for c in page2})
    assert {c["id"] for c in page1} | {c["id"] for c in page2} == set(created_ids)


async def test_operator_case_list_rejects_limit_over_max(client: AsyncClient):
    """limit の上限（200）超過は 422 で弾く（無制限クエリへの退行防止）。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "上限テスト業者",
            "email": "limit_op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    op_token = r.json()["access_token"]

    r = await client.get("/api/v1/cases?limit=201", headers=_auth(op_token))
    assert r.status_code == 422


async def test_user_case_list_is_not_paginated(client: AsyncClient):
    """依頼者側の一覧は従来どおり自分の案件を全件返す（limit は業者分岐専用）。"""
    token = await _signup_user(client, "own_list_user@example.com")
    for _ in range(3):
        r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
        assert r.status_code == 201, r.text

    r = await client.get("/api/v1/cases?limit=1", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3
    assert summary_module.build_fallback_summary is summary_module._fallback_summary


# ──────────────── H2: pending 放置の回収（r6-review） ────────────────


async def test_get_and_list_reap_stale_pending_case_to_failed(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """作成から10分超 pending のまま放置された案件は、GET/一覧の応答時に failed へ倒れる。

    BackgroundTasks が失われて誰も ai_status を更新しない状況（デプロイ・OOM 等）を
    再現するため、_run_case_ai_analysis 自体を no-op に差し替えて ai_status="pending"
    のまま作成する。フォールバック要約（作成時に必ず書かれる）は failed になっても
    消えないことも合わせて確認する。
    """
    from app.api.v1.endpoints import cases as cases_module

    async def _noop(case_id: object) -> None:
        return None

    monkeypatch.setattr(cases_module, "_run_case_ai_analysis", _noop)

    token = await _signup_user(client, "stale_pending_user@example.com")
    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    assert r.json()["ai_status"] == "pending"
    fallback_summary = r.json()["ai_summary"]
    assert fallback_summary

    # 作成から10分超に見せかける（_AI_STALE_PENDING_WINDOW=10分）。
    row = await db_session.scalar(select(Case).where(Case.id == uuid.UUID(case_id)))
    assert row is not None
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    await db_session.commit()

    r = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["ai_status"] == "failed"
    # 案件自体は有効なまま、作成時のフォールバック要約が残っている。
    assert detail["status"] == "open"
    assert detail["ai_summary"] == fallback_summary

    row = await db_session.scalar(select(Case).where(Case.id == uuid.UUID(case_id)))
    assert row is not None
    assert row.ai_status == "failed"
    assert row.ai_failed_reason == "stale"

    # 一覧側（依頼者向け）でも同じ遅延回収が効く。
    token2 = await _signup_user(client, "stale_pending_user2@example.com")
    r = await client.post(
        "/api/v1/cases", json=_case_payload(), headers=_auth(token2)
    )
    assert r.status_code == 201, r.text
    case_id2 = r.json()["id"]
    row2 = await db_session.scalar(select(Case).where(Case.id == uuid.UUID(case_id2)))
    assert row2 is not None
    row2.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    await db_session.commit()

    r = await client.get("/api/v1/cases", headers=_auth(token2))
    assert r.status_code == 200, r.text
    listed = next(c for c in r.json() if c["id"] == case_id2)
    assert listed["ai_status"] == "failed"
    assert listed["ai_summary"]


async def test_startup_sweep_reaps_only_stale_pending_cases(
    client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    """main.py lifespan から呼ばれる起動時スイープが、10分超 pending のみを一括回収する。

    まだ猶予内の pending や既に done/failed の案件は変更しない。
    """
    from app.api.v1.endpoints import cases as cases_module

    async def _noop(case_id: object) -> None:
        return None

    monkeypatch.setattr(cases_module, "_run_case_ai_analysis", _noop)

    token = await _signup_user(client, "sweep_user@example.com")

    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    assert r.status_code == 201, r.text
    stale_id = uuid.UUID(r.json()["id"])

    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(token))
    assert r.status_code == 201, r.text
    fresh_id = uuid.UUID(r.json()["id"])

    row = await db_session.scalar(select(Case).where(Case.id == stale_id))
    assert row is not None
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    await db_session.commit()

    count = await cases_module.sweep_stale_pending_ai(db_session)
    assert count == 1

    stale_row = await db_session.scalar(select(Case).where(Case.id == stale_id))
    fresh_row = await db_session.scalar(select(Case).where(Case.id == fresh_id))
    assert stale_row is not None and stale_row.ai_status == "failed"
    assert stale_row.ai_failed_reason == "stale"
    assert fresh_row is not None and fresh_row.ai_status == "pending"
