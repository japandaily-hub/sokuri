"""案件写真の商品ごとのアルバム化（CaseItem）機能の統合テスト。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_katadzuke_api.py と同様、各テストファイルは自己完結（ヘルパーを
ローカルに複製する既存スタイルを踏襲）。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.limits import MAX_ITEMS_PER_CASE, MAX_PHOTOS_PER_ITEM
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.case import CaseItem, CasePhoto
from app.db.models.enums import CategoryTier, ItemCondition
from app.db.session import get_session
from app.services import summary as summary_module
from app.services.vision import VisionResult


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
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def tmp_storage(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return tmp_path


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup_user(client: AsyncClient, email: str = "user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    from app.db.models.user import User

    admin = User(
        email="admin@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


async def _invite_code(client: AsyncClient, admin_token: str) -> str:
    r = await client.post(
        "/api/v1/admin/invites", json={}, headers=_auth(admin_token)
    )
    assert r.status_code == 201
    return r.json()["code"]


async def _verified_operator(
    client: AsyncClient, db_session: AsyncSession, admin_token: str, email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    code = await _invite_code(client, admin_token)
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": company,
            "email": email,
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    data = r.json()
    token, op_id = data["access_token"], data["operator"]["id"]
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    return token, op_id


def _photo(sort_order: int = 0) -> dict:
    return {"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": sort_order}


def _photo_with_file(tmp_storage, sort_order: int = 0) -> dict:
    """AI解析経路（photo_url_for_ai）が None を返さないよう、実ファイルを書き込む。"""
    key = f"{uuid.uuid4().hex}.jpg"
    (tmp_storage / key).write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")
    return {"storage_key": key, "sort_order": sort_order}


def _base_case_fields() -> dict:
    return {
        "purpose": "遺品整理",
        "prefecture": "東京都",
        "city": "世田谷区",
        "housing_type": "マンション",
        "floor_plan": "2LDK",
    }


def _vision_result(
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


# ──────────────────────────── 1. items ネスト作成 ────────────────────────────


async def test_create_case_with_items_groups_photos_and_normalizes_sort_order(
    client: AsyncClient,
):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {"name": "テーブル", "sort_order": 99, "photos": [_photo(5), _photo(1)]},
            {"name": None, "sort_order": 1, "photos": [_photo(3)]},
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()

    assert case["item_count"] == 2
    assert case["photo_count"] == 3
    # 既存のフラット photos（全件）は維持される。
    assert len(case["photos"]) == 3

    items = case["items"]
    assert len(items) == 2
    assert items[0]["name"] == "テーブル"
    # sort_order はサーバ側で配列インデックスに正規化される（クライアント値=99/1は無視）。
    assert [it["sort_order"] for it in items] == [0, 1]
    assert [p["sort_order"] for p in items[0]["photos"]] == [0, 1]
    assert len(items[1]["photos"]) == 1


# ──────────────────────────── 2. items と photos の併存 ────────────────────────────


async def test_items_and_flat_photos_coexist(client: AsyncClient):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [_photo(0)],
        "items": [{"name": "椅子", "photos": [_photo(0)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["item_count"] == 1
    assert case["photo_count"] == 2
    assert len(case["photos"]) == 2
    assert len(case["items"][0]["photos"]) == 1


# ──────────────────────────── 3. 上限超過で422 ────────────────────────────


async def test_too_many_items_422(client: AsyncClient):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": f"item{i}", "photos": [_photo(0)]} for i in range(MAX_ITEMS_PER_CASE + 1)],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


async def test_too_many_photos_per_item_422(client: AsyncClient):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": "item", "photos": [_photo(i) for i in range(MAX_PHOTOS_PER_ITEM + 1)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


async def test_total_photo_count_over_case_limit_422(client: AsyncClient):
    """各商品は上限(12枚)以下でも、合計(13商品×12枚=156枚)が案件上限(150枚)を超えれば422。"""
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {"name": f"item{i}", "photos": [_photo(j) for j in range(12)]}
            for i in range(13)
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


# ──────────────────────────── 4. パストラバーサル ────────────────────────────


async def test_item_photo_path_traversal_rejected_422(client: AsyncClient):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {"name": "item", "photos": [{"storage_key": "../../etc/passwd", "sort_order": 0}]}
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


# ──────────────────────────── 5. レガシー案件（items無し） ────────────────────────────


async def test_legacy_case_without_items_returns_empty_items_list(client: AsyncClient):
    token = await _signup_user(client)
    payload = {**_base_case_fields(), "photos": [_photo(0), _photo(1)]}
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["items"] == []
    assert case["item_count"] == 0
    assert case["photo_count"] == 2
    # 既存フォーマット（generate_case_summary のフォールバック文）がそのまま使われる。
    # storage_key に対応する実ファイルが存在しないため photo_url_for_ai は None を返し、
    # AI解析対象0枚として扱われる（既存の写真アップロード無しテストと同じ挙動。
    # photo_count（案件全体の実写真枚数=2）とは別概念であることに注意）。
    assert case["ai_summary"].startswith("利用目的: 遺品整理。")
    assert "写真 0 枚" in case["ai_summary"]


# ──────────────────────────── 6. 商品削除のカスケード ────────────────────────────


async def test_delete_item_cascades_photos(client: AsyncClient, db_session: AsyncSession):
    """商品(CaseItem)を削除すると配下写真も削除される（複合FK ON DELETE CASCADE）。

    SQLite はデフォルトで外部キー制約を強制しない（PRAGMA foreign_keys がデフォルト
    OFF）。DB定義の複合FKの実効性そのものを検証するため、当該コネクション上で
    明示的に有効化する。
    """
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": "item", "photos": [_photo(0), _photo(1)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    item_id = uuid.UUID(r.json()["items"][0]["id"])

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    item = await db_session.get(CaseItem, item_id)
    assert item is not None
    await db_session.delete(item)
    await db_session.commit()

    remaining = await db_session.scalar(
        select(func.count()).select_from(CasePhoto).where(CasePhoto.case_item_id == item_id)
    )
    assert remaining == 0


# ──────────────────────────── 7. 複合FKによる他案件item参照の拒否 ────────────────────────────


async def test_cross_case_item_reference_rejected_by_composite_fk(
    client: AsyncClient, db_session: AsyncSession
):
    token = await _signup_user(client)
    # CaseItemIn.photos は min_length=1 必須（security review 指摘対応）のため、
    # 各itemに最低1枚の写真を付与する（本テストの主眼はitem間の複合FK隔離であり、
    # 写真枚数はこの検証と無関係）。
    payload_a = {**_base_case_fields(), "photos": [], "items": [{"name": "A", "photos": [_photo(0)]}]}
    payload_b = {**_base_case_fields(), "photos": [], "items": [{"name": "B", "photos": [_photo(0)]}]}
    r_a = await client.post("/api/v1/cases", json=payload_a, headers=_auth(token))
    r_b = await client.post("/api/v1/cases", json=payload_b, headers=_auth(token))
    assert r_a.status_code == 201 and r_b.status_code == 201

    case_a_id = uuid.UUID(r_a.json()["id"])
    item_b_id = uuid.UUID(r_b.json()["items"][0]["id"])

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    bad_photo = CasePhoto(
        case_id=case_a_id,
        case_item_id=item_b_id,  # 案件Bのitem_idを案件A配下の写真に指定（不正）
        storage_key=f"{uuid.uuid4().hex}.jpg",
        sort_order=0,
    )
    db_session.add(bad_photo)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ──────────────────────────── 8. Gemini呼び出し予算 ────────────────────────────


async def test_eight_items_all_analyzed_within_budget(
    client: AsyncClient, tmp_storage, monkeypatch
):
    """商品数(8)がGemini予算(8)以下の場合、Round1で全商品が必ず1回は解析される。"""
    token = await _signup_user(client)
    call_log: list[str] = []

    async def fake_analyze_image(ref: str) -> VisionResult:
        call_log.append(ref)
        return _vision_result(detected_name=f"品目{len(call_log)}")

    monkeypatch.setattr(summary_module, "analyze_image", fake_analyze_image)

    items = [{"name": None, "photos": [_photo_with_file(tmp_storage)]} for _ in range(8)]
    payload = {**_base_case_fields(), "photos": [], "items": items}
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()

    assert len(call_log) <= 8
    for item in case["items"]:
        assert item["ai_detected_name"] is not None


async def test_ten_items_exceeds_budget_capped_at_eight_calls(
    client: AsyncClient, tmp_storage, monkeypatch
):
    """商品数(10)がGemini予算(8)を超える場合、呼び出しは8回に制限される。

    予算超過分の商品はAI情報なし（ai_detected_name=None）のまま残るのは設計上の
    トレードオフであり、想定内の挙動（Round1は8商品までしか代表写真を割り当てない）。
    """
    token = await _signup_user(client)
    call_log: list[str] = []

    async def fake_analyze_image(ref: str) -> VisionResult:
        call_log.append(ref)
        return _vision_result(detected_name=f"品目{len(call_log)}")

    monkeypatch.setattr(summary_module, "analyze_image", fake_analyze_image)

    items = [{"name": None, "photos": [_photo_with_file(tmp_storage)]} for _ in range(10)]
    payload = {**_base_case_fields(), "photos": [], "items": items}
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()

    assert len(call_log) <= 8
    assert len(case["items"]) == 10
    analyzed_count = sum(1 for it in case["items"] if it["ai_detected_name"] is not None)
    assert analyzed_count <= 8


# ──────────────────────────── 9. 1商品の解析失敗が他商品を巻き込まない ────────────────────────────


async def test_one_item_analysis_failure_does_not_break_others(
    client: AsyncClient, tmp_storage, monkeypatch
):
    token = await _signup_user(client)
    ok_result = _vision_result(detected_name="生存品目")
    mock = AsyncMock(side_effect=[RuntimeError("boom"), ok_result])
    monkeypatch.setattr(summary_module, "analyze_image", mock)

    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {"name": None, "photos": [_photo_with_file(tmp_storage)]},
            {"name": None, "photos": [_photo_with_file(tmp_storage)]},
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()

    detected_names = [it["ai_detected_name"] for it in case["items"]]
    assert "生存品目" in detected_names
    assert case["ai_summary"] is not None
    assert "生存品目" in case["ai_summary"]


# ──────────────────────────── 10. 汚染されたdetected_nameのサニタイズ ────────────────────────────


async def test_poisoned_detected_name_not_persisted(
    client: AsyncClient, tmp_storage, monkeypatch
):
    token = await _signup_user(client)
    poisoned = _vision_result(detected_name="https://evil.example/phish")
    monkeypatch.setattr(summary_module, "analyze_image", AsyncMock(return_value=poisoned))

    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": None, "photos": [_photo_with_file(tmp_storage)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()

    assert case["items"][0]["ai_detected_name"] is None
    assert "evil.example" not in (case["ai_summary"] or "")


# ──────────────────────────── 11. transactions.py の items eager load ────────────────────────────


async def test_transaction_detail_with_items_does_not_500(
    client: AsyncClient, db_session: AsyncSession
):
    """items を含む案件が落札された場合、成約詳細取得でMissingGreenlet(500)にならない
    こと（transactions.py の _TXN_LOAD に items の eager load が効いていることの回帰確認）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "txn_items_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "txn_items_op@example.com"
    )

    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": "商品A", "photos": [_photo(0)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(user_token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids", json={"amount": 30000}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    bid_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid_id}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    txn_id = r.json()["id"]

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["case"]["item_count"] == 1
    assert len(detail["case"]["items"]) == 1
    assert detail["case"]["items"][0]["name"] == "商品A"

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text


