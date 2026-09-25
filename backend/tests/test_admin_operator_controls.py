"""admin の業者制御（承認時の許可証ゲート／停止・停止解除）の統合テスト。

- 承認: pending かつ許可証未提出 → 409 / 許可証提出後 → 200 active /
        既に active の業者（2026-09-25 以前の招待コード即 active 登録の残存）は許可証なしでも
        verified_at 付与可（状態遷移なし）。2026-09-25 以降は招待コード登録も pending で始まる
- 停止: suspended=true で業者の既存トークンが 403・ログイン拒否 / suspended=false で復帰
        （停止前のトークンは解除後も 401 のまま・再ログインで復帰） /
        非 admin は 401/403 / 存在しない業者は 404 / 型不正は 422
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session


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


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
_OP_PASSWORD = "operatorpass1"


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="admin_controls@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_controls@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_pending_operator(client: AsyncClient, email: str) -> tuple[str, str]:
    """招待コードなしの業者登録（vendor_status=pending）。(token, operator_id) を返す。"""
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "company_name": "制御テスト業者",
            "email": email,
            "password": _OP_PASSWORD,
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["operator"]["vendor_status"] == "pending"
    return data["access_token"], data["operator"]["id"]


async def _signup_invited_operator(client: AsyncClient, admin_token: str, email: str) -> tuple[str, str]:
    """招待コードありの業者登録 → 許可証画像の提出 → 運営承認まで済ませた active 業者。

    2026-09-25 ユーザー決定で、招待コード経由でも signup 直後は pending（許可証提出＋運営承認で
    active）。(token, operator_id) を返す。
    """
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": "招待テスト業者",
            "email": email,
            "password": _OP_PASSWORD,
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["operator"]["vendor_status"] == "pending"
    op_token, op_id = data["access_token"], data["operator"]["id"]
    await _upload_license(client, op_token)
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["vendor_status"] == "active"
    return op_token, op_id


async def _legacy_active_operator_without_license(db_session: AsyncSession, email: str) -> str:
    """2026-09-25 以前に招待コードで即 active 登録された業者（許可証未提出・verified_at なし）。

    仕様変更後は API からは作れないが、本番には残存し得る（0043 で件数を監査）ため DB へ直接作る。
    operator_id を返す。
    """
    operator = Operator(
        company_name="旧招待登録業者",
        contact_email=email,
        password_hash=hash_password(_OP_PASSWORD),
        license_number="第123456789012号",
        vendor_status="active",
        verified_at=None,
    )
    db_session.add(operator)
    await db_session.commit()
    return str(operator.id)


async def _upload_license(client: AsyncClient, op_token: str) -> None:
    r = await client.post(
        "/api/v1/operator/license-image",
        files={"file": ("license.png", _PNG_BYTES, "image/png")},
        headers=_auth(op_token),
    )
    assert r.status_code == 200, r.text


# ──────────────────────────── 承認時の許可証ゲート ────────────────────────────


async def test_verify_pending_without_license_is_rejected(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    _, op_id = await _signup_pending_operator(client, "ctl_pending1@example.com")

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409, r.text
    assert "許可証" in r.json()["detail"]

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.vendor_status == "pending"
    assert operator.verified_at is None


async def test_verify_pending_with_license_succeeds(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _signup_pending_operator(client, "ctl_pending2@example.com")
    await _upload_license(client, op_token)

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["vendor_status"] == "active"
    assert r.json()["verified_at"] is not None


async def test_verify_already_active_without_license_is_allowed(client: AsyncClient, db_session: AsyncSession):
    """既に active の業者（旧仕様の招待コード即 active 登録の残存）は状態遷移なしなので、
    許可証なしでも verified_at を付与できる（既存の業者は変更しない方針。2026-09-25 ユーザー決定）。"""
    admin_token = await _make_admin(client, db_session)
    op_id = await _legacy_active_operator_without_license(db_session, "ctl_invited1@example.com")

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["vendor_status"] == "active"
    assert r.json()["verified_at"] is not None


async def test_unverify_never_requires_license(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    # 許可証未提出の active 業者でも承認取消（→ pending）は許可証を要求しない。
    op_id = await _legacy_active_operator_without_license(db_session, "ctl_invited2@example.com")

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["vendor_status"] == "pending"


# ──────────────────────────── 停止／停止解除 ────────────────────────────


async def test_suspend_and_unsuspend_operator(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _signup_invited_operator(client, admin_token, "ctl_suspend1@example.com")

    # 停止前は自社プロフィールを取得できる
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 200, r.text

    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_suspended"] is True
    assert r.json()["vendor_status"] == "active"  # 承認状態は変えない

    # 既存トークンは 403、再ログインも拒否
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/auth/operator/login",
        json={"email": "ctl_suspend1@example.com", "password": _OP_PASSWORD},
    )
    assert r.status_code in (401, 403), r.text

    # 停止解除で復帰（再ログインが必要）
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_suspended"] is False
    # 停止前に発行されたトークンは解除後も復活しない（sessions_revoked_at による失効。
    # 再ログイン後の流れは tests/test_suspension_session_revocation.py で固定）。
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 401, r.text
    # 失効ゲートの 401（再ログイン要求）であること（停止の 403 や別の 401 と区別する）。
    assert r.json()["detail"] == "Invalid credentials. Please log in again.", r.text
    assert r.headers.get("www-authenticate") == "Bearer"
    r = await client.post(
        "/api/v1/auth/operator/login",
        json={"email": "ctl_suspend1@example.com", "password": _OP_PASSWORD},
    )
    assert r.status_code == 200, r.text

    # 一覧にも反映される
    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    assert r.status_code == 200
    row = next(o for o in r.json()["items"] if o["id"] == op_id)
    assert row["is_suspended"] is False


async def test_suspend_requires_admin_and_existing_operator(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _signup_invited_operator(client, admin_token, "ctl_suspend2@example.com")

    # 業者トークン（typ=operator）では admin ゲートを通過できない
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/suspend",
        json={"suspended": True},
        headers=_auth(op_token),
    )
    assert r.status_code in (401, 403), r.text

    # 未認証
    r = await client.patch(f"/api/v1/admin/operators/{op_id}/suspend", json={"suspended": True})
    assert r.status_code in (401, 403), r.text

    # 存在しない業者
    r = await client.patch(
        f"/api/v1/admin/operators/{uuid.uuid4()}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 404, r.text

    # 型不正
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/suspend",
        json={"suspended": "yes-please"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422, r.text

    # 必須フィールド欠落
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/suspend",
        json={},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422, r.text


# ──────────────────────────── 公開プロフィールの承認バッジ ────────────────────────────


async def test_public_profile_is_approved_follows_vendor_status(client: AsyncClient, db_session: AsyncSession):
    admin_token = await _make_admin(client, db_session)
    _, pending_id = await _signup_pending_operator(client, "ctl_public_pending@example.com")
    _, active_id = await _signup_invited_operator(client, admin_token, "ctl_public_active@example.com")
    legacy_id = await _legacy_active_operator_without_license(db_session, "ctl_public_legacy@example.com")

    r = await client.get(f"/api/v1/vendors/{pending_id}")
    assert r.status_code == 200, r.text
    assert r.json()["is_approved"] is False

    r = await client.get(f"/api/v1/vendors/{active_id}")
    assert r.status_code == 200, r.text
    assert r.json()["is_approved"] is True
    assert r.json()["verified_at"] is not None

    # 旧仕様の招待コード即 active 登録は verified_at が付かないが、承認済みバッジの根拠は vendor_status
    r = await client.get(f"/api/v1/vendors/{legacy_id}")
    assert r.status_code == 200, r.text
    assert r.json()["is_approved"] is True
    assert r.json()["verified_at"] is None


# ──────────────────────────── 一覧の status/q 絞込・counts（H-1） ────────────────────────────


async def test_list_operators_status_q_total_counts(client: AsyncClient, db_session: AsyncSession):
    """H-1対応: GET /admin/operators の status/q絞込・total・counts・
    並び順（pending優先→created_at降順→id降順のtie-breaker）を検証する。

    是正前は limit/offset のみで status/total を返さず、web側のクライアント絞込が
    「現在ページの50件」しか見ていなかったため、2ページ目以降のpending業者が
    「審査待ち0件」に見える承認漏れが起きていた。
    """
    admin_token = await _make_admin(client, db_session)

    _, pending_id = await _signup_pending_operator(client, "ctl_list_pending@example.com")
    _, active_id = await _signup_invited_operator(client, admin_token, "ctl_list_active@example.com")

    r = await client.patch(
        f"/api/v1/admin/operators/{active_id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200

    # 全件（status未指定=all）: pending が先頭に来ること・counts は全件中の値。
    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    assert r.status_code == 200
    body = r.json()
    ids = [item["id"] for item in body["items"]]
    assert ids.index(pending_id) < ids.index(active_id)
    assert body["total"] == 2
    assert body["counts"] == {
        "all": 2,
        "pending": 1,
        "limited": 0,
        "active": 1,
        "rejected": 0,
        "suspended": 1,
        # r10 O-M4: pending かつ許可証画像あり＝いま承認できる件数。
        # 事前申込経由の pending 業者は許可証未提出のため 0。
        "pending_with_license": 0,
    }

    # status=pending
    r = await client.get(
        "/api/v1/admin/operators", params={"status": "pending"}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    body = r.json()
    returned_ids = {item["id"] for item in body["items"]}
    assert pending_id in returned_ids
    assert active_id not in returned_ids
    assert all(item["vendor_status"] == "pending" for item in body["items"])
    assert body["counts"]["pending"] == 1  # 絞込に関わらずバッジ用の値は全件中のまま
    assert body["counts"]["all"] == 2

    # status=suspended（is_suspended=True で絞込。vendor_statusとは独立の軸）
    r = await client.get(
        "/api/v1/admin/operators", params={"status": "suspended"}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    body = r.json()
    returned_ids = {item["id"] for item in body["items"]}
    assert active_id in returned_ids
    assert pending_id not in returned_ids
    assert all(item["is_suspended"] is True for item in body["items"])

    # q: 会社名/メール/許可番号の部分一致（メールで絞る）
    r = await client.get(
        "/api/v1/admin/operators",
        params={"q": "ctl_list_pending"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == pending_id

    # 不正なstatus値（綴り違い）は422（空一覧で無言に失敗しない）
    r = await client.get(
        "/api/v1/admin/operators", params={"status": "pendingg"}, headers=_auth(admin_token)
    )
    assert r.status_code == 422

    # limit上限（200）超過は422
    r = await client.get(
        "/api/v1/admin/operators", params={"limit": 201}, headers=_auth(admin_token)
    )
    assert r.status_code == 422



# ──────────────────────────── 退会済み業者の除外・保護（r8-review 未解決5） ────────────────────────────


async def test_admin_operators_excludes_deleted_by_default(
    client: AsyncClient, db_session: AsyncSession
):
    """退会済み（deleted_at 非null）業者は既定で一覧・countsから除外され、
    include_deleted=true で明示的に含められる。verify/suspend は409。"""
    admin_token = await _make_admin(client, db_session)

    _, active_id = await _signup_invited_operator(client, admin_token, "ctl_del_active@example.com")
    _, deleted_id = await _signup_invited_operator(client, admin_token, "ctl_del_deleted@example.com")

    deleted_operator = await db_session.get(Operator, uuid.UUID(deleted_id))
    deleted_operator.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    # 既定（include_deleted省略）: 退会済みは一覧・countsから消える。
    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {item["id"] for item in body["items"]}
    assert active_id in ids
    assert deleted_id not in ids
    assert body["total"] == 1
    assert body["counts"]["all"] == 1

    # include_deleted=true: 含まれる。
    r = await client.get(
        "/api/v1/admin/operators", params={"include_deleted": True}, headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {item["id"] for item in body["items"]}
    assert deleted_id in ids
    assert body["total"] == 2
    assert body["counts"]["all"] == 2

    # 退会済み業者への verify / suspend は409（状態不整合の防止）。
    r = await client.patch(
        f"/api/v1/admin/operators/{deleted_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409, r.text

    r = await client.patch(
        f"/api/v1/admin/operators/{deleted_id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409, r.text


# ──────────────────────────── admin による強制削除（業者アカウント一覧「削除」ボタン対応） ────────────────────────────


async def test_admin_delete_operator_anonymizes_and_revokes_access(
    client: AsyncClient, db_session: AsyncSession
):
    """admin が業者を削除すると、本人退会（DELETE /operator/me）と同じ匿名化が
    パスワード再認証なしで行われ、以後ログイン・旧トークンいずれも失効する。"""
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _signup_invited_operator(client, admin_token, "ctl_admindel1@example.com")

    r = await client.delete(
        f"/api/v1/admin/operators/{op_id}",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == op_id
    assert r.json()["detail"]

    operator = await db_session.get(Operator, uuid.UUID(op_id))
    await db_session.refresh(operator)
    assert operator.contact_email == f"deleted-{operator.id}@deleted.katazuke.internal"
    assert operator.password_hash is None
    assert operator.deleted_at is not None

    # 旧トークンは失効し、同一emailでの再ログインもできない。
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code in (401, 403), r.text
    r = await client.post(
        "/api/v1/auth/operator/login",
        json={"email": "ctl_admindel1@example.com", "password": _OP_PASSWORD},
    )
    assert r.status_code in (401, 403), r.text

    # 一覧に既定では出てこず、include_deleted=true で退会済みとして現れる。
    r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert all(item["id"] != op_id for item in r.json()["items"])
    r = await client.get(
        "/api/v1/admin/operators",
        params={"include_deleted": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert any(item["id"] == op_id for item in r.json()["items"])


async def test_admin_delete_operator_requires_admin_and_existing_and_rejects_double_delete(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _signup_invited_operator(client, admin_token, "ctl_admindel2@example.com")

    # 業者トークン（typ=operator）では admin ゲートを通過できない
    r = await client.delete(f"/api/v1/admin/operators/{op_id}", headers=_auth(op_token))
    assert r.status_code in (401, 403), r.text

    # 未認証
    r = await client.delete(f"/api/v1/admin/operators/{op_id}")
    assert r.status_code in (401, 403), r.text

    # 存在しない業者
    r = await client.delete(
        f"/api/v1/admin/operators/{uuid.uuid4()}", headers=_auth(admin_token)
    )
    assert r.status_code == 404, r.text

    # 削除済みの業者を再度削除しようとすると 409（状態不整合の防止・verify/suspendと同型）
    r = await client.delete(f"/api/v1/admin/operators/{op_id}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    r = await client.delete(f"/api/v1/admin/operators/{op_id}", headers=_auth(admin_token))
    assert r.status_code == 409, r.text
