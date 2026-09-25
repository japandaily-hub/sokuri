"""退会・強制削除済み業者の旧トークン失効の回帰テスト（security review 指摘対応）。

本人退会（``DELETE /operator/me``）・運営による強制削除（``DELETE /admin/operators/{id}``）で
論理削除（deleted_at 設定・匿名化）された業者の旧JWTが、``get_current_operator`` 以外の
経路で失効していなかった:

- ``deps.get_current_actor`` の operator 分岐（案件一覧・詳細・入札一覧・成約一覧・
  成約詳細・チャット・レビュー投稿・/auth/me）。匿名化は vendor_status / is_suspended を
  変えないため停止ゲート・閲覧ゲートでも止まらず、完了取引の依頼者住所・メールまで読めた。
- ``auth.line_exchange`` の Bearer 付き連携経路（operator 分岐）。削除で password_hash=None に
  なるため再認証も飛ばされ、匿名化済みの業者行へ line_user_id を再設定できた（匿名化の
  部分的な巻き戻り）上、新しいトークンまで発行されていた。

本ファイルで固定する契約:

- 削除前に取得した旧トークンで上記の全経路が 401（``get_current_operator`` と同一の
  ``_CRED_EXC``）になること。本人退会・運営削除の両方。
- 削除されていない承認済み業者は従来どおり 200 / 201（正常系を塞いでいないことの対照）。
- 任意認証（``GET /files/{key}``）は従来どおり削除済みを「トークン無し」として扱うこと。
- 閲覧ゲート ``assert_operator_case_access`` 単体でも削除済みを 401 で止めること（多層防御）。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。ヘルパーは
tests/test_r8_abnormal_guards.py と同様にこのファイル内へ自己完結で複製する。LINE API は
tests/test_line_integration.py と同じく ``httpx.AsyncClient.get`` を URL で出し分けてモックする。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_operator_case_access
from app.api.v1.endpoints import auth as auth_endpoint
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.transaction import Review
from app.db.models.user import User
from app.db.session import get_session

_TEST_LINE_CLIENT_ID = "test-line-channel-id"
_OP_PASSWORD = "operatorpass1"
# 構造として正しい最小の JPEG（1×1 グレー）。写真配信はメタデータ除去
# （services/image_metadata.py）で JPEG の構造を解釈し、画像でないバイト列は
# fail closed（404）にするため、配信経路のテストには実在する形式の画像を置く。
_MINIMAL_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b"
    "0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ff"
    "c0000b080001000101011100ffc40014000100000000000000000000000000000000ffc4001410010000000000"
    "0000000000000000000000ffda0008010100003f003fffd9"
)
_USER_EMAIL = "revoke_user@example.com"
# deps._CRED_EXC の detail（get_current_operator の論理削除ゲートと同一の契約）。
_CRED_DETAIL = "Invalid credentials. Please log in again."


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


@pytest.fixture(autouse=True)
def _line_client_id_configured(monkeypatch):
    """LINE_CLIENT_ID を設定済み状態にする（未設定だと line_exchange が 503 で先に止まり、
    失効ゲートまで到達しないため。tests/test_line_integration.py と同じ作法）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "line_client_id", _TEST_LINE_CLIENT_ID)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mock_line_get(user_id: str) -> AsyncMock:
    """LINE Verify API / Profile API を URL で出し分けるモック。"""
    verify_res = httpx.Response(
        200, json={"client_id": _TEST_LINE_CLIENT_ID, "expires_in": 3600, "scope": "profile"}
    )
    profile_res = httpx.Response(200, json={"userId": user_id, "displayName": "テスト業者"})

    async def _side_effect(url, *args, **kwargs):
        if url == auth_endpoint._LINE_VERIFY_ENDPOINT:
            return verify_res
        if url == auth_endpoint._LINE_PROFILE_ENDPOINT:
            return profile_res
        raise AssertionError(f"未想定のURLへのリクエスト: {url}")

    return AsyncMock(side_effect=_side_effect)


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="revoke_admin@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke_admin@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str = _USER_EMAIL) -> tuple[str, str]:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    return data["access_token"], data["user"]["id"]