# ──────────────────────────── 12. CaseItem.name のサーバ側無害化 ────────────────────────────


@pytest.mark.parametrize(
    "poisoned_name",
    [
        "商品名 090-1234-5678まで連絡ください",
        "https://evil.example/contact",
        "問い合わせ contact@evil.example",
    ],
)
async def test_item_name_with_contact_info_rejected_422(
    client: AsyncClient, poisoned_name: str
):
    """CaseItem.name（ユーザー自由入力）に電話番号・URL・メールアドレスを
    含めると422になる（security review 指摘対応: プラットフォーム外への
    直接連絡誘導の防止をbids.py同様、案件作成時にも適用する）。"""
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": poisoned_name, "photos": [_photo(0)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


async def test_item_name_control_chars_stripped(client: AsyncClient):
    """CaseItem.name の制御文字・双方向制御文字はサーバ側で除去される。"""
    token = await _signup_user(client)
    # \x00: 制御文字。‮: RIGHT-TO-LEFT OVERRIDE（Unicode双方向制御文字。
    # 表示崩れ・なりすまし対策として除去対象）。
    poisoned_name = "商品\x00名‮"
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": poisoned_name, "photos": [_photo(0)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    assert r.json()["items"][0]["name"] == "商品名"


# ──────────────────────────── 13. sort_order の範囲制約 ────────────────────────────


