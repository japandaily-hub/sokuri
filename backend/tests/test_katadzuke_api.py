"""カタヅケ API の統合テスト — 認証 / 案件 / 入札 / 成約 / 減額 / レビュー / 管理。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。
AI（Gemini）・メール（Brevo）には接続しない（写真ファイル不在時は
summary がフォールバック文を返し、Brevo はキー未設定でスキップされる）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.transaction import Review
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import CURRENT_OPERATOR_TERMS_VERSION
from app.services import storage
from app.services.storage import StorageUnavailableError


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


# 構造として正しい最小の JPEG（1×1 グレー。Pillow で生成し実デコードを確認済み）。
# 写真の受信・配信はメタデータ除去（services/image_metadata.py）で JPEG の構造を
# 解釈するため、先頭のマジックバイトだけの偽バイト列は受信で 415・配信で 404 に
# なる。メタデータを持たないので、除去の前後でバイト列は変わらない。
_MINIMAL_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b"
    "0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ff"
    "c0000b080001000101011100ffc40014000100000000000000000000000000000000ffc4001410010000000000"
    "0000000000000000000000ffda0008010100003f003fffd9"
)


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
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


async def _signup_user(client: AsyncClient, email: str = "user1@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201
    return r.json()["access_token"]


async def _invite_code(client: AsyncClient, admin_token: str) -> str:
    r = await client.post(
        "/api/v1/admin/invites", json={}, headers=_auth(admin_token)
    )
    assert r.status_code == 201
    return r.json()["code"]


async def _signup_operator(
    client: AsyncClient, code: str, email: str, company: str = "テスト片付け株式会社"
) -> tuple[str, str]:
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
    return data["access_token"], data["operator"]["id"]


async def _verified_operator(
    client: AsyncClient, db_session: AsyncSession, admin_token: str, email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    code = await _invite_code(client, admin_token)
    token, op_id = await _signup_operator(client, code, email, company)
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    return token, op_id


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
        "photos": [
            {"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0},
            {"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 1},
        ],
    }


async def _create_case(client: AsyncClient, user_token: str) -> dict:
    r = await client.post(
        "/api/v1/cases", json=_case_payload(), headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


# ──────────────────────────── 認証 ────────────────────────────


async def test_signup_login_me(client: AsyncClient):
    token = await _signup_user(client)
    r = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "user1@example.com"
    assert r.json()["account_type"] == "user"


async def test_signup_duplicate_email_409(client: AsyncClient):
    await _signup_user(client)
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": "user1@example.com", "password": "password123"},
    )
    assert r.status_code == 409


async def test_login_wrong_password_401(client: AsyncClient):
    await _signup_user(client)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "user1@example.com", "password": "wrongpassword"},
    )
    assert r.status_code == 401


async def test_operator_signup_requires_agreement_422(client: AsyncClient):
    """agreed=False（利用規約・プライバシーポリシー未同意）は422で拒否される。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "未同意テスト業者",
            "email": "no_agree_op@example.com",
            "password": "operatorpass1",
            "agreed": False,
        },
    )
    assert r.status_code == 422


async def test_operator_signup_missing_agreed_key_422(client: AsyncClient):
    """agreed キー自体を省略した場合も（必須フィールド欠落として）422で拒否される。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "agreedキー省略テスト業者",
            "email": "no_agreed_key_op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
        },
    )
    assert r.status_code == 422


async def test_operator_signup_records_agreement(
    client: AsyncClient, db_session: AsyncSession
):
    """agreed=True で登録成功し、同意日時・規約バージョンがDBに保存される。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "同意記録テスト業者",
            "email": "agree_op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    op_id = r.json()["operator"]["id"]

    operator = await db_session.scalar(
        select(Operator).where(Operator.id == uuid.UUID(op_id))
    )
    assert operator is not None
    assert operator.agreed_terms_version == CURRENT_OPERATOR_TERMS_VERSION
    assert operator.agreed_at is not None


async def test_operator_with_old_terms_version_can_still_login(
    client: AsyncClient, db_session: AsyncSession
):
    """CURRENT_OPERATOR_TERMS_VERSION 改定前に同意した既存業者も、再同意ゲートが
    存在しないためログイン・API利用がブロックされないことを確認する（ADD-H1対応）。

    agreed_terms_version は auth.py/operator_applications.py の登録・申込時にのみ
    書き込まれ、ログイン処理（operator_login）を含むどのエンドポイントも比較・検査
    していない（grep で確認済み）。よって定数更新は既存業者の締め出しを生まない。
    """
    import uuid as _uuid

    old_op = Operator(
        id=_uuid.uuid4(),
        company_name="旧規約同意業者",
        contact_email="old_terms_op@example.com",
        password_hash=hash_password("password123"),
        vendor_status="active",
        agreed_terms_version="2026-07-02",
    )
    db_session.add(old_op)
    await db_session.commit()

    r = await client.post(
        "/api/v1/auth/operator/login",
        json={"email": "old_terms_op@example.com", "password": "password123"},
    )
    assert r.status_code == 200, r.text
    assert old_op.agreed_terms_version != CURRENT_OPERATOR_TERMS_VERSION

    op_token = r.json()["access_token"]
    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200


async def test_operator_signup_requires_valid_invite(client: AsyncClient):
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": "KDZ-NOTEXIST",
            "company_name": "X社",
            "email": "op@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 403


async def test_invite_single_use(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    code = await _invite_code(client, admin_token)
    await _signup_operator(client, code, "op1@example.com")
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "二重利用社",
            "email": "op2@example.com",
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 403


async def test_admin_endpoints_require_admin_role(client: AsyncClient):
    token = await _signup_user(client)
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(token))
    assert r.status_code == 403


async def test_endpoints_require_auth_401(client: AsyncClient):
    assert (await client.get("/api/v1/cases")).status_code == 401
    assert (await client.post("/api/v1/cases", json=_case_payload())).status_code == 401
    assert (await client.post("/api/v1/upload/presign", json={})).status_code == 401


# ──────────────────────────── 案件 + マスキング ────────────────────────────


async def test_create_case_has_ai_summary_and_photos(client: AsyncClient):
    token = await _signup_user(client)
    case = await _create_case(client, token)
    assert case["status"] == "open"
    assert case["ai_summary"]
    assert len(case["photos"]) == 2
    assert case["address_detail"] == "桜丘1-2-3 メゾン桜 101号室"


async def test_create_case_rejects_unknown_purpose_422(client: AsyncClient):
    """purpose は web の選択肢＋既存テスト・シードで使われてきた値に限定される
    （CasePurpose の Literal 化）。未知の値は 422。
    """
    token = await _signup_user(client)
    payload = _case_payload()
    payload["purpose"] = "存在しない目的"
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422, r.text


async def test_unverified_operator_cannot_list_cases(
    client: AsyncClient, db_session: AsyncSession
):
    """vendor_status=pending の業者は案件一覧を閲覧できない（403 approval_required）。

    r12 決定1（プライバシー優先）で従来の「閲覧可・入札不可」の非対称を撤去した。
    承認後に 200 へ変わることは tests/test_r12_backend_fixes.py で検証する。
    """
    from app.core.security import create_access_token
    from app.db.models.operator import Operator
    import uuid as _uuid

    pending_op = Operator(
        id=_uuid.uuid4(),
        company_name="ペンディング業者",
        contact_email="pending_op@example.com",
        password_hash=hash_password("password123"),
        vendor_status="pending",
    )
    db_session.add(pending_op)
    await db_session.commit()
    await db_session.refresh(pending_op)

    op_token = create_access_token(pending_op.id, "operator", "operator")
    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "approval_required"


async def test_operator_case_view_masks_address(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    case = await _create_case(client, user_token)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "op1@example.com"
    )

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(op_token))
    assert r.status_code == 200
    body = r.json()
    assert "address_detail" not in body
    assert body["prefecture"] == "東京都"
    assert body["city"] == "世田谷区"

    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200
    assert all("address_detail" not in c for c in r.json())


async def test_user_cannot_view_others_case(client: AsyncClient):
    token_a = await _signup_user(client, "a@example.com")
    token_b = await _signup_user(client, "b@example.com")
    case = await _create_case(client, token_a)
    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(token_b))
    assert r.status_code == 403


# ──────────────────────────── フルフロー ────────────────────────────


async def test_full_flow_bid_select_reduction_complete_review(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op1_token, op1_id = await _verified_operator(
        client, db_session, admin_token, "op1@example.com", "片付けA社"
    )
    op2_token, op2_id = await _verified_operator(
        client, db_session, admin_token, "op2@example.com", "片付けB社"
    )
    case = await _create_case(client, user_token)
    case_id = case["id"]

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 50000, "message": "丁寧に対応します"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 201
    bid1 = r.json()
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 65000},
        headers=_auth(op2_token),
    )
    assert r.status_code == 201

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 70000},
        headers=_auth(op1_token),
    )
    assert r.status_code == 409

    r = await client.get(f"/api/v1/cases/{case_id}/bids", headers=_auth(user_token))
    assert r.status_code == 200
    bids = r.json()
    assert len(bids) == 2
    assert all(b["operator"]["company_name"] for b in bids)

    # 業者向け（op1）: 2026-09-07 決定で他社分も金額のみ匿名開示される（社名は非開示）。
    r = await client.get(f"/api/v1/cases/{case_id}/bids", headers=_auth(op1_token))
    op1_bids = r.json()
    assert len(op1_bids) == 2
    op1_own = next(b for b in op1_bids if b["is_mine"])
    op1_other = next(b for b in op1_bids if not b["is_mine"])
    assert op1_own["operator"]["company_name"] == "片付けA社"
    assert op1_other["operator"] is None
    assert op1_other["amount"] == 65000
    assert "片付けB社" not in r.text

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid1['id']}/select", headers=_auth(op1_token)
    )
    assert r.status_code in (401, 403)

    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid1['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201
    txn = r.json()
    assert txn["initial_amount"] == 50000
    txn_id = txn["id"]

    r = await client.get(f"/api/v1/cases/{case_id}", headers=_auth(user_token))
    assert r.json()["status"] == "closed"
    r = await client.get(f"/api/v1/cases/{case_id}/bids", headers=_auth(user_token))
    statuses = {b["operator"]["id"]: b["status"] for b in r.json()}
    assert statuses[op1_id] == "selected"
    assert statuses[op2_id] == "rejected"

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op1_token))
    assert r.status_code == 200
    detail = r.json()
    assert detail["address"]["address_detail"] == "桜丘1-2-3 メゾン桜 101号室"
    assert detail["contact_email"] == "user1@example.com"

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op2_token))
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 40000, "reason": "短い"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 60000, "reason": "実際の物量が想定より多かったため"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={
            "requested_amount": 42000,
            "reason": "現地確認の結果、家電 2 点に破損があり再販価値が下がるため",
        },
        headers=_auth(op1_token),
    )
    assert r.status_code == 201
    reduction = r.json()
    assert reduction["status"] == "pending"

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 41000, "reason": "さらに追加の破損が見つかったため"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 409

    r = await client.patch(
        f"/api/v1/transactions/{txn_id}/reduction/{reduction['id']}",
        json={"action": "approve"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.json()["final_amount"] == 42000

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(op1_token)
    )
    assert r.status_code == 403
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["final_amount"] == 42000

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "迅速で丁寧でした"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good"},
        headers=_auth(user_token),
    )
    assert r.status_code == 409

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "スムーズでした"},
        headers=_auth(op1_token),
    )
    assert r.status_code == 201

    # 依頼者→業者の評価だけが業者の件数に入る（業者→依頼者の評価は数えない）。
    r = await client.get(f"/api/v1/vendors/{op1_id}")
    assert (r.json()["good_count"], r.json()["improve_count"], r.json()["review_count"]) == (1, 0, 1)


# ──────────────────────────── 入札メッセージ: 連絡先/URLガード ────────────────────────────