async def _verified_operator(
    client: AsyncClient,
    admin_token: str,
    email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": company,
            "email": email,
            "password": _OP_PASSWORD,
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    op_id = data["operator"]["id"]
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    return data["access_token"], op_id


async def _operator_reauth_token(client: AsyncClient, op_token: str) -> str:
    """業者がLINE連携（新規付与）に必要な再認証トークンを発行する。"""
    r = await client.post(
        "/api/v1/operator/reauth-token",
        json={"current_password": _OP_PASSWORD},
        headers=_auth(op_token),
    )
    assert r.status_code == 200, r.text
    return r.json()["reauth_token"]


def _case_payload() -> dict:
    return {
        "purpose": "遺品整理",
        "prefecture": "東京都",
        "city": "世田谷区",
        "address_detail": "桜丘1-2-3 メゾン桜 101号室",
        "housing_type": "マンション",
        "floor_plan": "2LDK",
        "floor_number": 1,
        "has_elevator": False,
        "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0}],
    }


async def _create_completed_transaction(
    client: AsyncClient, user_token: str, op_token: str
) -> tuple[str, str]:
    """案件作成 → 入札 → 落札 → 完了確定まで進め、(case_id, transaction_id) を返す。

    完了（終端状態）にしておくのは、進行中取引があると退会・強制削除が 409 で
    拒否されるため（operator_profile._delete_and_anonymize_operator）。完了取引は
    業者側の詳細に依頼者の住所・メールが開示される＝失効漏れの実害が最も大きい状態でもある。
    """
    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(user_token))
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
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    return case_id, txn_id


def _operator_read_paths(case_id: str, txn_id: str) -> list[str]:
    """get_current_actor / get_case_viewer_actor を経由する業者の閲覧系エンドポイント。"""
    return [
        "/api/v1/cases",
        f"/api/v1/cases/{case_id}",
        f"/api/v1/cases/{case_id}/bids",
        "/api/v1/transactions",
        f"/api/v1/transactions/{txn_id}",
        f"/api/v1/transactions/{txn_id}/messages",
        "/api/v1/auth/me",
    ]