@pytest.mark.parametrize("bad_sort_order", [-1, 1001])
async def test_flat_photo_sort_order_out_of_range_422(
    client: AsyncClient, bad_sort_order: int
):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": bad_sort_order}],
        "items": [],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


@pytest.mark.parametrize("bad_sort_order", [-1, 1001])
async def test_item_photo_sort_order_out_of_range_422(
    client: AsyncClient, bad_sort_order: int
):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {
                "name": "item",
                "photos": [
                    {"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": bad_sort_order}
                ],
            }
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


# ──────────────────────────── 14. CaseItemIn.photos の min_length=1 ────────────────────────────


async def test_item_with_zero_photos_rejected_422(client: AsyncClient):
    """写真の紐づいていない商品アルバム（0枚）は422になる（security review 指摘対応）。"""
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": "商品", "photos": []}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


# ──────────────────────────── 15. ユーザー入力名がAI検出結果として混入しないこと ────────────────────────────


async def test_user_input_name_not_mixed_into_ai_detected_summary(
    client: AsyncClient, tmp_storage, monkeypatch
):
    """CaseItem.name（ユーザー入力）は ai_summary の「AI 検出品目」欄へ、
    AIが検出したかのように混入してはならない（security review 指摘対応）。
    AI解析自体が失敗した（=ai_detected_nameがNoneのまま）ケースで、ユーザー
    入力名がai_summaryに現れないことを確認する。"""
    token = await _signup_user(client)
    monkeypatch.setattr(
        summary_module, "analyze_image", AsyncMock(side_effect=RuntimeError("boom"))
    )
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {"name": "ユーザー入力の商品名", "photos": [_photo_with_file(tmp_storage)]}
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()

    assert case["items"][0]["name"] == "ユーザー入力の商品名"
    assert case["items"][0]["ai_detected_name"] is None
    assert "ユーザー入力の商品名" not in (case["ai_summary"] or "")
    assert "AI 検出品目" not in (case["ai_summary"] or "")