async def test_bid_message_with_phone_number_rejected_422(
    client: AsyncClient, db_session: AsyncSession
):
    """入札メッセージに電話番号が含まれる場合は422で拒否される（脱プラットフォーム勧誘対策）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "guard_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "guard_op@example.com"
    )
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000, "message": "ご質問はお電話ください 090-1234-5678 まで"},
        headers=_auth(op_token),
    )
    assert r.status_code == 422
    assert "連絡先" in r.json()["detail"]

    # 422時にDB副作用が残らないこと（入札レコードが作成されず、案件がopenのまま）の回帰保証。
    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(user_token))
    assert r.status_code == 200
    assert r.json() == []

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.status_code == 200
    assert r.json()["status"] == "open"


async def test_bid_message_without_contact_info_accepted_201(
    client: AsyncClient, db_session: AsyncSession
):
    """連絡先やURLを含まない通常の入札メッセージは201で受け付けられる。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "guard_ok_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "guard_ok_op@example.com"
    )
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000, "message": "丁寧に対応いたします。よろしくお願いします。"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201


async def test_transaction_list_has_review_reflects_user_review(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /transactions の has_review は、成約完了直後は false、
    ユーザーレビュー投稿後は true に切り替わる（通知の恒久残存防止用フラグ）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "op_has_review@example.com"
    )
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(op_token),
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
        headers=_auth(user_token),
    )
    txn_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
    )
    assert r.status_code == 200

    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200
    txn_item = next(t for t in r.json() if t["id"] == txn_id)
    assert txn_item["has_review"] is False

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "とても良かったです"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201

    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200
    txn_item = next(t for t in r.json() if t["id"] == txn_id)
    assert txn_item["has_review"] is True


async def test_cancel_flow_by_operator(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "op1@example.com"
    )
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(op_token),
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
        headers=_auth(user_token),
    )
    txn_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "繁忙期のため対応不可になりました"},
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(user_token))
    assert r.json()["status"] == "cancelled"

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.json()["address"] is None

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
    )
    assert r.status_code == 409


async def test_reviews_only_after_completed(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "op1@example.com"
    )
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 10000}, headers=_auth(op_token)
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    txn_id = r.json()["id"]
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good"},
        headers=_auth(user_token),
    )
    assert r.status_code == 409


async def test_duplicate_review_by_same_party_409(
    client: AsyncClient, db_session: AsyncSession
):
    """成約完了後、同一当事者による2件目のレビュー投稿は409（uq_reviews_transaction_reviewer）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "op_dup_review@example.com"
    )
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 10000}, headers=_auth(op_token)
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    txn_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token)
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "良かったです"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "improve", "comment": "2回目"},
        headers=_auth(user_token),
    )
    assert r.status_code == 409, r.text


# ──────────────────────────── 写真アップロード ────────────────────────────


async def test_upload_roundtrip(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    r = await client.post(
        "/api/v1/upload/presign",
        json={"filename": "room.jpg", "content_type": "image/jpeg"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    presign = r.json()

    r = await client.put(
        presign["upload_url"],
        content=_MINIMAL_JPEG,
        headers={**_auth(token), "Content-Type": "image/jpeg"},
    )
    assert r.status_code == 204

    r = await client.get(presign["public_url"])
    assert r.status_code == 200
    assert r.content == _MINIMAL_JPEG
    storage_key = presign["storage_key"]
    assert r.headers["ETag"] == f'"{storage_key}"'
    # security review 指摘対応: immutable を含めない（認可の反映を最大7日
    # 遅延させないため、ETag による毎回の再検証を必須にする）。
    assert r.headers["Cache-Control"] == "private, no-cache"
    assert r.headers["Vary"] == "Authorization"
    assert r.headers["X-Content-Type-Options"] == "nosniff"

    r = await client.get(
        presign["public_url"], headers={"If-None-Match": f'"{storage_key}"'}
    )
    assert r.status_code == 304
    assert r.headers["ETag"] == f'"{storage_key}"'


async def test_serve_file_rejects_malformed_key_even_with_matching_if_none_match(
    client: AsyncClient, tmp_storage
):
    """security/qa review 指摘対応（回帰テスト）: 304 分岐は形式検証・実在確認の

    *後* にある必要がある。一度もアップロードされたことがなく ``_KEY_RE`` の
    形式にすら一致しないキーへ If-None-Match を偽装しても、304 ではなく
    404 になること（qa-reviewer が実証した具体的な突破口）。
    """
    malformed_key = "not-a-valid-storage-key"
    r = await client.get(
        f"/api/v1/files/{malformed_key}",
        headers={"If-None-Match": f'"{malformed_key}"'},
    )
    assert r.status_code == 404


async def test_serve_file_rejects_well_formed_but_unuploaded_key_with_if_none_match(
    client: AsyncClient, tmp_storage
):
    """形式は正しい（``_KEY_RE`` に一致する）が、一度もアップロードされていない
    キーへ If-None-Match を偽装しても 304 ではなく 404 になること
    （根本原因: 実在確認なしに ETag 一致だけで 304 を返していたこと）。
    """
    well_formed_but_never_uploaded_key = f"{uuid.uuid4().hex}.jpg"
    r = await client.get(
        f"/api/v1/files/{well_formed_but_never_uploaded_key}",
        headers={"If-None-Match": f'"{well_formed_but_never_uploaded_key}"'},
    )
    assert r.status_code == 404


async def test_upload_requires_authentication(client: AsyncClient, tmp_storage):
    """PUT /upload/{storage_key} は認証必須（security review 指摘対応:
    storage_key の推測不能性のみに依存した無認証capability URLの是正）。"""
    token = await _signup_user(client)
    r = await client.post(
        "/api/v1/upload/presign",
        json={"filename": "room.jpg", "content_type": "image/jpeg"},
        headers=_auth(token),
    )
    presign = r.json()
    r = await client.put(
        presign["upload_url"],
        content=b"\xff\xd8\xff\xe0fakejpegbytes",
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 401


async def test_upload_rejects_duplicate_storage_key(client: AsyncClient, tmp_storage):
    """同一 storage_key への2回目のPUT（上書き）は409になる（security review 指摘対応）。"""
    token = await _signup_user(client)
    r = await client.post(
        "/api/v1/upload/presign",
        json={"filename": "room.jpg", "content_type": "image/jpeg"},
        headers=_auth(token),
    )
    presign = r.json()
    r = await client.put(
        presign["upload_url"],
        content=_MINIMAL_JPEG,
        headers={**_auth(token), "Content-Type": "image/jpeg"},
    )
    assert r.status_code == 204

    # メタデータ除去後も内容が異なる JPEG（量子化テーブルの係数を1つだけ変えた有効な画像）で
    # 上書きを試みる。COM 等のメタデータだけが違う画像だと、除去後に1回目と同じバイト列に
    # なり「別内容での上書き」を検証できないため。
    dqt_first_coeff = _MINIMAL_JPEG.index(b"\xff\xdb\x00\x43\x00") + 5
    different_jpeg = (
        _MINIMAL_JPEG[:dqt_first_coeff]
        + bytes([_MINIMAL_JPEG[dqt_first_coeff] + 1])
        + _MINIMAL_JPEG[dqt_first_coeff + 1 :]
    )
    assert different_jpeg != _MINIMAL_JPEG
    r = await client.put(
        presign["upload_url"],
        content=different_jpeg,
        headers={**_auth(token), "Content-Type": "image/jpeg"},
    )
    assert r.status_code == 409

    # 保存済みの実体は1回目のまま（上書きされていない）。
    r = await client.get(presign["public_url"])
    assert r.status_code == 200
    assert r.content == _MINIMAL_JPEG


async def test_upload_rejects_content_type_spoofing(client: AsyncClient, tmp_storage):
    """Content-Type ヘッダを偽装しても、実バイト列が画像形式でなければ415になる
    （sniff_image_ext によるマジックバイト判定。security review 指摘対応）。"""
    token = await _signup_user(client)
    r = await client.post(
        "/api/v1/upload/presign",
        json={"filename": "room.jpg", "content_type": "image/jpeg"},
        headers=_auth(token),
    )
    presign = r.json()
    r = await client.put(
        presign["upload_url"],
        content=b"not-an-image-payload",
        headers={**_auth(token), "Content-Type": "image/jpeg"},
    )
    assert r.status_code == 415


async def test_upload_rejects_invalid_key(client: AsyncClient, tmp_storage):
    token = await _signup_user(client)
    r = await client.put(
        "/api/v1/upload/..%2F..%2Fevil.sh",
        content=b"\xff\xd8\xff\xe0fakejpegbytes",
        headers=_auth(token),
    )
    assert r.status_code in (404, 422)


async def test_upload_translates_storage_unavailable_to_503(
    client: AsyncClient, tmp_storage
):
    """PUT /upload/{key} で storage.save_bytes が StorageUnavailableError を
    送出する場合、500 ではなく 503 として返す（qa review 指摘対応・回帰テスト）。
    """
    token = await _signup_user(client)
    r = await client.post(
        "/api/v1/upload/presign",
        json={"filename": "room.jpg", "content_type": "image/jpeg"},
        headers=_auth(token),
    )
    presign = r.json()
    with patch(
        "app.api.v1.endpoints.case_photos.storage.save_bytes",
        new_callable=AsyncMock,
        side_effect=StorageUnavailableError("R2 put_object に失敗しました"),
    ):
        r = await client.put(
            presign["upload_url"],
            content=_MINIMAL_JPEG,
            headers={**_auth(token), "Content-Type": "image/jpeg"},
        )
    assert r.status_code == 503


async def test_serve_file_translates_storage_unavailable_to_503(
    client: AsyncClient, tmp_storage
):
    """GET /files/{key} で storage.read_bytes が StorageUnavailableError を
    送出する場合、500 ではなく 503 として返す（qa review 指摘対応・回帰テスト）。

    exists() 確認（実在チェック）は通過させ、read_bytes だけが失敗するケースを
    再現するため、事前に実ファイルを書き込んでおく。
    """
    storage_key = f"{uuid.uuid4().hex}.jpg"
    (tmp_storage / storage_key).write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")
    with patch(
        "app.api.v1.endpoints.case_photos.storage.read_bytes",
        new_callable=AsyncMock,
        side_effect=StorageUnavailableError("R2 get_object に失敗しました"),
    ):
        r = await client.get(f"/api/v1/files/{storage_key}")
    assert r.status_code == 503


async def test_serve_file_if_none_match_exists_check_translates_storage_unavailable_to_503(
    client: AsyncClient, tmp_storage
):
    """GET /files/{key} で If-None-Match が一致し 304 判定に入る分岐において、
    ``storage.exists`` が StorageUnavailableError を送出する場合は 503 になる
    （security review 2回目レビュー指摘対応の回帰テスト: exists() は
    If-None-Match 一致時のみ呼ばれる設計になったため、このテストは一致する
    ETag を付けてリクエストする）。
    """
    storage_key = f"{uuid.uuid4().hex}.jpg"
    with patch(
        "app.api.v1.endpoints.case_photos.storage.exists",
        new_callable=AsyncMock,
        side_effect=StorageUnavailableError("R2 head_object に失敗しました"),
    ):
        r = await client.get(
            f"/api/v1/files/{storage_key}",
            headers={"If-None-Match": f'"{storage_key}"'},
        )
    assert r.status_code == 503


async def test_serve_file_rejects_header_injection_via_storage_key(
    client: AsyncClient, tmp_storage
):
    """ヘッダインジェクション退行検知: storage_key にCRLF＋偽ヘッダを埋め込んでも
    404 になり、レスポンスに偽装ヘッダが混入しないこと。
    """
    injected_key = f"{uuid.uuid4().hex}.jpg%0d%0aX-Injected:%201"
    r = await client.get(f"/api/v1/files/{injected_key}")
    assert r.status_code == 404
    assert "X-Injected" not in r.headers


def test_storage_is_valid_key_rejects_crlf_injection():
    """storage.is_valid_key はCRLFを含む文字列を単体でも拒否する
    （ヘッダインジェクション退行検知の単体テスト側）。"""
    assert storage.is_valid_key(f"{uuid.uuid4().hex}.jpg\r\nX-Injected: 1") is False


async def test_case_create_rejects_invalid_storage_key(client: AsyncClient):
    token = await _signup_user(client)
    payload = _case_payload()
    payload["photos"] = [{"storage_key": "../../etc/passwd", "sort_order": 0}]
    r = await client.post("/api/v1/cases", json=payload, headers=_auth(token))
    assert r.status_code == 422


# ──────────────────────────── TASK-2: オープン登録 / vendor_status ────────────────────────────


async def test_open_operator_registration(client: AsyncClient, db_session: AsyncSession):
    """招待コードなしでオープン登録 → vendor_status=pending → 案件閲覧も入札も403（r12 決定1）。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "オープン登録業者テスト",
            "email": "open_op@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["operator"]["vendor_status"] == "pending"
    op_token = data["access_token"]

    user_token = await _signup_user(client, "open_user@example.com")
    case = await _create_case(client, user_token)

    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "approval_required"

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 25000},
        headers=_auth(op_token),
    )
    assert r.status_code == 403


