"""商品(CaseItem)情報編集・削除、写真(CasePhoto)削除・追加APIの統合テスト。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_case_items.py と同様、各テストファイルは自己完結（ヘルパーを
ローカルに複製する既存スタイルを踏襲）。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.case import CaseItem, CasePhoto
from app.db.session import get_session

# ──────────────────────────── fixture / helper（test_case_items.py から複製） ────────────────────────────


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


# ──────────────────────────── 本テストファイル固有のヘルパー ────────────────────────────


async def _create_case_with_item(
    client: AsyncClient, token: str, *, n_photos: int = 1, name: str = "商品A"
) -> tuple[str, str, list[dict]]:
    """商品(CaseItem)1件・写真n_photos枚を持つ案件を作成する。

    Returns:
        (case_id, item_id, photos) — photos は作成時レスポンスの CaseItemOut.photos。
    """
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": name, "photos": [_photo(i) for i in range(n_photos)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()
    item = case["items"][0]
    return case["id"], item["id"], item["photos"]


async def _create_case_with_flat_photo(client: AsyncClient, token: str) -> tuple[str, str]:
    """未分類写真（case_item_id=NULL）を1枚持つ案件を作成する。"""
    payload = {**_base_case_fields(), "photos": [_photo(0)], "items": []}
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()
    return case["id"], case["photos"][0]["id"]


async def _advance_to_bidding(
    client: AsyncClient, db_session: AsyncSession, admin_token: str, case_id: str
) -> tuple[str, str]:
    """案件を bidding 状態に進める（業者が1件入札）。"""
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, f"op_{uuid.uuid4().hex}@example.com"
    )
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids", json={"amount": 10000}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    return op_token, r.json()["id"]


async def _advance_to_closed(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    user_token: str,
    case_id: str,
) -> None:
    """案件を closed 状態に進める（業者を選択して落札確定）。"""
    _op_token, bid_id = await _advance_to_bidding(client, db_session, admin_token, case_id)
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid_id}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text


# ──────────────────────────── PUT /cases/{case_id}/items/{item_id} ────────────────────────────


async def test_update_item_200_updates_user_fields_without_touching_ai_fields(
    client: AsyncClient,
):
    token = await _signup_user(client)
    case_id, item_id, _ = await _create_case_with_item(client, token)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={
            "name": "編集後の商品名",
            "user_condition": "good",
            "user_description": "傷はほぼありません。",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["name"] == "編集後の商品名"
    assert item["user_condition"] == "good"
    assert item["user_description"] == "傷はほぼありません。"
    # ai_condition/ai_summary（AI推定値）は不変（未解析のためNoneのまま）。
    assert item["ai_condition"] is None
    assert item["ai_summary"] is None

    # 再取得しても反映されている（DB永続化の確認）。
    r2 = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    item2 = r2.json()["items"][0]
    assert item2["name"] == "編集後の商品名"
    assert item2["user_condition"] == "good"
    assert item2["user_description"] == "傷はほぼありません。"


async def test_update_item_200_null_clears_fields(client: AsyncClient):
    token = await _signup_user(client)
    case_id, item_id, _ = await _create_case_with_item(client, token)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={"name": "いったん設定", "user_condition": "fair", "user_description": "説明あり"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text

    r2 = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={"name": None, "user_condition": None, "user_description": None},
        headers=_auth(token),
    )
    assert r2.status_code == 200, r2.text
    item = r2.json()
    assert item["name"] is None
    assert item["user_condition"] is None
    assert item["user_description"] is None


async def test_update_item_403_other_user(client: AsyncClient):
    token = await _signup_user(client, "owner@example.com")
    other_token = await _signup_user(client, "other@example.com")
    case_id, item_id, _ = await _create_case_with_item(client, token)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={"name": "不正編集"},
        headers=_auth(other_token),
    )
    assert r.status_code == 403


async def test_update_item_404_item_not_found(client: AsyncClient):
    token = await _signup_user(client)
    case_id, _item_id, _ = await _create_case_with_item(client, token)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{uuid.uuid4()}",
        json={"name": "存在しない"},
        headers=_auth(token),
    )
    assert r.status_code == 404


async def test_update_item_404_item_belongs_to_other_case(client: AsyncClient):
    token = await _signup_user(client)
    case_a_id, _item_a_id, _ = await _create_case_with_item(client, token, name="A")
    _case_b_id, item_b_id, _ = await _create_case_with_item(client, token, name="B")

    r = await client.put(
        f"/api/v1/cases/{case_a_id}/items/{item_b_id}",
        json={"name": "別案件のitemを指定"},
        headers=_auth(token),
    )
    assert r.status_code == 404


async def test_update_item_409_bidding(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    token = await _signup_user(client, "bidding_owner@example.com")
    case_id, item_id, _ = await _create_case_with_item(client, token)
    await _advance_to_bidding(client, db_session, admin_token, case_id)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={"name": "入札中に編集"},
        headers=_auth(token),
    )
    assert r.status_code == 409


async def test_update_item_409_closed(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    token = await _signup_user(client, "closed_owner@example.com")
    case_id, item_id, _ = await _create_case_with_item(client, token)
    await _advance_to_closed(client, db_session, admin_token, token, case_id)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={"name": "成約後に編集"},
        headers=_auth(token),
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "field,poisoned_value",
    [
        ("name", "090-1234-5678まで連絡ください"),
        ("user_description", "問い合わせは contact@evil.example まで"),
    ],
)
async def test_update_item_422_contact_info_rejected(
    client: AsyncClient, field: str, poisoned_value: str
):
    token = await _signup_user(client)
    case_id, item_id, _ = await _create_case_with_item(client, token)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={field: poisoned_value},
        headers=_auth(token),
    )
    assert r.status_code == 422


async def test_update_item_422_description_too_long(client: AsyncClient):
    token = await _signup_user(client)
    case_id, item_id, _ = await _create_case_with_item(client, token)

    r = await client.put(
        f"/api/v1/cases/{case_id}/items/{item_id}",
        json={"user_description": "あ" * 501},
        headers=_auth(token),
    )
    assert r.status_code == 422


# ──────────────────────────── DELETE /cases/{case_id}/items/{item_id} ────────────────────────────


async def test_delete_item_204_cascades_db_and_storage(
    client: AsyncClient, db_session: AsyncSession, tmp_storage
):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": "削除対象", "photos": [_photo_with_file(tmp_storage, 0), _photo_with_file(tmp_storage, 1)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    item = r.json()["items"][0]
    item_id = item["id"]
    storage_keys = [p["url"].rsplit("/", 1)[-1] for p in item["photos"]]
    for key in storage_keys:
        assert (tmp_storage / key).is_file()

    # SQLite はデフォルトで外部キー制約を強制しないため、複合FKのON DELETE CASCADEを
    # 実効させるにはコネクション単位で明示的に有効化する必要がある
    # （test_case_items.py の test_delete_item_cascades_photos と同じ対応）。
    await db_session.execute(text("PRAGMA foreign_keys=ON"))

    r2 = await client.delete(f"/api/v1/cases/{case_id}/items/{item_id}", headers=_auth(token))
    assert r2.status_code == 204, r2.text

    remaining_item = await db_session.get(CaseItem, uuid.UUID(item_id))
    assert remaining_item is None
    remaining_photo = await db_session.scalar(
        select(CasePhoto).where(CasePhoto.case_item_id == uuid.UUID(item_id))
    )
    assert remaining_photo is None

    for key in storage_keys:
        assert not (tmp_storage / key).is_file()


async def test_delete_item_403_other_user(client: AsyncClient):
    token = await _signup_user(client, "owner2@example.com")
    other_token = await _signup_user(client, "other2@example.com")
    case_id, item_id, _ = await _create_case_with_item(client, token)

    r = await client.delete(
        f"/api/v1/cases/{case_id}/items/{item_id}", headers=_auth(other_token)
    )
    assert r.status_code == 403


async def test_delete_item_404_not_found(client: AsyncClient):
    token = await _signup_user(client)
    case_id, _item_id, _ = await _create_case_with_item(client, token)

    r = await client.delete(
        f"/api/v1/cases/{case_id}/items/{uuid.uuid4()}", headers=_auth(token)
    )
    assert r.status_code == 404


async def test_delete_item_409_bidding(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    token = await _signup_user(client, "delete_bidding_owner@example.com")
    case_id, item_id, _ = await _create_case_with_item(client, token)
    await _advance_to_bidding(client, db_session, admin_token, case_id)

    r = await client.delete(
        f"/api/v1/cases/{case_id}/items/{item_id}", headers=_auth(token)
    )
    assert r.status_code == 409


# ──────────────────────────── DELETE /cases/{case_id}/photos/{photo_id} ────────────────────────────


async def test_delete_photo_204_removes_db_and_storage(
    client: AsyncClient, db_session: AsyncSession, tmp_storage
):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": "商品", "photos": [_photo_with_file(tmp_storage, 0), _photo_with_file(tmp_storage, 1)]}],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    photos = r.json()["items"][0]["photos"]
    target = photos[0]
    target_key = target["url"].rsplit("/", 1)[-1]
    assert (tmp_storage / target_key).is_file()

    r2 = await client.delete(
        f"/api/v1/cases/{case_id}/photos/{target['id']}", headers=_auth(token)
    )
    assert r2.status_code == 204, r2.text

    remaining = await db_session.get(CasePhoto, uuid.UUID(target["id"]))
    assert remaining is None
    assert not (tmp_storage / target_key).is_file()


async def test_delete_photo_204_last_photo_keeps_item(client: AsyncClient):
    token = await _signup_user(client)
    case_id, item_id, photos = await _create_case_with_item(client, token, n_photos=1)
    photo_id = photos[0]["id"]

    r = await client.delete(
        f"/api/v1/cases/{case_id}/photos/{photo_id}", headers=_auth(token)
    )
    assert r.status_code == 204, r.text

    r2 = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    items = r2.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == item_id
    assert items[0]["photos"] == []


async def test_delete_photo_204_unclassified_photo(client: AsyncClient):
    token = await _signup_user(client)
    case_id, photo_id = await _create_case_with_flat_photo(client, token)

    r = await client.delete(
        f"/api/v1/cases/{case_id}/photos/{photo_id}", headers=_auth(token)
    )
    assert r.status_code == 204, r.text

    r2 = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["photos"] == []


async def test_delete_photo_403_other_user(client: AsyncClient):
    token = await _signup_user(client, "owner3@example.com")
    other_token = await _signup_user(client, "other3@example.com")
    case_id, _item_id, photos = await _create_case_with_item(client, token)

    r = await client.delete(
        f"/api/v1/cases/{case_id}/photos/{photos[0]['id']}", headers=_auth(other_token)
    )
    assert r.status_code == 403


async def test_delete_photo_404_not_found(client: AsyncClient):
    token = await _signup_user(client)
    case_id, _item_id, _photos = await _create_case_with_item(client, token)

    r = await client.delete(
        f"/api/v1/cases/{case_id}/photos/{uuid.uuid4()}", headers=_auth(token)
    )
    assert r.status_code == 404


async def test_delete_photo_409_bidding(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    token = await _signup_user(client, "delete_photo_bidding_owner@example.com")
    case_id, _item_id, photos = await _create_case_with_item(client, token)
    await _advance_to_bidding(client, db_session, admin_token, case_id)

    r = await client.delete(
        f"/api/v1/cases/{case_id}/photos/{photos[0]['id']}", headers=_auth(token)
    )
    assert r.status_code == 409


# ──────────────────────────── POST /cases/{case_id}/items/{item_id}/photos ────────────────────────────


async def test_add_photo_201_assigns_next_sort_order(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    case_id, item_id, photos = await _create_case_with_item(
        client, token, n_photos=1
    )
    assert photos[0]["sort_order"] == 0

    new_photo = _photo_with_file(tmp_storage, 999)  # クライアント指定値は無視される
    r = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json=new_photo,
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["sort_order"] == 1


async def test_add_photo_201_after_gap_uses_max_plus_one(
    client: AsyncClient, db_session: AsyncSession, tmp_storage
):
    """途中の写真（sort_order=1）を削除して欠番を作った後に追加すると、
    連番を詰めず既存最大値+1を採番する（設計確定済み）。"""
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {
                "name": "商品",
                "photos": [
                    _photo_with_file(tmp_storage, 0),
                    _photo_with_file(tmp_storage, 1),
                    _photo_with_file(tmp_storage, 2),
                ],
            }
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    item_id = r.json()["items"][0]["id"]
    photos = r.json()["items"][0]["photos"]
    middle_photo_id = photos[1]["id"]  # sort_order=1

    r2 = await client.delete(
        f"/api/v1/cases/{case_id}/photos/{middle_photo_id}", headers=_auth(token)
    )
    assert r2.status_code == 204, r2.text

    new_photo = _photo_with_file(tmp_storage, 0)
    r3 = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json=new_photo,
        headers=_auth(token),
    )
    assert r3.status_code == 201, r3.text
    # 残存写真の sort_order は {0, 2} のため、欠番(1)を埋めず 3 が採番される。
    assert r3.json()["sort_order"] == 3


async def test_add_photo_404_file_not_uploaded(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    case_id, item_id, _ = await _create_case_with_item(client, token, n_photos=1)

    r = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json={"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0},
        headers=_auth(token),
    )
    assert r.status_code == 404


async def test_add_photo_422_invalid_key_format(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    case_id, item_id, _ = await _create_case_with_item(client, token, n_photos=1)

    r = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json={"storage_key": "../../etc/passwd", "sort_order": 0},
        headers=_auth(token),
    )
    assert r.status_code == 422


async def test_add_photo_409_reusing_other_users_storage_key(
    client: AsyncClient, tmp_storage
):
    """他人の案件の storage_key を自分の商品に流用しようとすると、DB UNIQUE制約
    （case_photos.storage_key、0017マイグレーション）違反により409で拒否される
    （security review 指摘対応・H-1: クロステナントでの写真破壊の入口を塞ぐ）。

    無認証の GET /files/{storage_key} で案件一覧閲覧などから storage_key を収集した
    攻撃者が、実ファイルが存在する（＝被害者がアップロード済み）ことを悪用して
    自分の商品に「追加」→ 自分の案件から「削除」で被害者の実ファイルを物理削除する
    経路そのものを、追加の時点で拒否できていることを確認する。
    """
    victim_token = await _signup_user(client, "storage_key_victim@example.com")
    attacker_token = await _signup_user(client, "storage_key_attacker@example.com")

    victim_payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [{"name": "被害者の商品", "photos": [_photo_with_file(tmp_storage, 0)]}],
    }
    r = await client.post(
        "/api/v1/cases", json=victim_payload, headers=_auth(victim_token)
    )
    assert r.status_code == 201, r.text
    victim_photo = r.json()["items"][0]["photos"][0]
    # storage_key 自体は CasePhotoOut に含まれないため url から逆算する
    # （既存テストの他箇所と同じ手法）。
    stolen_key = victim_photo["url"].rsplit("/", 1)[-1]
    assert (tmp_storage / stolen_key).is_file()

    attacker_case_id, attacker_item_id, _ = await _create_case_with_item(
        client, attacker_token, n_photos=1
    )

    r2 = await client.post(
        f"/api/v1/cases/{attacker_case_id}/items/{attacker_item_id}/photos",
        json={"storage_key": stolen_key, "sort_order": 0},
        headers=_auth(attacker_token),
    )
    assert r2.status_code == 409, r2.text

    # 流用が拒否されたため、被害者の実ファイルは無傷のまま残っていること
    # （攻撃者が後続で DELETE /cases/{自分のcase}/photos/{...} を呼べる状態に
    # 一切到達していないことの直接証拠）。
    assert (tmp_storage / stolen_key).is_file()


async def test_add_photo_422_item_limit_exceeded(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    payload = {
        **_base_case_fields(),
        "photos": [],
        "items": [
            {
                "name": "商品",
                "photos": [_photo_with_file(tmp_storage, i) for i in range(8)],
            }
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    item_id = r.json()["items"][0]["id"]

    new_photo = _photo_with_file(tmp_storage, 0)
    r2 = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json=new_photo,
        headers=_auth(token),
    )
    assert r2.status_code == 422


async def test_add_photo_422_case_limit_exceeded(client: AsyncClient, tmp_storage):
    """商品側は上限未満（7枚）でも、案件全体が上限(20枚)に達していれば422になる。"""
    token = await _signup_user(client)
    # item: 7枚（商品上限8枚未満）+ 直下: 13枚 = 合計20枚（案件上限ちょうど）。
    payload = {
        **_base_case_fields(),
        "photos": [_photo_with_file(tmp_storage, i) for i in range(13)],
        "items": [
            {
                "name": "商品",
                "photos": [_photo_with_file(tmp_storage, j) for j in range(7)],
            }
        ],
    }
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["photo_count"] == 20
    case_id = case["id"]
    item_id = case["items"][0]["id"]
    assert len(case["items"][0]["photos"]) == 7  # 商品側は上限(8)未満

    r2 = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json=_photo_with_file(tmp_storage, 0),
        headers=_auth(token),
    )
    assert r2.status_code == 422


async def test_add_photo_403_other_user(client: AsyncClient, tmp_storage):
    token = await _signup_user(client, "owner4@example.com")
    other_token = await _signup_user(client, "other4@example.com")
    case_id, item_id, _ = await _create_case_with_item(client, token, n_photos=1)

    r = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json=_photo_with_file(tmp_storage, 0),
        headers=_auth(other_token),
    )
    assert r.status_code == 403


async def test_add_photo_404_item_not_found(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    case_id, _item_id, _ = await _create_case_with_item(client, token, n_photos=1)

    r = await client.post(
        f"/api/v1/cases/{case_id}/items/{uuid.uuid4()}/photos",
        json=_photo_with_file(tmp_storage, 0),
        headers=_auth(token),
    )
    assert r.status_code == 404


async def test_add_photo_409_bidding(
    client: AsyncClient, db_session: AsyncSession, tmp_storage
):
    admin_token = await _make_admin(client, db_session)
    token = await _signup_user(client, "add_photo_bidding_owner@example.com")
    case_id, item_id, _ = await _create_case_with_item(client, token, n_photos=1)
    await _advance_to_bidding(client, db_session, admin_token, case_id)

    r = await client.post(
        f"/api/v1/cases/{case_id}/items/{item_id}/photos",
        json=_photo_with_file(tmp_storage, 0),
        headers=_auth(token),
    )
    assert r.status_code == 409