# ──────────────────────────── 16. 入札の同時実行下でのDB制約違反は409（500にならない） ────────────────────────────


async def test_duplicate_bid_db_constraint_violation_returns_409_not_500(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """アプリ層の in-memory 重複チェック（any(...)）をすり抜けた場合でも、
    DBのユニーク制約（uq_bids_case_operator）違反はIntegrityErrorとして捕捉され
    409に変換されること（素通しで500にならないこと。security review 指摘対応）。
    """
    from app.api.v1.endpoints import bids as bids_endpoint
    from app.db.models.bid import Bid

    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "dup_bid_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "dup_bid_op@example.com"
    )

    payload = {**_base_case_fields(), "photos": [_photo(0)], "items": []}
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(user_token))
    assert r.status_code == 201, r.text
    case_id = uuid.UUID(r.json()["id"])

    # DBへ直接、既に入札済みの行を先行して作る（DB制約違反を実際に発生させるため）。
    existing_bid = Bid(case_id=case_id, operator_id=uuid.UUID(op_id), amount=10000)
    db_session.add(existing_bid)
    await db_session.commit()

    class _FakeCase:
        """アプリ層の in-memory 事前チェック（any(...)）を意図的にすり抜けさせる
        ダミー（実際に同時実行下でTOCTOUが起きた状況を模す）。"""

        def __init__(self, case_id: uuid.UUID) -> None:
            self.id = case_id
            self.status = "open"
            self.bids: list = []
            self.user_id = None

    async def _fake_get_case(session, cid):
        return _FakeCase(cid)

    monkeypatch.setattr(bids_endpoint, "_get_case", _fake_get_case)

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 20000},
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text