async def test_invited_operator_gets_active(client: AsyncClient, db_session: AsyncSession):
    """招待コードありで登録 → vendor_status=active。"""
    admin_token = await _make_admin(client, db_session)
    code = await _invite_code(client, admin_token)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "招待登録業者テスト",
            "email": "invited_op@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["operator"]["vendor_status"] == "active"


async def test_pending_operator_cannot_bid(client: AsyncClient, db_session: AsyncSession):
    """pending業者（未承認）は案件の閲覧も入札も403でブロックされる（r12 決定1）。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "未承認テスト業者",
            "email": "pending_bid_op@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    pending_op_token = r.json()["access_token"]
    assert r.json()["operator"]["vendor_status"] == "pending"

    user_token = await _signup_user(client, "user_for_pending@example.com")
    case = await _create_case(client, user_token)

    # 閲覧もブロックされる（承認前に他人の自宅写真・所在地を見せない）
    r = await client.get("/api/v1/cases", headers=_auth(pending_op_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "approval_required"
    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(pending_op_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "approval_required"

    # 入札はブロックされる（エラーメッセージは日本語で承認待ちである旨を伝える）
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(pending_op_token),
    )
    assert r.status_code == 403
    assert "承認待ち" in r.json()["detail"]


async def test_deapproved_operator_address_hidden(
    client: AsyncClient, db_session: AsyncSession
):
    """承認済み(active)業者が落札した後、admin取り消しでpendingに戻った場合は
    住所情報が非開示になりawaiting_approval=Trueになる（安全側の経過措置ケース）。
    """
    admin_token = await _make_admin(client, db_session)

    # 1. 招待コードで登録 → active（審査済み前提）
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "deapprove_op@example.com", "取消テスト業者"
    )

    user_token = await _signup_user(client, "user_for_deapprove@example.com")
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 30000},
        headers=_auth(op_token),
    )
    assert r.status_code == 201
    bid_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid_id}/select",
        headers=_auth(user_token),
    )
    assert r.status_code == 201
    txn_id = r.json()["id"]

    # 落札直後（active）は住所開示される
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["address"] is not None

    # 2. admin が承認を取り消す（active → pending）
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["vendor_status"] == "pending"

    # 3. 承認取り消し後は住所非開示・awaiting_approval=True になる
    r = await client.get(
        f"/api/v1/transactions/{txn_id}",
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    txn_data = r.json()
    assert txn_data["address"] is None
    assert txn_data.get("awaiting_approval") is True


async def test_admin_approve_sets_active(client: AsyncClient, db_session: AsyncSession):
    """admin approveでvendor_status=active + verified_atが設定されること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "承認テスト業者",
            "email": "approve_test@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    op_id = r.json()["operator"]["id"]
    op_token = r.json()["access_token"]
    assert r.json()["operator"]["vendor_status"] == "pending"

    # 承認（pending → active）には許可証画像の提出が必須
    r = await client.post(
        "/api/v1/operator/license-image",
        files={"file": ("license.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 256, "image/png")},
        headers=_auth(op_token),
    )
    assert r.status_code == 200, r.text

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["vendor_status"] == "active"
    assert data["verified_at"] is not None

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["vendor_status"] == "pending"
    assert data["verified_at"] is None


async def test_bulk_invite_creation(client: AsyncClient, db_session: AsyncSession):
    """バルク発行: 10件のコードが発行され、lot_nameが設定されること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/admin/invites/bulk",
        json={"count": 10, "lot_name": "テストロット"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["count"] == 10
    assert len(data["codes"]) == 10
    assert data["lot_name"] == "テストロット"
    assert len(set(data["codes"])) == 10
    for code in data["codes"]:
        assert code.startswith("KDZ-")


# ──────────────────────────── 業者事前申込 (/operator-applications) ────────────────────────────


def _application_payload(email: str = "biz@example.com", company: str = "申込テスト株式会社") -> dict:
    return {
        "company_name": company,
        "representative_name": "代表 太郎",
        "registered_address": "東京都千代田区丸の内1-1-1",
        "contact_name": "担当 花子",
        "email": email,
        "phone": "03-1234-5678",
        "business_type": "corp",
        "service_area": "東京都",
        "categories": "家電,家具",
        "message": "よろしくお願いします。",
        "license_number": "第123456789012号",
        "invoice_number": "T1234567890123",
        "bank_account": {
            "bank_name": "みずほ銀行",
            "branch_name": "東京営業部",
            "account_type": "ordinary",
            "account_number": "1234567",
            "account_holder": "シンセイテストカブシキガイシャ",
        },
        "agreed": True,
    }


async def test_operator_application_create_public_201(client: AsyncClient):
    """認証不要で申込でき、201・status=receivedが返る。"""
    r = await client.post(
        "/api/v1/operator-applications", json=_application_payload()
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "received"
    assert "application_id" in data


async def test_operator_application_missing_required_field_422(client: AsyncClient):
    """必須項目（company_name）欠落は422で拒否される。"""
    payload = _application_payload()
    del payload["company_name"]
    r = await client.post("/api/v1/operator-applications", json=payload)
    assert r.status_code == 422


async def test_operator_application_missing_license_number_422(client: AsyncClient):
    """古物商許可番号の欠落は422で拒否される。"""
    payload = _application_payload()
    del payload["license_number"]
    r = await client.post("/api/v1/operator-applications", json=payload)
    assert r.status_code == 422


async def test_operator_application_not_agreed_422(client: AsyncClient):
    """agreed=Falseは422で拒否される。"""
    payload = _application_payload()
    payload["agreed"] = False
    r = await client.post("/api/v1/operator-applications", json=payload)
    assert r.status_code == 422


async def test_operator_application_rate_limit_429(client: AsyncClient):
    """同一IPから制限件数（5件/時間）を超えて申込むと429になる（security review Critical指摘対応）。"""
    ip = "203.0.113.10"
    for i in range(5):
        r = await client.post(
            "/api/v1/operator-applications",
            json=_application_payload(email=f"rate_limit_{i}@example.com"),
            headers={"X-Forwarded-For": ip},
        )
        assert r.status_code == 201

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="rate_limit_over@example.com"),
        headers={"X-Forwarded-For": ip},
    )
    assert r.status_code == 429

    # 別IPからは引き続き申込可能であること（IP単位の絞り込みであることの確認）
    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="rate_limit_other_ip@example.com"),
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert r.status_code == 201


async def test_operator_application_bank_account_not_stored_plaintext(
    client: AsyncClient, db_session: AsyncSession
):
    """口座情報がDB上で平文で保存されていないこと（暗号化されていること）を検証する。"""
    from app.db.models.operator_application import OperatorApplication

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="encrypt_check@example.com"),
    )
    assert r.status_code == 201
    application_id = r.json()["application_id"]

    application = await db_session.get(
        OperatorApplication, uuid.UUID(application_id)
    )
    assert application is not None
    assert application.bank_account_enc is not None
    # 平文の口座番号・口座名義がそのまま暗号文に含まれていないこと
    assert "1234567" not in application.bank_account_enc
    assert "シンセイテストカブシキガイシャ" not in application.bank_account_enc

    # 復号すれば元の値が正しく取り出せること
    from app.core.crypto import decrypt_json

    decrypted = decrypt_json(application.bank_account_enc)
    assert decrypted["account_number"] == "1234567"
    assert decrypted["account_holder"] == "シンセイテストカブシキガイシャ"


async def test_admin_list_operator_applications_masks_bank_account(
    client: AsyncClient, db_session: AsyncSession
):
    """admin一覧が口座情報を下4桁マスクで返すこと。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="mask_check@example.com"),
    )
    assert r.status_code == 201

    r = await client.get(
        "/api/v1/admin/operator-applications", headers=_auth(admin_token)
    )
    assert r.status_code == 200
    body = r.json()
    assert "total" in body and body["total"] >= 1  # M4: 一覧は {items,total} を返す
    applications = body["items"]
    target = next(a for a in applications if a["contact_email"] == "mask_check@example.com")
    assert target["bank_account"]["account_number_masked"] == "***4567"
    assert "1234567" not in str(target["bank_account"])


async def test_admin_operator_applications_require_admin_role(client: AsyncClient):
    """admin以外は業者申込一覧にアクセスできない（403）。"""
    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="no_admin_access@example.com"),
    )
    assert r.status_code == 201

    user_token = await _signup_user(client, "not_admin@example.com")
    r = await client.get(
        "/api/v1/admin/operator-applications", headers=_auth(user_token)
    )
    assert r.status_code == 403


async def test_admin_reveal_bank_account_returns_full_number(
    client: AsyncClient, db_session: AsyncSession
):
    """admin限定の復号エンドポイントは口座番号全桁を返す。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="reveal_check@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.post(
        f"/api/v1/admin/operator-applications/{application_id}/reveal-bank-account",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["account_number"] == "1234567"
    assert data["account_holder"] == "シンセイテストカブシキガイシャ"


async def test_admin_approve_operator_application_issues_invite(
    client: AsyncClient, db_session: AsyncSession
):
    """承認フローでInviteが発行され、申込がapprovedになること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="approve_flow@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["application"]["status"] == "approved"
    assert data["invite_code"].startswith("KDZ-")

    # 発行されたInviteコードで実際に業者登録できること（申込時のemailと同一である必要がある）
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": data["invite_code"],
            "company_name": "申込テスト株式会社",
            "email": "approve_flow@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["operator"]["vendor_status"] == "active"

    # 承認済み申込を再承認しようとすると409
    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


async def test_operator_signup_invite_email_mismatch_403(
    client: AsyncClient, db_session: AsyncSession
):
    """承認発行された招待コード（emailに紐付け済み）を別emailで使おうとすると403になる。

    招待コード漏洩時に第三者が無審査でactive業者アカウントを作成できてしまう
    バイパスを防ぐための照合（security review High指摘対応）。
    """
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="mismatch_owner@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    invite_code = r.json()["invite_code"]

    # 招待コードの発行先とは異なるemailでsignupを試みる → 403
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": invite_code,
            "company_name": "なりすまし株式会社",
            "email": "attacker@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 403

    # Inviteが消費されていない（未使用のまま）ことも確認する
    from sqlalchemy import select as sa_select

    from app.db.models.invite import Invite

    invite = await db_session.scalar(sa_select(Invite).where(Invite.code == invite_code))
    assert invite is not None
    assert invite.used_at is None


async def test_operator_signup_invite_without_email_allows_any_email(
    client: AsyncClient, db_session: AsyncSession
):
    """emailに紐付いていない招待コード（admin/invitesの通常発行分）は従来通り任意emailで使える（回帰確認）。"""
    admin_token = await _make_admin(client, db_session)
    code = await _invite_code(client, admin_token)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "オープン招待株式会社",
            "email": "anyone_can_use@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["operator"]["vendor_status"] == "active"