async def _delete_operator(
    client: AsyncClient, deletion: str, admin_token: str, op_token: str, op_id: str
) -> None:
    """本人退会（self_withdraw）または運営による強制削除（admin_delete）を実行する。"""
    if deletion == "self_withdraw":
        r = await client.request(
            "DELETE",
            "/api/v1/operator/me",
            json={"password": _OP_PASSWORD},
            headers=_auth(op_token),
        )
        assert r.status_code == 204, r.text
        return
    r = await client.delete(f"/api/v1/admin/operators/{op_id}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text


def _assert_revoked(r: httpx.Response, label: str) -> None:
    """get_current_operator の論理削除ゲートと同一の 401（_CRED_EXC）であること。"""
    assert r.status_code == 401, f"{label}: {r.status_code} {r.text}"
    assert r.json()["detail"] == _CRED_DETAIL, f"{label}: {r.text}"
    assert r.headers.get("www-authenticate") == "Bearer", label


# ──────────────── 削除済み業者の旧トークン失効（本人退会・運営削除） ────────────────


@pytest.mark.parametrize("deletion", ["self_withdraw", "admin_delete"])
async def test_deleted_operator_old_token_is_revoked_on_every_path(
    client: AsyncClient, db_session: AsyncSession, deletion: str
):
    """削除前に取得した旧トークンは、Actor 経由の全経路と line_exchange で 401 になる。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, op_id = await _verified_operator(
        client, admin_token, f"revoke_{deletion}@example.com"
    )
    case_id, txn_id = await _create_completed_transaction(client, user_token, op_token)

    # 前提: 削除前は同じトークンで全経路が通る（401 の原因が経路・権限の誤りではなく
    # 失効であることの担保）。完了取引の詳細には依頼者の住所・メールが含まれる。
    for path in _operator_read_paths(case_id, txn_id):
        r = await client.get(path, headers=_auth(op_token))
        assert r.status_code == 200, f"{path}: {r.text}"
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.json()["address"] is not None
    assert r.json()["contact_email"] == _USER_EMAIL

    await _delete_operator(client, deletion, admin_token, op_token, op_id)

    for path in _operator_read_paths(case_id, txn_id):
        r = await client.get(path, headers=_auth(op_token))
        _assert_revoked(r, f"GET {path}")

    # 書き込み経路: レビュー投稿も 401 で止まり、行は作られない。
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good"},
        headers=_auth(op_token),
    )
    _assert_revoked(r, "POST /api/v1/reviews")
    review_count = await db_session.scalar(
        select(func.count()).select_from(Review).where(Review.transaction_id == uuid.UUID(txn_id))
    )
    assert review_count == 0

    # line_exchange（Bearer付き連携経路）: 401 で止まり、新トークンも発行されない。
    # 匿名化済みの業者行に line_user_id が再設定されない（匿名化が巻き戻らない）。
    with patch.object(
        httpx.AsyncClient, "get", new=_mock_line_get("U0a1b2c3d4e5f60718293a4b5c6d7e8f9")
    ):
        r = await client.post(
            "/api/v1/auth/line/exchange",
            json={"line_access_token": "dummy-line-token"},
            headers=_auth(op_token),
        )
    _assert_revoked(r, "POST /api/v1/auth/line/exchange")
    assert "access_token" not in r.json()

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.deleted_at is not None
    assert operator.line_user_id is None
    assert operator.contact_email == f"deleted-{op_id}@deleted.katazuke.internal"


async def test_active_operator_token_keeps_working_on_every_path(
    client: AsyncClient, db_session: AsyncSession
):
    """対照: 削除されていない承認済み業者は従来どおり 200 / 201（正常系を塞いでいない）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, _ = await _signup_user(client)
    op_token, op_id = await _verified_operator(client, admin_token, "revoke_control@example.com")
    case_id, txn_id = await _create_completed_transaction(client, user_token, op_token)

    for path in _operator_read_paths(case_id, txn_id):
        r = await client.get(path, headers=_auth(op_token))
        assert r.status_code == 200, f"{path}: {r.text}"
    r = await client.get("/api/v1/auth/me", headers=_auth(op_token))
    assert r.json()["account_type"] == "operator"
    assert r.json()["operator"]["id"] == op_id

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["reviewer_type"] == "operator"

    line_user_id = "U1a2b3c4d5e6f708192a3b4c5d6e7f8a9"
    op_reauth_token = await _operator_reauth_token(client, op_token)
    with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
        r = await client.post(
            "/api/v1/auth/line/exchange",
            json={"line_access_token": "dummy-line-token", "reauth_token": op_reauth_token},
            headers=_auth(op_token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["account_type"] == "operator"
    assert r.json()["operator"]["id"] == op_id

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.line_user_id == line_user_id


# ──────────────── 任意認証（GET /files/{key}）の既存方針の維持 ────────────────


async def test_deleted_operator_token_on_file_delivery_is_treated_as_no_token(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
):
    """``get_optional_operator`` は削除済みを従来どおり「トークン無し」として扱う（401 にしない）。

    ``GET /files/{key}`` は無認証の capability URL のため、401 にしてもヘッダを外せば
    同じ画像が取れ防御上の差が無い一方、既存の無認証配信を壊す。判定条件は
    ``assert_operator_not_revoked`` と同一（deleted_at）に保ち、応答は無トークン時と同一にする。
    """
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    storage_key = f"{uuid.uuid4().hex}.jpg"
    (tmp_path / storage_key).write_bytes(_MINIMAL_JPEG)
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, admin_token, "revoke_files@example.com")

    r = await client.request(
        "DELETE",
        "/api/v1/operator/me",
        json={"password": _OP_PASSWORD},
        headers=_auth(op_token),
    )
    assert r.status_code == 204, r.text

    anonymous = await client.get(f"/api/v1/files/{storage_key}")
    assert anonymous.status_code == 200
    r = await client.get(f"/api/v1/files/{storage_key}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.content == anonymous.content


# ──────────────── 閲覧ゲート単体の多層防御 ────────────────


@pytest.mark.parametrize("is_suspended", [False, True])
def test_case_access_gate_rejects_deleted_operator_before_other_checks(is_suspended: bool):
    """``assert_operator_case_access`` 単体でも、削除済みは vendor_status=active のままでも 401。

    匿名化は vendor_status / is_suspended を変えないため、別経路で解決した業者が
    このゲートに渡されても閲覧が通らないことを固定する。停止中かつ削除済みの場合も
    ``account_suspended``（403・問い合わせ導線）ではなく 401（再ログイン要求）を優先する。
    """
    operator = Operator(
        company_name="削除済み業者",
        contact_email="deleted-gate@deleted.katazuke.internal",
        vendor_status="active",
        is_suspended=is_suspended,
        deleted_at=datetime.now(timezone.utc),
    )
    with pytest.raises(HTTPException) as exc_info:
        assert_operator_case_access(operator)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == _CRED_DETAIL