async def test_admin_reject_operator_application(
    client: AsyncClient, db_session: AsyncSession
):
    """却下フローでstatus=rejected・reject_reasonが記録されること。"""
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="reject_flow@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/reject",
        json={"reject_reason": "古物商許可番号の記載内容に不備があるため"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "rejected"
    assert data["reject_reason"] == "古物商許可番号の記載内容に不備があるため"


async def test_admin_list_operator_applications_status_q_total_and_received_first(
    client: AsyncClient, db_session: AsyncSession
):
    """M4対応: GET /admin/operator-applications の status/q絞込・total・
    並び順（received優先 → created_at降順 → id降順のtie-breaker）を検証する。

    admin/page.tsx・operator-applications/page.tsx のバッジ・フィルタが最新100件
    内のみで、未審査(received)がページ外に埋もれていた不整合（QA r4-review M4）
    の是正。
    """
    from app.db.models.operator_application import OperatorApplication

    admin_token = await _make_admin(client, db_session)

    async def _create(email: str, company: str) -> str:
        r = await client.post(
            "/api/v1/operator-applications",
            json=_application_payload(email=email, company=company),
        )
        assert r.status_code == 201
        return r.json()["application_id"]

    received_old_id = await _create("m4_received_old@example.com", "M4申込A株式会社")
    received_new_id = await _create("m4_received_new@example.com", "M4申込B株式会社")
    approved_id = await _create("m4_approved@example.com", "M4申込C株式会社")
    rejected_id = await _create("m4_rejected@example.com", "M4申込D株式会社")

    # received_old は received_new より古い created_at にする
    # （received 同士の created_at 降順が効いていることを検証するため）。
    old_app = await db_session.get(OperatorApplication, uuid.UUID(received_old_id))
    old_app.created_at = old_app.created_at - timedelta(days=1)
    # approved は received より新しい created_at にしても、received が常に先頭に
    # 来ること（received_first のソートキーが created_at より優先されること）を検証する。
    approved_app = await db_session.get(OperatorApplication, uuid.UUID(approved_id))
    approved_app.created_at = approved_app.created_at + timedelta(days=1)
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{approved_id}/approve", headers=_auth(admin_token)
    )
    assert r.status_code == 200
    r = await client.patch(
        f"/api/v1/admin/operator-applications/{rejected_id}/reject",
        json={"reject_reason": "書類不備"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200

    # 全件（status未指定）: received が先頭2件（新→旧）、以降は非receivedがcreated_at降順。
    r = await client.get("/api/v1/admin/operator-applications", headers=_auth(admin_token))
    assert r.status_code == 200
    body = r.json()
    ids = [item["id"] for item in body["items"]]
    assert ids.index(received_new_id) < ids.index(received_old_id) < ids.index(approved_id)
    assert body["total"] >= 4

    # status絞込
    r = await client.get(
        "/api/v1/admin/operator-applications",
        params={"status": "received"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    returned_ids = {item["id"] for item in body["items"]}
    assert received_new_id in returned_ids and received_old_id in returned_ids
    assert approved_id not in returned_ids and rejected_id not in returned_ids
    assert all(item["status"] == "received" for item in body["items"])

    # q: 会社名の部分一致
    r = await client.get(
        "/api/v1/admin/operator-applications",
        params={"q": "M4申込C"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == approved_id

    # q: メールの部分一致
    r = await client.get(
        "/api/v1/admin/operator-applications",
        params={"q": "m4_rejected"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == rejected_id

    # limit上限（200）超過は422（M4: 既定50・上限200へ変更）
    r = await client.get(
        "/api/v1/admin/operator-applications",
        params={"limit": 201},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422


async def test_admin_list_operator_applications_invalid_status_422(
    client: AsyncClient, db_session: AsyncSession
):
    """M-5対応: status に許可されていない値（綴り違い等）を渡すと422になる。

    是正前は空一覧 {"items":[],"total":0} を無言で返しており、審査待ちキューが
    「0件」に見える無言の失敗になっていた。
    """
    admin_token = await _make_admin(client, db_session)
    r = await client.get(
        "/api/v1/admin/operator-applications",
        params={"status": "pendingg"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422


async def test_admin_list_operator_applications_q_matches_license_number(
    client: AsyncClient, db_session: AsyncSession
):
    """M-1対応: q は会社名/メールに加え古物商許可番号の部分一致でも申込を検索できる。"""
    admin_token = await _make_admin(client, db_session)
    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="license_q_check@example.com"),
    )
    assert r.status_code == 201

    r = await client.get(
        "/api/v1/admin/operator-applications",
        params={"q": "123456789012"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["contact_email"] == "license_q_check@example.com"


async def test_admin_approve_operator_application_existing_operator_409(
    client: AsyncClient, db_session: AsyncSession
):
    """M-3対応: 同じメールのOperatorが既に存在する場合、招待コードを発行せず409。

    是正前は承認が成功したように見えるが、申込者が本登録すると必ず409（重複メール）
    で詰み、運営は問い合わせが来るまで気付けなかった。
    """
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "既存業者株式会社",
            "email": "dup_existing_operator@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="dup_existing_operator@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "このメールアドレスの業者アカウントは既に存在します。招待コードは発行していません。"

    from app.db.models.invite import Invite
    from app.db.models.operator_application import OperatorApplication

    app_row = await db_session.get(OperatorApplication, uuid.UUID(application_id))
    assert app_row.status == "received"  # 審査済みにしない（再承認できる状態を維持）
    invite = await db_session.scalar(
        select(Invite).where(Invite.email == "dup_existing_operator@example.com")
    )
    assert invite is None  # 使用不能な招待コードを発行・送信しない


async def test_operator_application_operator_id_tracked_after_signup(
    client: AsyncClient, db_session: AsyncSession
):
    """M-4対応: 承認発行の招待コードで本登録が完了すると、申込のoperator_idに
    新規Operatorのidが書き込まれる（一覧・詳細どちらのレスポンスにも反映）。
    """
    admin_token = await _make_admin(client, db_session)

    r = await client.post(
        "/api/v1/operator-applications",
        json=_application_payload(email="operator_id_track@example.com"),
    )
    application_id = r.json()["application_id"]

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["application"]["operator_id"] is None  # 承認直後・本登録未完了
    invite_code = r.json()["invite_code"]

    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": invite_code,
            "company_name": "追跡テスト株式会社",
            "email": "operator_id_track@example.com",
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201
    operator_id = r.json()["operator"]["id"]

    r = await client.get(
        f"/api/v1/admin/operator-applications/{application_id}", headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert r.json()["operator_id"] == operator_id

    r = await client.get(
        "/api/v1/admin/operator-applications", headers=_auth(admin_token)
    )
    assert r.status_code == 200
    target = next(a for a in r.json()["items"] if a["id"] == application_id)
    assert target["operator_id"] == operator_id


# ──────────────────────────── チャット・日程調整・プロフィール・最高入札額 ────────────────────────────


async def _create_transaction(
    client: AsyncClient,
    user_token: str,
    op_token: str,
    amount: int = 30000,
) -> tuple[str, str]:
    """案件作成 → 入札 → 落札まで進め、(case_id, transaction_id) を返す。"""
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": amount},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    return case["id"], r.json()["id"]


async def _pending_operator_token(
    client: AsyncClient, db_session: AsyncSession, email: str, company: str = "承認待ち業者"
) -> tuple[str, str]:
    """招待コードなしでオープン登録し、vendor_status=pending のトークンを返す。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": company,
            "email": email,
            "password": "password123",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["operator"]["vendor_status"] == "pending"
    return data["access_token"], data["operator"]["id"]


async def _force_select_bid_for_pending_operator(
    db_session: AsyncSession, case_id: str, op_id: str, amount: int = 20000
) -> str:
    """pending 業者を落札業者として成約を強制生成する（入札API自体は403でブロックされるため
    DB直接操作でテスト用に成約状態を作る）。承認待ち業者でもチャット可能かを検証する目的。
    """
    from app.db.models.bid import Bid
    from app.db.models.case import Case
    from app.db.models.transaction import Transaction

    case = await db_session.get(Case, uuid.UUID(case_id))
    bid = Bid(
        case_id=case.id,
        operator_id=uuid.UUID(op_id),
        amount=amount,
        status="selected",
    )
    db_session.add(bid)
    case.status = "closed"
    await db_session.commit()
    await db_session.refresh(bid)

    txn = Transaction(
        case_id=case.id,
        bid_id=bid.id,
        initial_amount=amount,
        fee_amount=0,
        status="pending",
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)
    return str(txn.id)


# ── メッセージ ──


async def test_messages_non_party_forbidden(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "msg_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "msg_op@example.com")
    other_user_token = await _signup_user(client, "msg_other@example.com")
    other_op_token, _ = await _verified_operator(
        client, db_session, admin_token, "msg_other_op@example.com", "無関係業者"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(other_user_token))
    assert r.status_code == 403
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "なりすまし"},
        headers=_auth(other_op_token),
    )
    assert r.status_code == 403


async def test_suspended_operator_cannot_bid_or_chat_403_dict(
    client: AsyncClient, db_session: AsyncSession
):
    """停止中（is_suspended）業者は入札・チャット送信のいずれも403で拒否される。
    detail は機械可読dict（{"code": "account_suspended", ...}）で、依頼者側
    （assert_user_not_suspended）と同一契約を共用する（deps.assert_operator_not_suspended。
    既存トークンをその場で失効させる）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "susp_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "susp_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    other_case = await _create_case(client, user_token)

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    operator.is_suspended = True
    await db_session.commit()

    r = await client.post(
        f"/api/v1/cases/{other_case['id']}/bids",
        json={"amount": 10000},
        headers=_auth(op_token),
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "account_suspended"

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "訪問予定についてご連絡します"},
        headers=_auth(op_token),
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "account_suspended"


async def test_messages_send_and_after_diff(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "msg_diff_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "msg_diff_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "訪問可能日はいつですか？"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    msg1 = r.json()
    assert msg1["mine"] is True
    assert msg1["sender_type"] == "user"

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(op_token))
    assert r.status_code == 200
    msgs = r.json()
    assert len(msgs) == 1
    assert msgs[0]["mine"] is False

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "来週火曜はいかがですか"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201

    # SQLite（テスト用インメモリDB）は created_at が秒精度のため、同一トランザクション内の
    # 連続送信では msg1/msg2 が同一タイムスタンプになり得る。after 差分取得の境界挙動
    # （strictly greater than）を確実に検証するため、msg1 の created_at を明示的に
    # 1秒巻き戻してから after クエリを実行する。
    from datetime import timedelta

    from app.db.models.message import Message

    msg1_row = await db_session.get(Message, uuid.UUID(msg1["id"]))
    msg1_row.created_at = msg1_row.created_at - timedelta(seconds=1)
    await db_session.commit()
    # after_ts は「巻き戻し後」の msg1_row.created_at をそのまま基準にする。
    # こうすると after クエリは Message.created_at > after_ts（strictly greater
    # than）なので、msg1（= after_ts と同値）は境界で除外され、msg2（元の
    # created_at。msg1 と同一秒で作成されていても巻き戻し後の msg1 より後）だけが
    # 含まれる。巻き戻し前の msg1["created_at"] を使うと、msg1/msg2 が同一秒で
    # 作成された場合に after_ts == msg2.created_at となり msg2 まで除外されて
    # diff が空になり、テストがフレーキーになる。
    after_ts = msg1_row.created_at.isoformat()

    r = await client.get(
        f"/api/v1/transactions/{txn_id}/messages",
        params={"after": after_ts},
        headers=_auth(user_token),
    )
    assert r.status_code == 200
    diff = r.json()
    assert len(diff) == 1
    assert diff[0]["body"] == "来週火曜はいかがですか"


async def test_messages_sender_type_cannot_be_spoofed(
    client: AsyncClient, db_session: AsyncSession
):
    """リクエストボディに sender_type を含めても無視され、actor から自動判定される。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "spoof_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "spoof_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "なりすまし試行", "sender_type": "operator"},
        headers=_auth(user_token),
    )
    assert r.status_code == 201
    assert r.json()["sender_type"] == "user"


async def test_messages_unread_count_after_read(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "unread_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "unread_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "1通目"},
        headers=_auth(user_token),
    )
    await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "2通目"},
        headers=_auth(user_token),
    )

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["unread_count"] == 2

    r = await client.post(f"/api/v1/transactions/{txn_id}/messages/read", headers=_auth(op_token))
    assert r.status_code == 200

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.json()["unread_count"] == 0

    # ユーザー側の未読は業者の既読処理に影響しない
    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.json()["unread_count"] == 0


async def test_pending_operator_can_chat(client: AsyncClient, db_session: AsyncSession):
    """承認待ち(vendor_status=pending)業者が落札した成約でもチャット送受信できる
    （住所非開示のみで会話は許可という確定方針）。
    """
    user_token = await _signup_user(client, "pending_chat_user@example.com")
    case = await _create_case(client, user_token)
    op_token, op_id = await _pending_operator_token(client, db_session, "pending_chat_op@example.com")

    txn_id = await _force_select_bid_for_pending_operator(db_session, case["id"], op_id)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["awaiting_approval"] is True
    assert r.json()["address"] is None

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "承認待ちですが訪問希望日をご相談できますか"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(user_token))
    assert r.status_code == 200
    assert len(r.json()) == 1


# ── 日程調整 ──


async def test_schedule_propose_operator_only(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "sched_propose_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "sched_propose_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["2026-07-10 午前", "2026-07-11 午後"]},
        headers=_auth(user_token),
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["2026-07-10 午前", "2026-07-11 午後"]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "schedule_proposal"
    assert data["meta"]["slots"] == ["2026-07-10 午前", "2026-07-11 午後"]


async def test_schedule_confirm_user_only_and_status_transition(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "sched_confirm_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "sched_confirm_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    # visit_date は「本日以降」バリデーションがあるため、固定日ではなく動的な未来日を使う
    # （固定日だと実行日がそれを過ぎた時点で 422 になり時限失敗する）。
    from datetime import date, timedelta

    visit_date = (date.today() + timedelta(days=7)).isoformat()

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": visit_date, "visit_time_slot": "午前"},
        headers=_auth(op_token),
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": visit_date, "visit_time_slot": "午前", "note": "在宅確認済み"},
        headers=_auth(user_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "visiting"
    assert data["visit_date"] == visit_date
    assert data["visit_time_slot"] == "午前"

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(user_token))
    assert r.status_code == 200
    kinds = [m["kind"] for m in r.json()]
    assert "schedule_confirmed" in kinds


# ── 開示ゲート回帰（既存フローが壊れていないこと） ──


async def test_regression_full_flow_still_passes_with_new_fields(
    client: AsyncClient, db_session: AsyncSession
):
    """既存の落札〜成約詳細取得フローが新規カラム追加後も200で動作し、
    新規フィールド（unread_count, visit_time_slot）が妥当な初期値を持つこと。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "regression_user@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "regression_op@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    assert r.status_code == 200
    data = r.json()
    assert data["unread_count"] == 0
    assert data["visit_time_slot"] is None
    assert data["address"] is not None


# ── プロフィール ──


async def test_operator_profile_strong_categories_must_be_subset(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "profile_subset_op@example.com")

    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都"],
            "categories": ["家電", "家具"],
            "strong_categories": ["家電", "書籍"],
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 422


async def test_operator_profile_intro_message_with_contact_info_rejected_422(
    client: AsyncClient, db_session: AsyncSession
):
    """intro_messageに電話番号が含まれる場合は422で拒否され、DBに保存されない
    （show_message=True時に公開プロフィールで無認証ユーザーへ表示されるため、
    脱プラットフォーム勧誘対策としてbids.pyの入札メッセージと同様のガードを適用）。"""
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "profile_guard_op@example.com"
    )

    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都"],
            "categories": ["家電"],
            "strong_categories": ["家電"],
            "intro_message": "ご相談はお電話ください 090-1234-5678 まで",
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 422
    assert "連絡先" in r.json()["detail"]

    # DB副作用が残らないこと（再取得してもintro_messageが未設定のまま）の回帰保証。
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["intro_message"] is None


async def test_operator_profile_intro_message_without_contact_info_accepted(
    client: AsyncClient, db_session: AsyncSession
):
    """連絡先やURLを含まない通常のintro_messageは正常に更新できる。"""
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "profile_guard_ok_op@example.com"
    )

    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都"],
            "categories": ["家電"],
            "strong_categories": ["家電"],
            "intro_message": "丁寧に対応いたします。よろしくお願いします。",
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    assert r.json()["intro_message"] == "丁寧に対応いたします。よろしくお願いします。"


async def test_operator_profile_update_intro_message_key_omitted_succeeds(
    client: AsyncClient, db_session: AsyncSession
):
    """intro_messageキーを省略したPUT（他は全フィールド正当値）も、
    連絡先ガードが誤発動せず200で通ること（None入力での過剰検知回帰防止）。"""
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "profile_guard_omit_op@example.com"
    )

    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都"],
            "categories": ["家電"],
            "strong_categories": ["家電"],
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    assert r.json()["intro_message"] is None


async def test_operator_profile_update_ignores_verified_fields(
    client: AsyncClient, db_session: AsyncSession
):
    """company_name 等の審査確定項目を PUT ボディに含めても無視され、更新されないこと。"""
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "profile_immutable_op@example.com", "元の会社名"
    )

    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "company_name": "書き換え試行株式会社",
            "license_number": "第000000000000号",
            "areas": ["東京都", "神奈川県"],
            "categories": ["家電"],
            "strong_categories": ["家電"],
            "business_hours": "9:00-18:00",
            "intro_message": "丁寧に対応します。",
            "show_message": True,
            "accept_unsellable": True,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["company_name"] == "元の会社名"
    assert data["areas"] == ["東京都", "神奈川県"]
    assert data["accept_unsellable"] is True

    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 200
    assert r.json()["company_name"] == "元の会社名"


async def test_operator_profile_first_access_auto_creates(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, _ = await _verified_operator(client, db_session, admin_token, "profile_autocreate_op@example.com")

    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 200
    data = r.json()
    assert data["areas"] == []
    assert "is_public" not in data
    assert data["review_count"] == 0


async def test_vendor_public_profile_respects_show_flags(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "public_profile_op@example.com", "公開プロフィール株式会社"
    )
    await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都"],
            "categories": ["家電"],
            "strong_categories": ["家電"],
            "intro_message": "秘密のメッセージ",
            "show_message": False,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )

    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["intro_message"] is None  # show_message=False のため省かれる
    assert data["company_name"] == "公開プロフィール株式会社"


async def test_vendor_public_profile_reviews_user_only_and_minimal_fields(
    client: AsyncClient, db_session: AsyncSession
):
    """無認証の公開プロフィールに (a)業者が顧客について書いたレビューが混入しない
    (b)内部識別子(transaction_id)・reviewer_type が露出しない ことの回帰テスト。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "pubreview_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "pubreview_op@example.com", "公開レビュー株式会社"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200

    # 双方向レビュー: 顧客→業者 と 業者→顧客
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "丁寧でした"},
        headers=_auth(user_token),
    )
    assert r.status_code in (200, 201)
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "improve", "comment": "顧客対応の内部メモ"},
        headers=_auth(op_token),
    )
    assert r.status_code in (200, 201)

    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 200
    reviews = r.json()["reviews"]
    assert reviews is not None and len(reviews) == 1  # 顧客→業者のみ
    assert reviews[0]["comment"] == "丁寧でした"
    assert "transaction_id" not in reviews[0]
    assert "reviewer_type" not in reviews[0]


async def test_vendor_public_profile_visible_regardless_of_profile_settings(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "private_profile_op@example.com", "非公開株式会社"
    )
    await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": [],
            "categories": [],
            "strong_categories": [],
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )

    # 口コミ・評価は常時公開（2026-09-04 決定）。旧 is_public=False 相当の設定でも 200。
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 200
    assert r.json()["reviews"] == []
    assert r.json()["review_count"] == 0


async def test_vendor_public_profile_default_public_when_profile_row_missing(
    client: AsyncClient, db_session: AsyncSession
):
    """プロフィール行が未作成（業者が一度もプロフィール画面を開いていない）でも、
    既定は公開(is_public default=True)なので 404 にしない。
    チャットの「プロフィールを見る」導線の回帰テスト。"""
    admin_token = await _make_admin(client, db_session)
    _, op_id = await _verified_operator(
        client, db_session, admin_token, "no_profile_row_op@example.com", "行未作成株式会社"
    )
    # GET /operator/profile（遅延作成トリガー）を呼ばないまま公開プロフィールを参照する
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["company_name"] == "行未作成株式会社"
    assert data["areas"] == []
    # GET では行を作成しない（副作用なし）
    from app.db.models.operator_profile import OperatorProfile
    import uuid as _uuid

    assert await db_session.get(OperatorProfile, _uuid.UUID(op_id)) is None


# ── 他社入札額の非開示（r12 決定2。旧「最高入札額」テストを反転） ──


async def test_other_operators_bid_amount_is_disclosed_anonymously(
    client: AsyncClient, db_session: AsyncSession
):
    """2026-09-07 決定: 他社の入札額は開示するが、社名は非開示のまま。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "topbid_user@example.com")
    op1_token, _ = await _verified_operator(client, db_session, admin_token, "topbid_op1@example.com", "A社")
    op2_token, _ = await _verified_operator(client, db_session, admin_token, "topbid_op2@example.com", "B社")
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 40000}, headers=_auth(op1_token)
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 55000}, headers=_auth(op2_token)
    )
    assert r.status_code == 201

    # 業者向け一覧・詳細は他社の最高額（55000）を top_bid_amount として開示するが、
    # 他社の社名は現れない（自社分は my_bid.operator 経由で自社名のみ見える）。
    r = await client.get("/api/v1/cases", headers=_auth(op1_token))
    assert r.status_code == 200
    target = next(c for c in r.json() if c["id"] == case["id"])
    assert target["top_bid_amount"] == 55000
    assert target["is_top_bidder"] is False
    assert target["bid_count"] == 2
    assert target["my_bid"]["amount"] == 40000
    assert "B社" not in r.text  # 他社(B社)の社名は非開示
    assert "A社" in r.text  # 自社(A社)は my_bid.operator 経由で見える

    r = await client.get(f"/api/v1/cases/{case['id']}", headers=_auth(op2_token))
    assert r.status_code == 200
    body = r.json()
    assert body["top_bid_amount"] == 55000
    assert body["is_top_bidder"] is True
    assert body["bid_count"] == 2
    assert body["my_bid"]["amount"] == 55000
    assert "A社" not in r.text  # 他社(A社)の社名は非開示
    assert "B社" in r.text  # 自社(B社)は my_bid.operator 経由で見える

    # 入札一覧: 他社分は金額のみ・社名なし。自社分は社名込みで見える。
    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(op1_token))
    assert r.status_code == 200
    bids = {b["amount"]: b for b in r.json()}
    assert bids[55000]["is_mine"] is False
    assert bids[55000]["operator"] is None
    assert bids[40000]["is_mine"] is True
    assert bids[40000]["operator"]["company_name"] == "A社"
    assert "B社" not in r.text


async def test_review_updates_operator_review_stats_and_bid_summary(
    client: AsyncClient, db_session: AsyncSession
):
    """顧客→業者レビュー投稿で operators.review_count / latest_review_comment が更新され、
    入札一覧（BidOut.operator）と公開プロフィール・業者一覧に反映される。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "revstats_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "revstats_op@example.com", "集計株式会社"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "  搬出が早くて助かりました  "},
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    # 業者→顧客のレビューは集計に含めない
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "improve", "comment": "内部メモ"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201

    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 200
    data = r.json()
    assert (data["good_count"], data["improve_count"], data["review_count"]) == (1, 0, 1)
    assert len(data["reviews"]) == 1

    # 2件目の案件で入札一覧に集計が載る
    case2 = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case2['id']}/bids", json={"amount": 25000}, headers=_auth(op_token)
    )
    assert r.status_code == 201
    r = await client.get(f"/api/v1/cases/{case2['id']}/bids", headers=_auth(user_token))
    assert r.status_code == 200
    op_summary = r.json()[0]["operator"]
    assert (op_summary["good_count"], op_summary["improve_count"], op_summary["review_count"]) == (1, 0, 1)
    assert op_summary["latest_review_comment"] == "搬出が早くて助かりました"

    # 業者一覧
    r = await client.get("/api/v1/vendors")
    assert r.status_code == 200
    row = next(v for v in r.json() if v["operator_id"] == op_id)
    assert row["company_name"] == "集計株式会社"
    assert (row["good_count"], row["improve_count"], row["review_count"]) == (1, 0, 1)
    assert row["latest_review_comment"] == "搬出が早くて助かりました"
    assert "contact_email" not in row and "license_number" not in row

    # 運営が非表示にすると公開・集計から消え、再表示で戻る
    review_id = data["reviews"][0]["id"]
    r = await client.patch(
        f"/api/v1/admin/reviews/{review_id}/hide",
        json={"hidden": True, "reason": "第三者の個人情報を含むため"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["hidden_at"] is not None
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.json()["reviews"] == []
    assert (r.json()["good_count"], r.json()["improve_count"], r.json()["review_count"]) == (0, 0, 0)
    r = await client.patch(
        f"/api/v1/admin/reviews/{review_id}/hide", json={"hidden": False}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert (r.json()["good_count"], r.json()["improve_count"], r.json()["review_count"]) == (1, 0, 1)
    # 一般ユーザーは非表示操作できない
    r = await client.patch(
        f"/api/v1/admin/reviews/{review_id}/hide", json={"hidden": True}, headers=_auth(user_token)
    )
    assert r.status_code in (401, 403)


async def test_review_comment_rejects_contact_info_and_profile_lists_reject_urls(
    client: AsyncClient, db_session: AsyncSession
):
    """口コミ本文と業者プロフィールのエリア/カテゴリは公開されるため、連絡先・URL を拒否する。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "revguard_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "revguard_op@example.com", "ガード株式会社"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "直接依頼は https://evil.example へ"},
        headers=_auth(user_token),
    )
    assert r.status_code == 422
    r = await client.put(
        "/api/v1/operator/profile",
        json={
            "areas": ["東京都", "直通 090-1234-5678"],
            "categories": [],
            "strong_categories": [],
            "show_message": True,
            "accept_unsellable": False,
        },
        headers=_auth(op_token),
    )
    assert r.status_code == 422


# ──────────────────────────── 評価の2択化（よかった／伸びしろ・2026-09-25） ────────────────────────────
# ★（rating）は alembic 0042 で撤去済み（入力・応答・集計に無い。DB 列は残置し書き込まない）。

_REVIEWS_LOGGER = "app.api.v1.endpoints.reviews"


async def _completed_transaction(client: AsyncClient, user_token: str, op_token: str) -> str:
    """案件作成 → 入札 → 落札 → 完了まで進め、transaction_id を返す（評価を投稿できる状態）。"""
    _, txn_id = await _create_transaction(client, user_token, op_token)
    r = await client.post(f"/api/v1/transactions/{txn_id}/complete", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    return txn_id


def _verdict_counts(data: dict) -> tuple[int, int, int]:
    """応答の (good_count, improve_count, review_count)。"""
    return data["good_count"], data["improve_count"], data["review_count"]


async def _public_verdict_counts(client: AsyncClient, op_id: str) -> tuple[int, int, int]:
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.status_code == 200, r.text
    return _verdict_counts(r.json())


async def _post_review(client: AsyncClient, token: str, payload: dict) -> dict:
    r = await client.post("/api/v1/reviews", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _review_logs(caplog, prefix: str) -> list[str]:
    """reviews.py のログのうち、指定の接頭辞で始まるもの（競合の記録など）。"""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _REVIEWS_LOGGER and r.getMessage().startswith(prefix)
    ]


async def test_review_verdict_saves_without_rating_and_counts_on_every_operator_output(
    client: AsyncClient, db_session: AsyncSession
):
    """T1: verdict で投稿 → 201・ReviewOut.verdict。★（rating）は保存しない（NULL）。
    業者の件数は公開プロフィール・自社プロフィール・業者一覧・入札一覧に同じ値で載る。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_t1_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "verdict_t1_op@example.com", "評価株式会社"
    )
    for verdict in ("good", "improve"):
        txn_id = await _completed_transaction(client, user_token, op_token)
        body = await _post_review(client, user_token, {"transaction_id": txn_id, "verdict": verdict})
        assert body["verdict"] == verdict and "rating" not in body
        stored = (
            await db_session.execute(
                select(Review.verdict, Review.rating).where(Review.id == uuid.UUID(body["id"]))
            )
        ).one()
        assert tuple(stored) == (verdict, None)

    assert await _public_verdict_counts(client, op_id) == (1, 1, 2)
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert _verdict_counts(r.json()) == (1, 1, 2)
    r = await client.get("/api/v1/vendors")
    assert _verdict_counts(next(v for v in r.json() if v["operator_id"] == op_id)) == (1, 1, 2)
    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 25000}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(user_token))
    assert _verdict_counts(r.json()[0]["operator"]) == (1, 1, 2)


@pytest.mark.parametrize("reviewer", ["user", "operator"])
async def test_review_rating_only_payload_is_rejected_because_verdict_is_required(
    client: AsyncClient, db_session: AsyncSession, reviewer: str
):
    """T2: 旧形式（★の rating だけ）の投稿は、★の撤去（alembic 0042）後は verdict が無いため 422。
    依頼者・業者のどちらからでも同じで、行は作られず、その後の verdict での投稿は通る。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_t2_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "verdict_t2_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)
    token = user_token if reviewer == "user" else op_token

    r = await client.post(
        "/api/v1/reviews", json={"transaction_id": txn_id, "rating": 5}, headers=_auth(token)
    )
    assert r.status_code == 422, r.text
    assert any(err["loc"][-1] == "verdict" for err in r.json()["detail"])
    body = await _post_review(client, token, {"transaction_id": txn_id, "verdict": "good"})
    assert body["reviewer_type"] == reviewer


async def test_review_invalid_verdict_is_rejected_and_stray_rating_is_ignored(
    client: AsyncClient, db_session: AsyncSession
):
    """T3: verdict が無い・未知の値は 422 で、行は作られない（後続の正常投稿が 409 にならない）。
    rating を併せて送られても保存しない（★は撤去済み。入力モデルに無い項目として無視する）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_t3_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "verdict_t3_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)

    for bad_payload in (
        {"transaction_id": txn_id},
        {"transaction_id": txn_id, "verdict": "bad"},
        {"transaction_id": txn_id, "verdict": "GOOD"},
        {"transaction_id": txn_id, "verdict": None},
    ):
        r = await client.post("/api/v1/reviews", json=bad_payload, headers=_auth(user_token))
        assert r.status_code == 422, (bad_payload, r.text)

    body = await _post_review(
        client, user_token, {"transaction_id": txn_id, "verdict": "improve", "rating": 5}
    )
    assert body["verdict"] == "improve" and "rating" not in body
    stored_rating = await db_session.scalar(
        select(Review.rating).where(Review.id == uuid.UUID(body["id"]))
    )
    assert stored_rating is None


async def test_review_comment_limit_is_300_characters(
    client: AsyncClient, db_session: AsyncSession
):
    """口コミの上限は 300 字（web の REVIEW_COMMENT_MAX と同じ値。app/core/limits.py が唯一の定義）。
    ちょうど 300 字は通り、301 字は 422。"""
    from app.core.limits import REVIEW_COMMENT_MAX_LENGTH

    assert REVIEW_COMMENT_MAX_LENGTH == 300
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_limit_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "verdict_limit_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)

    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": txn_id, "verdict": "good", "comment": "あ" * 301},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    body = await _post_review(
        client, user_token, {"transaction_id": txn_id, "verdict": "good", "comment": "あ" * 300}
    )
    assert body["comment"] == "あ" * 300


async def test_review_non_party_and_invalid_state_return_before_taking_the_lock(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """第三者（当事者でない依頼者・業者）の投稿は行ロックを取る前に 403 になる（取引 ID を知るだけの
    第三者に行ロックを掴ませない。transactions.py の「ロック前に当事者確認」r6-verify-fix M1 と
    同じ規約）。存在しない取引の 404・未完了の 409 もロック前に返り、当事者の正常な投稿では
    ロックを1回だけ取る。判定順・文言・ステータスコードは従来どおり。"""
    from app.api.v1.endpoints import reviews as reviews_endpoint

    lock_calls: list[uuid.UUID] = []
    original_lock = reviews_endpoint.lock_transaction_rows

    async def _observed_lock(session, txn_id):
        lock_calls.append(txn_id)
        return await original_lock(session, txn_id)

    monkeypatch.setattr(reviews_endpoint, "lock_transaction_rows", _observed_lock)
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_lock_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "verdict_lock_op@example.com"
    )
    outsider_user_token = await _signup_user(client, "verdict_lock_outsider@example.com")
    outsider_op_token, _ = await _verified_operator(
        client, db_session, admin_token, "verdict_lock_outsider_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)
    _, open_txn_id = await _create_transaction(client, user_token, op_token)

    for token in (outsider_user_token, outsider_op_token):
        r = await client.post(
            "/api/v1/reviews", json={"transaction_id": txn_id, "verdict": "good"}, headers=_auth(token)
        )
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == "この成約への権限がありません。"
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": str(uuid.uuid4()), "verdict": "good"},
        headers=_auth(user_token),
    )
    assert r.status_code == 404 and r.json()["detail"] == "成約情報が見つかりません。"
    r = await client.post(
        "/api/v1/reviews",
        json={"transaction_id": open_txn_id, "verdict": "good"},
        headers=_auth(user_token),
    )
    assert r.status_code == 409 and r.json()["detail"] == "レビューは成約完了後に投稿できます。"
    assert lock_calls == [], "第三者・存在しない取引・未完了の取引ではロックを取らない"

    await _post_review(client, user_token, {"transaction_id": txn_id, "verdict": "good"})
    assert lock_calls == [uuid.UUID(txn_id)]


async def test_operator_to_user_verdict_is_excluded_from_operator_counts(
    client: AsyncClient, db_session: AsyncSession
):
    """T4: 業者→依頼者の評価は業者の集計（件数・内訳）に入らない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_t4_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "verdict_t4_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)
    await _post_review(client, user_token, {"transaction_id": txn_id, "verdict": "good"})
    body = await _post_review(client, op_token, {"transaction_id": txn_id, "verdict": "improve"})
    assert (body["reviewer_type"], body["verdict"]) == ("operator", "improve")
    assert await _public_verdict_counts(client, op_id) == (1, 0, 1)


async def test_admin_hide_and_unhide_move_verdict_counts_consistently(
    client: AsyncClient, db_session: AsyncSession
):
    """T5: 運営の非表示で件数・内訳が減り、再表示で戻る（常に review_count = good + improve）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_t5_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "verdict_t5_op@example.com"
    )
    good_txn = await _completed_transaction(client, user_token, op_token)
    await _post_review(client, user_token, {"transaction_id": good_txn, "verdict": "good"})
    improve_txn = await _completed_transaction(client, user_token, op_token)
    improve_review = await _post_review(
        client, user_token, {"transaction_id": improve_txn, "verdict": "improve"}
    )
    assert await _public_verdict_counts(client, op_id) == (1, 1, 2)

    r = await client.patch(
        f"/api/v1/admin/reviews/{improve_review['id']}/hide",
        json={"hidden": True, "reason": "第三者の個人情報を含むため"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] == "improve" and r.json()["hidden_at"] is not None
    assert await _public_verdict_counts(client, op_id) == (1, 0, 1)

    r = await client.patch(
        f"/api/v1/admin/reviews/{improve_review['id']}/hide",
        json={"hidden": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert await _public_verdict_counts(client, op_id) == (1, 1, 2)


async def test_review_unique_violation_at_flush_returns_409_and_leaves_nothing(
    client: AsyncClient, db_session: AsyncSession, caplog
):
    """同時の二重投稿の後発が flush（INSERT）で uq_reviews_transaction_reviewer に当たっても、
    500 ではなく 409 になり、ロールバックで評価も集計も残らない（その後の正常投稿は通る）。

    アプリ層の重複チェックを通った後・flush の直前に「同じ取引・同じ投稿者の評価」を割り込ませ、
    本物の一意制約違反を起こす（テスト DB にもモデルの UniqueConstraint で同じ制約がある）。"""
    from sqlalchemy import event, func

    caplog.set_level(logging.INFO, logger=_REVIEWS_LOGGER)
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_race_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "verdict_race_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)
    injected: list[Review] = []

    def _inject_concurrent_duplicate(session, flush_context, instances) -> None:
        pending = [
            obj
            for obj in session.new
            if isinstance(obj, Review) and obj.transaction_id == uuid.UUID(txn_id)
        ]
        if pending and not injected:
            duplicate = Review(
                transaction_id=uuid.UUID(txn_id),
                reviewer_type=pending[0].reviewer_type,
                verdict="good",
            )
            injected.append(duplicate)
            session.add(duplicate)

    event.listen(db_session.sync_session, "before_flush", _inject_concurrent_duplicate)
    try:
        r = await client.post(
            "/api/v1/reviews",
            json={"transaction_id": txn_id, "verdict": "improve"},
            headers=_auth(user_token),
        )
    finally:
        event.remove(db_session.sync_session, "before_flush", _inject_concurrent_duplicate)
    assert injected, "割り込みが発火していない（flush より前に止まった）"
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "既にレビュー投稿済みです。"
    assert _review_logs(caplog, "review_create_conflict") == [
        f"review_create_conflict transaction={txn_id} reviewer_type=user error=IntegrityError"
    ]
    remaining = await db_session.scalar(
        select(func.count()).select_from(Review).where(Review.transaction_id == uuid.UUID(txn_id))
    )
    assert remaining == 0
    assert await _public_verdict_counts(client, op_id) == (0, 0, 0)

    await _post_review(client, user_token, {"transaction_id": txn_id, "verdict": "improve"})
    assert await _public_verdict_counts(client, op_id) == (0, 1, 1)


async def test_review_non_unique_integrity_error_returns_500_without_leaking_the_comment(
    client: AsyncClient, db_session: AsyncSession, caplog
):
    """一意制約（uq_reviews_transaction_reviewer）以外の IntegrityError は 409 に偽装せず 500 にする
    （例: 段B のコードが 0041 のスキーマで動き rating の NOT NULL に当たる。5xx 監視に載せる）。
    ログは取引・投稿者種別・例外の型・sqlstate・制約名だけで、口コミ本文を出さない。
    再現: flush の直前に評価の verdict を NULL にし、本物の NOT NULL 違反を起こす。"""
    from sqlalchemy import event, func

    caplog.set_level(logging.INFO, logger=_REVIEWS_LOGGER)
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_500_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "verdict_500_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)
    secret_comment = "口コミ本文はログに出さない"

    def _break_not_null(session, flush_context, instances) -> None:
        for obj in session.new:
            if isinstance(obj, Review) and obj.transaction_id == uuid.UUID(txn_id):
                obj.verdict = None

    event.listen(db_session.sync_session, "before_flush", _break_not_null)
    try:
        r = await client.post(
            "/api/v1/reviews",
            json={"transaction_id": txn_id, "verdict": "good", "comment": secret_comment},
            headers=_auth(user_token),
        )
    finally:
        event.remove(db_session.sync_session, "before_flush", _break_not_null)
    assert r.status_code == 500, r.text
    assert r.json()["detail"] == "評価の保存に失敗しました。時間をおいて再度お試しください。"
    assert _review_logs(caplog, "review_create_integrity_error") == [
        f"review_create_integrity_error transaction={txn_id} reviewer_type=user"
        " error=IntegrityError sqlstate=None constraint=None"
    ]
    assert _review_logs(caplog, "review_create_conflict") == []
    assert all(secret_comment not in record.getMessage() for record in caplog.records)
    remaining = await db_session.scalar(
        select(func.count()).select_from(Review).where(Review.transaction_id == uuid.UUID(txn_id))
    )
    assert remaining == 0
    assert await _public_verdict_counts(client, op_id) == (0, 0, 0)


def test_classify_integrity_error_by_asyncpg_sqlstate_and_constraint_name():
    """409 にするのは uq_reviews_transaction_reviewer の違反だけ（PostgreSQL は sqlstate 23505 かつ
    制約名、SQLite は文言）。PostgreSQL の形は SQLAlchemy の asyncpg アダプタ
    （sqlalchemy/dialects/postgresql/asyncpg.py の AsyncAdapt_asyncpg_connection._handle_exception）と
    同じく、実クラスで組み立てる: 元の asyncpg 例外を __cause__ に付け、sqlstate を orig の
    pgcode / sqlstate に写す。制約名は asyncpg 例外の constraint_name（サーバの 'n' フィールド）。"""
    import sqlite3

    from asyncpg.exceptions import PostgresError
    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
    from sqlalchemy.exc import IntegrityError

    from app.api.v1.endpoints.reviews import _classify_integrity_error

    def asyncpg_shaped(fields: dict) -> IntegrityError:
        asyncpg_error = PostgresError.new(fields)  # sqlstate（'C'）から具体的な例外クラスが選ばれる
        translated = AsyncAdapt_asyncpg_dbapi.IntegrityError(f"{type(asyncpg_error)}: {asyncpg_error}")
        translated.pgcode = translated.sqlstate = asyncpg_error.sqlstate
        translated.__cause__ = asyncpg_error  # アダプタは raise translated_error from error で送出する
        return IntegrityError("INSERT INTO reviews ...", {"comment": "本文"}, translated)

    unique_ours = asyncpg_shaped(
        {"C": "23505", "M": "duplicate key value", "n": "uq_reviews_transaction_reviewer"}
    )
    assert type(unique_ours.orig.__cause__).__name__ == "UniqueViolationError"
    assert _classify_integrity_error(unique_ours) == (True, "23505", "uq_reviews_transaction_reviewer")
    assert _classify_integrity_error(
        asyncpg_shaped({"C": "23505", "M": "duplicate key value", "n": "pk_reviews"})
    ) == (False, "23505", "pk_reviews")
    assert _classify_integrity_error(
        asyncpg_shaped({"C": "23502", "M": "null value in column", "c": "rating", "t": "reviews"})
    ) == (False, "23502", None)
    assert _classify_integrity_error(
        asyncpg_shaped({"C": "23514", "M": "violates check constraint", "n": "ck_reviews_verdict"})
    ) == (False, "23514", "ck_reviews_verdict")

    def sqlite_shaped(message: str) -> IntegrityError:
        return IntegrityError("INSERT INTO reviews ...", {}, sqlite3.IntegrityError(message))

    assert _classify_integrity_error(
        sqlite_shaped("UNIQUE constraint failed: reviews.transaction_id, reviews.reviewer_type")
    ) == (True, None, None)
    assert _classify_integrity_error(sqlite_shaped("UNIQUE constraint failed: reviews.id")) == (
        False,
        None,
        None,
    )
    assert _classify_integrity_error(sqlite_shaped("NOT NULL constraint failed: reviews.rating")) == (
        False,
        None,
        None,
    )


async def test_vendor_list_orders_by_good_then_fewer_improve_then_oldest(
    client: AsyncClient, db_session: AsyncSession
):
    """T7: GET /vendors は『よかった』の多い順 → 同数なら『伸びしろ』の少ない順 →
    登録の古い順 → id（ページ送りの順序を決定的にする最後の決着）。"""
    from datetime import datetime, timezone

    base_time = datetime(2026, 9, 1, tzinfo=timezone.utc)
    # (会社名, よかった, 伸びしろ, 登録日のずらし（日）)。件数は並び順だけを見るため直接置く。
    specs = [
        ("G0I1-x", 0, 1, 4),
        ("G3I2", 3, 2, 0),
        ("G0I0", 0, 0, 0),
        ("G3I0-new", 3, 0, 2),
        ("G5I5", 5, 5, 3),
        ("G3I0-old", 3, 0, 1),
        ("G0I1-y", 0, 1, 4),
    ]
    for index, (name, good, improve, days) in enumerate(specs):
        db_session.add(
            Operator(
                company_name=name,
                contact_email=f"verdict_order_{index}@example.com",
                vendor_status="active",
                good_count=good,
                improve_count=improve,
                review_count=good + improve,
                created_at=base_time + timedelta(days=days),
            )
        )
    await db_session.commit()

    r = await client.get("/api/v1/vendors")
    assert r.status_code == 200, r.text
    names = [v["company_name"] for v in r.json()]
    ids = {v["company_name"]: v["operator_id"] for v in r.json()}
    # 件数も登録日時も同じ2社は id の昇順（UUID のバイト順＝16進文字列の順）。
    same_rank = sorted(["G0I1-x", "G0I1-y"], key=lambda n: uuid.UUID(ids[n]).hex)
    assert names == ["G5I5", "G3I0-old", "G3I0-new", "G3I2", "G0I0", *same_rank]


async def test_review_responses_no_longer_include_rating(
    client: AsyncClient, db_session: AsyncSession
):
    """T8: ★（rating）は alembic 0042 で撤去済み。評価・業者情報を返す全ての応答に rating が無く、
    verdict と件数（good_count / improve_count / review_count）を返す（0040〜0041 の互換期間中に
    「rating が残ること」を固定していたテストを反転）。OperatorOut（admin 一覧・業者本人）にも
    rating は無く、件数も足さない（設計判断の固定）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_t8_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "verdict_t8_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)
    body = await _post_review(client, user_token, {"transaction_id": txn_id, "verdict": "good"})
    assert "verdict" in body and "rating" not in body
    counts = {"good_count", "improve_count", "review_count"}

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(user_token))
    review_keys, operator_keys = r.json()["reviews"][0].keys(), r.json()["operator"].keys()
    assert "verdict" in review_keys and "rating" not in review_keys
    assert counts <= operator_keys and "rating" not in operator_keys
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert counts <= r.json().keys() and "rating" not in r.json()
    assert "verdict" in r.json()["reviews"][0] and "rating" not in r.json()["reviews"][0]
    r = await client.get("/api/v1/vendors")
    assert counts <= r.json()[0].keys() and "rating" not in r.json()[0]
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert counts <= r.json().keys() and "rating" not in r.json()

    case = await _create_case(client, user_token)
    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 20000}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"/api/v1/cases/{case['id']}/bids", headers=_auth(user_token))
    assert counts <= r.json()[0]["operator"].keys() and "rating" not in r.json()[0]["operator"]

    r = await client.patch(
        f"/api/v1/admin/reviews/{body['id']}/hide", json={"hidden": False}, headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert "verdict" in r.json() and "rating" not in r.json()
    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    admin_item = next(o for o in r.json()["items"] if o["id"] == op_id)
    assert "rating" not in admin_item and "good_count" not in admin_item
    r = await client.get("/api/v1/auth/me", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert "rating" not in r.json()["operator"]


async def test_review_comment_of_joined_phrases_passes_sanitizer_and_is_normalized(
    client: AsyncClient, db_session: AsyncSession
):
    """T9: 候補文（web/src/lib/review-verdict.ts）を3つ連結したコメントは無害化を通過し、
    全角「！」は NFKC で半角「!」に、改行は制御文字として除去される（既存の無害化仕様の固定。
    候補文を文末記号で完結させ、区切りは必要なときだけ半角スペースにする設計の前提）。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "verdict_t9_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "verdict_t9_op@example.com"
    )
    txn_id = await _completed_transaction(client, user_token, op_token)
    body = await _post_review(
        client,
        user_token,
        {
            "transaction_id": txn_id,
            "verdict": "good",
            "comment": "安心して取引できました！スムーズでした！\n対応が早くて助かりました！",
        },
    )
    assert body["comment"] == "安心して取引できました!スムーズでした!対応が早くて助かりました!"
    r = await client.get(f"/api/v1/vendors/{op_id}")
    assert r.json()["reviews"][0]["comment"] == body["comment"]


async def test_vendor_list_excludes_suspended(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    _, active_id = await _verified_operator(
        client, db_session, admin_token, "list_active@example.com", "掲載株式会社"
    )
    _, suspended_id = await _verified_operator(
        client, db_session, admin_token, "list_susp@example.com", "停止株式会社"
    )
    r = await client.patch(
        f"/api/v1/admin/operators/{suspended_id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/vendors")
    assert r.status_code == 200
    ids = {v["operator_id"] for v in r.json()}
    assert active_id in ids
    assert suspended_id not in ids


# ──────────────────────────── 通知配線: 減額申請（往路・復路） ────────────────────────────


async def _create_txn_for_notify_tests(
    client: AsyncClient, db_session: AsyncSession, admin_token: str
) -> tuple[str, str, str, str]:
    """減額/キャンセル通知テスト用に、成約直後の状態まで進める。

    戻り値: (user_token, op_token, case_id, txn_id)
    """
    user_token = await _signup_user(client, "notify_user@example.com")
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "notify_op@example.com", "通知テスト株式会社"
    )
    case = await _create_case(client, user_token)
    case_id = case["id"]
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids",
        json={"amount": 50000},
        headers=_auth(op_token),
    )
    bid = r.json()
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    txn_id = r.json()["id"]
    return user_token, op_token, case_id, txn_id


async def test_create_reduction_notifies_case_owner(
    client: AsyncClient, db_session: AsyncSession
):
    """ADD-2対応: 減額申請の送信が依頼者に通知される（往路）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, op_token, case_id, txn_id = await _create_txn_for_notify_tests(
        client, db_session, admin_token
    )

    with patch(
        "app.api.v1.endpoints.reductions.notify_dispatch.dispatch_reduction_requested",
        new_callable=AsyncMock,
    ) as dispatch_mock:
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/reduction",
            json={"requested_amount": 40000, "reason": "現地確認の結果、破損が見つかったため"},
            headers=_auth(op_token),
        )
    assert r.status_code == 201, r.text
    dispatch_mock.assert_called_once()
    call_args = dispatch_mock.call_args[0]
    assert call_args[2] == case_id  # case_id
    assert call_args[3] == 40000  # requested_amount


async def test_decide_reduction_notifies_operator(
    client: AsyncClient, db_session: AsyncSession
):
    """R3-vendor H2対応: 減額申請の承認/却下結果が業者に通知される（復路）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, op_token, case_id, txn_id = await _create_txn_for_notify_tests(
        client, db_session, admin_token
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 40000, "reason": "現地確認の結果、破損が見つかったため"},
        headers=_auth(op_token),
    )
    reduction_id = r.json()["id"]

    with patch(
        "app.api.v1.endpoints.reductions.notify_dispatch.dispatch_reduction_decided",
        new_callable=AsyncMock,
    ) as dispatch_mock:
        r = await client.patch(
            f"/api/v1/transactions/{txn_id}/reduction/{reduction_id}",
            json={"action": "approve"},
            headers=_auth(user_token),
        )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_called_once()
    call_args = dispatch_mock.call_args[0]
    assert call_args[2] == txn_id
    assert call_args[3] is True  # approved
    assert call_args[4] == 40000


# ──────────────────────────── 通知配線: 成約キャンセル ────────────────────────────


async def test_cancel_transaction_notifies_operator_when_user_cancels(
    client: AsyncClient, db_session: AsyncSession
):
    """ADD-1対応: 依頼者がキャンセルすると業者に通知される（空振り訪問の防止）。"""
    admin_token = await _make_admin(client, db_session)
    user_token, op_token, case_id, txn_id = await _create_txn_for_notify_tests(
        client, db_session, admin_token
    )

    with patch(
        "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_transaction_cancelled",
        new_callable=AsyncMock,
    ) as dispatch_mock:
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/cancel",
            json={"reason": "気が変わった"},
            headers=_auth(user_token),
        )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_called_once()
    call_args = dispatch_mock.call_args[0]
    assert call_args[2] == txn_id
    assert call_args[3] == "operator"  # 依頼者がキャンセルしたので業者へ通知


async def test_cancel_transaction_notifies_user_when_operator_cancels(
    client: AsyncClient, db_session: AsyncSession
):
    """ADD-1対応: 業者がキャンセルすると依頼者に通知される。"""
    admin_token = await _make_admin(client, db_session)
    user_token, op_token, case_id, txn_id = await _create_txn_for_notify_tests(
        client, db_session, admin_token
    )

    with patch(
        "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_transaction_cancelled",
        new_callable=AsyncMock,
    ) as dispatch_mock:
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/cancel",
            json={"reason": "対応できなくなった"},
            headers=_auth(op_token),
        )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_called_once()
    call_args = dispatch_mock.call_args[0]
    assert call_args[3] == "user"  # 業者がキャンセルしたので依頼者へ通知


# ──────────────────────────── admin: 案件・成約の横断閲覧（R3-operator H2） ────────────────────────────


async def test_admin_list_cases_and_transactions(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token, op_token, case_id, txn_id = await _create_txn_for_notify_tests(
        client, db_session, admin_token
    )

    r = await client.get("/api/v1/admin/cases", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    row = next(c for c in body["items"] if c["id"] == case_id)
    assert row["status"] == "closed"
    assert row["user_email"] == "notify_user@example.com"
    assert row["company_name"] == "通知テスト株式会社"
    assert row["amount"] == 50000

    r = await client.get("/api/v1/admin/transactions", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(t for t in body["items"] if t["id"] == txn_id)
    assert row["case_id"] == case_id
    assert row["user_email"] == "notify_user@example.com"
    assert row["company_name"] == "通知テスト株式会社"

    # q: 依頼者メールの部分一致で検索できる
    r = await client.get(
        "/api/v1/admin/cases", params={"q": "notify_user"}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert any(c["id"] == case_id for c in r.json()["items"])

    # q: 業者名の部分一致で成約検索できる
    r = await client.get(
        "/api/v1/admin/transactions",
        params={"q": "通知テスト"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert any(t["id"] == txn_id for t in r.json()["items"])

    # 非adminは403/401
    r = await client.get("/api/v1/admin/cases", headers=_auth(op_token))
    assert r.status_code in (401, 403)
    r = await client.get("/api/v1/admin/transactions")
    assert r.status_code in (401, 403)


async def test_admin_list_cases_respects_limit_and_offset(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "paging_user@example.com")
    for _ in range(3):
        await _create_case(client, user_token)

    r = await client.get(
        "/api/v1/admin/cases", params={"limit": 2, "offset": 0}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 3

    r = await client.get(
        "/api/v1/admin/cases", params={"limit": 200, "offset": 0}, headers=_auth(admin_token)
    )
    assert r.status_code == 200

    r = await client.get(
        "/api/v1/admin/cases", params={"limit": 201}, headers=_auth(admin_token)
    )
    assert r.status_code == 422  # 上限200超過


# ──────────────────────────── admin: 一覧系APIの limit/offset 後方互換（M2） ────────────────────────────


async def test_admin_invites_and_operators_list_accept_limit_offset_and_default_unchanged(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    await _invite_code(client, admin_token)
    await _invite_code(client, admin_token)

    # クエリ省略時は従来どおり動く（後方互換）
    r = await client.get("/api/v1/admin/invites", headers=_auth(admin_token))
    assert r.status_code == 200
    assert len(r.json()) >= 2

    r = await client.get(
        "/api/v1/admin/invites", params={"limit": 1, "offset": 0}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.get(
        "/api/v1/admin/invites", params={"limit": 501}, headers=_auth(admin_token)
    )
    assert r.status_code == 422  # 上限500超過

    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    assert r.status_code == 200


# ──────────────────────────── auth: admin昇格経路（ADD-3） ────────────────────────────


async def test_login_promotes_existing_user_to_admin_when_email_listed(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
):
    """ADD-3対応: ADMIN_EMAILS に後から追記されたメールでも、次回ログインで admin に昇格する。

    security review C-1対応: 昇格が発生した瞬間を WARNING ログに残すことも検証する
    （アラート基盤が admin 付与イベントを拾えることの確認）。
    """
    from app.config import get_settings

    email = "promote-me@example.com"
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "昇格太郎"},
    )
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "user"

    monkeypatch.setattr(get_settings(), "admin_emails_raw", email)

    with caplog.at_level(logging.WARNING):
        r = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "password123"}
        )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"

    user = await db_session.scalar(select(User).where(User.email == email))
    await db_session.refresh(user)
    assert user.role == "admin"
    assert any(
        "admin role granted" in rec.message
        and "via=login_promotion" in rec.message
        and email in rec.message
        for rec in caplog.records
    )


async def test_signup_grants_admin_and_logs_warning(
    client: AsyncClient, monkeypatch, caplog: pytest.LogCaptureFixture
):
    """security review C-1対応: サインアップ時の admin 付与も WARNING ログを残す。"""
    from app.config import get_settings

    email = "landgrab-admin@example.com"
    monkeypatch.setattr(get_settings(), "admin_emails_raw", email)

    with caplog.at_level(logging.WARNING):
        r = await client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "password123", "name": "初代管理者"},
        )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "admin"
    assert any(
        "admin role granted" in rec.message and "via=signup" in rec.message and email in rec.message
        for rec in caplog.records
    )


async def test_signup_does_not_grant_admin_when_admin_already_exists(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """security review N-1（Critical）対応: DB に role=admin のユーザーが既に
    1人でも存在する場合、ADMIN_EMAILS 掲載アドレスでの signup であっても
    role="user" になる（初回ブートストラップ限定。以降はログイン昇格のみ）。
    """
    from app.config import get_settings

    existing_admin = User(
        email="existing-admin@example.com",
        password_hash=hash_password("password123"),
        name="既存管理者",
        role="admin",
    )
    db_session.add(existing_admin)
    await db_session.commit()

    landgrab_email = "landgrab-second@example.com"
    monkeypatch.setattr(
        get_settings(), "admin_emails_raw", f"existing-admin@example.com,{landgrab_email}"
    )

    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": landgrab_email, "password": "password123", "name": "二人目"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "user"

    user = await db_session.scalar(select(User).where(User.email == landgrab_email))
    assert user.role == "user"

    # R3再レビュー Critical対応: 既存 admin が居る間はログイン時昇格も塞がれる
    # （従来はログイン昇格だけは無条件で許していたため、ADMIN_EMAILS に残った
    # アドレスで際限なく admin を量産できる経路になっていた）。
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": landgrab_email, "password": "password123"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "user"

    user = await db_session.scalar(select(User).where(User.email == landgrab_email))
    await db_session.refresh(user)
    assert user.role == "user"


async def test_login_promotion_blocked_fires_warning_alert_when_admin_exists(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """R3再レビュー Critical対応: 既存 admin が居るため昇格をブロックした場合、
    ブロックした事実自体を運営アラート（severity=warning）で通知する
    （ADMIN_EMAILS の設定不備・退職者アドレス残存の早期検知のため）。
    """
    import asyncio

    from app.config import get_settings

    existing_admin = User(
        email="existing-admin-2@example.com",
        password_hash=hash_password("password123"),
        name="既存管理者",
        role="admin",
    )
    db_session.add(existing_admin)
    await db_session.commit()

    landgrab_email = "landgrab-blocked@example.com"
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": landgrab_email, "password": "password123", "name": "二人目"},
    )
    assert r.status_code == 201, r.text

    monkeypatch.setattr(
        get_settings(), "admin_emails_raw", f"existing-admin-2@example.com,{landgrab_email}"
    )

    with patch(
        "app.api.v1.endpoints.auth.alerts.send_alert", new_callable=AsyncMock
    ) as alert_mock:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": landgrab_email, "password": "password123"},
        )
        await asyncio.sleep(0.05)  # fire_and_forget のタスクを消化
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "user"
    alert_mock.assert_awaited_once()
    assert alert_mock.await_args.kwargs["severity"] == "warning"


async def test_signup_admin_grant_fires_critical_alert(
    client: AsyncClient, monkeypatch
):
    """N-1対応: admin 付与は WARNING ログだけでなく alerts.send_alert
    （severity=critical）でも通知される（検知漏れ防止）。"""
    import asyncio

    from app.config import get_settings

    email = "alert-signup-admin@example.com"
    monkeypatch.setattr(get_settings(), "admin_emails_raw", email)

    with patch(
        "app.api.v1.endpoints.auth.alerts.send_alert", new_callable=AsyncMock
    ) as alert_mock:
        r = await client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "password123", "name": "初代管理者"},
        )
        await asyncio.sleep(0.05)  # fire_and_forget のタスクを消化
    assert r.status_code == 201, r.text
    alert_mock.assert_awaited_once()
    assert alert_mock.await_args.kwargs["severity"] == "critical"


async def test_promote_to_admin_if_listed_normalizes_email_case_and_whitespace(
    db_session: AsyncSession, monkeypatch
):
    """security review L-1対応: user.email 側の大文字小文字・前後空白の揺れを
    正規化してから ADMIN_EMAILS と照合すること（LINE経由で作成されたユーザーは
    email 正規化が保証されないため）。DB に有効な admin が居ないことが前提
    （R3再レビュー Critical対応で ``_promote_to_admin_if_listed`` は session 引数を
    取り、admin 不在条件を判定するようになった）。"""
    from app.api.v1.endpoints.auth import _promote_to_admin_if_listed
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_emails_raw", "promote-case@example.com")
    user = User(
        email="  Promote-Case@example.com  ",
        password_hash=hash_password("password123"),
        name="ケース太郎",
        role="user",
    )
    db_session.add(user)
    await db_session.commit()
    assert await _promote_to_admin_if_listed(db_session, user) is True
    assert user.role == "admin"
