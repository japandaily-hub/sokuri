"""admin の依頼者制御（停止・停止解除／一覧・検索）の統合テスト。

対応根拠: `.agent-state/audit/r3-verify-operator.md` ADD-2
（依頼者アカウントの利用停止手段が API・UI・DB のいずれにも存在しない）。

- 停止: suspended=true で依頼者の既存トークンが 403・ログイン拒否 / suspended=false で復帰 /
        admin 自身・role=admin のユーザーは 409 / 非 admin は 401/403 / 存在しない依頼者は 404 / 型不正は 422
- 一覧: q（メール/表示名の部分一致）・limit/offset・新しい順・case_count 集計
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
from app.db.models.case import Case
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


_USER_PASSWORD = "userpass123"


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> tuple[str, str]:
    """(access_token, admin_id) を返す。"""
    admin = User(
        email="admin_uctl@katadzoku.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_uctl@katadzoku.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"], str(admin.id)


async def _signup_user(client: AsyncClient, email: str, name: str = "依頼者太郎") -> tuple[str, str]:
    """(access_token, user_id) を返す。"""
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": _USER_PASSWORD, "name": name},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    return data["access_token"], data["user"]["id"]


# ──────────────────────────── 停止／停止解除 ────────────────────────────


async def test_suspend_and_unsuspend_user(client: AsyncClient, db_session: AsyncSession):
    admin_token, _ = await _make_admin(client, db_session)
    user_token, user_id = await _signup_user(client, "uctl_suspend1@example.com")

    # 停止前は自分のプロフィールを取得できる
    r = await client.get("/api/v1/users/me/profile", headers=_auth(user_token))
    assert r.status_code == 200, r.text

    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": True, "reason": "スパム出品の疑い"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_suspended"] is True
    assert r.json()["suspended_at"] is not None
    # QA未解決リスク対応: 停止操作時点の open/bidding 案件数を返す。
    assert r.json()["open_case_count"] == 0

    # 既存トークンは 403（依頼者向けAPI全般に効く。迂回路が無いことの確認）。
    # security review L-2対応: detail は機械可読な code を持つ dict になった。
    r = await client.get("/api/v1/users/me/profile", headers=_auth(user_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "account_suspended"
    assert "利用停止中" in r.json()["detail"]["message"]

    # ログインも拒否される
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "uctl_suspend1@example.com", "password": _USER_PASSWORD},
    )
    assert r.status_code == 403, r.text

    # 公開APIには影響しない（無認証で到達可能なエンドポイント）
    r = await client.get("/api/v1/vendors")
    assert r.status_code == 200, r.text

    # 停止解除で復帰
    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_suspended"] is False
    assert r.json()["suspended_at"] is None

    r = await client.get("/api/v1/users/me/profile", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "uctl_suspend1@example.com", "password": _USER_PASSWORD},
    )
    assert r.status_code == 200, r.text


async def test_suspend_requires_admin_and_existing_user_and_rejects_admin_targets(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token, admin_id = await _make_admin(client, db_session)
    user_token, user_id = await _signup_user(client, "uctl_suspend2@example.com")

    # 依頼者トークン（role=user）では admin ゲートを通過できない
    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": True},
        headers=_auth(user_token),
    )
    assert r.status_code in (401, 403), r.text

    # 未認証
    r = await client.patch(f"/api/v1/admin/users/{user_id}/suspend", json={"suspended": True})
    assert r.status_code in (401, 403), r.text

    # 存在しない依頼者
    r = await client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 404, r.text

    # 型不正
    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": "yes-please"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422, r.text

    # 必須フィールド欠落
    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422, r.text

    # admin 自身は停止不可
    r = await client.patch(
        f"/api/v1/admin/users/{admin_id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409, r.text

    # role=admin の別ユーザーも停止不可
    other_admin = User(
        email="other_admin_uctl@katadzoku.jp",
        password_hash=hash_password("adminpass123"),
        name="別の管理者",
        role="admin",
    )
    db_session.add(other_admin)
    await db_session.commit()
    await db_session.refresh(other_admin)
    r = await client.patch(
        f"/api/v1/admin/users/{other_admin.id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409, r.text


async def test_suspend_response_includes_open_case_count(
    client: AsyncClient, db_session: AsyncSession
):
    """QA未解決リスク対応: 停止時点の open/bidding 案件数を返し、closed 等は数えない。"""
    admin_token, _ = await _make_admin(client, db_session)
    _, user_id = await _signup_user(client, "uctl_opencase@example.com")

    db_session.add_all(
        [
            Case(user_id=uuid.UUID(user_id), purpose="片付け整理", prefecture="東京都", city="渋谷区", status="open"),
            Case(user_id=uuid.UUID(user_id), purpose="引っ越し", prefecture="東京都", city="渋谷区", status="bidding"),
            Case(user_id=uuid.UUID(user_id), purpose="遺品整理", prefecture="東京都", city="渋谷区", status="closed"),
        ]
    )
    await db_session.commit()

    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["open_case_count"] == 2

    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["open_case_count"] == 2


# ──────────────────────────── 一覧／検索 ────────────────────────────


async def test_list_users_search_and_case_count(client: AsyncClient, db_session: AsyncSession):
    admin_token, _ = await _make_admin(client, db_session)
    _, user1_id = await _signup_user(client, "uctl_list_alpha@example.com", name="山田太郎")
    _, user2_id = await _signup_user(client, "uctl_list_beta@example.com", name="鈴木花子")

    db_session.add_all(
        [
            Case(user_id=uuid.UUID(user1_id), purpose="片付け整理", prefecture="東京都", city="渋谷区"),
            Case(user_id=uuid.UUID(user1_id), purpose="引っ越し", prefecture="東京都", city="渋谷区"),
        ]
    )
    await db_session.commit()

    r = await client.get("/api/v1/admin/users?q=alpha", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["id"] == user1_id
    assert row["email"] == "uctl_list_alpha@example.com"
    assert row["case_count"] == 2
    assert row["is_suspended"] is False

    # 表示名の部分一致でも検索できる
    r = await client.get("/api/v1/admin/users?q=鈴木", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == user2_id
    assert r.json()["items"][0]["case_count"] == 0

    # limit/offset
    r = await client.get("/api/v1/admin/users?limit=1&offset=0", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 1
    assert r.json()["total"] >= 2

    # limit の上限超過は 422（既存の admin 一覧APIと同じ規約）
    r = await client.get("/api/v1/admin/users?limit=9999", headers=_auth(admin_token))
    assert r.status_code == 422, r.text


async def test_list_users_excludes_deleted_by_default_and_include_deleted_flag(
    client: AsyncClient, db_session: AsyncSession
):
    """QA M2対応: 退会済み（deleted_at 非null）ユーザーは既定で一覧から除外され、
    include_deleted=true で明示的に含められること。"""
    admin_token, _ = await _make_admin(client, db_session)
    _, active_id = await _signup_user(client, "uctl_active@example.com")
    _, deleted_id = await _signup_user(client, "uctl_deleted@example.com")
    deleted_user = await db_session.get(User, uuid.UUID(deleted_id))
    deleted_user.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.get("/api/v1/admin/users", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    ids = {item["id"] for item in r.json()["items"]}
    assert active_id in ids
    assert deleted_id not in ids

    r = await client.get(
        "/api/v1/admin/users?include_deleted=true", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    ids = {item["id"] for item in r.json()["items"]}
    assert active_id in ids
    assert deleted_id in ids


async def test_list_users_pagination_tie_breaker_no_duplicate_or_missing_rows(
    client: AsyncClient, db_session: AsyncSession
):
    """QA M3対応: created_at が同一値の行が複数あっても、id を tie-breaker に
    した決定的な順序により、ページングで重複・欠落が起きないこと。"""
    admin_token, _ = await _make_admin(client, db_session)
    same_ts = datetime.now(timezone.utc)
    ids: list[str] = []
    for i in range(3):
        _, uid = await _signup_user(client, f"uctl_tie_{i}@example.com")
        user = await db_session.get(User, uuid.UUID(uid))
        user.created_at = same_ts
        ids.append(uid)
    await db_session.commit()

    page1 = await client.get(
        "/api/v1/admin/users?q=uctl_tie_&limit=2&offset=0", headers=_auth(admin_token)
    )
    page2 = await client.get(
        "/api/v1/admin/users?q=uctl_tie_&limit=2&offset=2", headers=_auth(admin_token)
    )
    assert page1.status_code == 200 and page2.status_code == 200
    page1_ids = [item["id"] for item in page1.json()["items"]]
    page2_ids = [item["id"] for item in page2.json()["items"]]
    assert len(page1_ids) == 2
    assert len(page2_ids) == 1
    # 重複・欠落なく全件をちょうど1回ずつカバーする。
    assert sorted(page1_ids + page2_ids) == sorted(ids)
    # id 降順で一貫していること（同一 created_at の tie-breaker）。
    assert page1_ids == sorted(page1_ids, reverse=True)


async def test_list_users_search_by_id_exact_match(client: AsyncClient, db_session: AsyncSession):
    """QA H-2対応: web の CopyableId でコピーしたユーザーIDでの検索が0件にならないこと。"""
    admin_token, _ = await _make_admin(client, db_session)
    _, target_id = await _signup_user(client, "uctl_id_target@example.com")
    _, _other_id = await _signup_user(client, "uctl_id_other@example.com")

    r = await client.get(f"/api/v1/admin/users?q={target_id}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == target_id

    # UUIDとしてパースできない値はID条件を発行しない（メール/表示名の部分一致のみ）。
    r = await client.get(
        f"/api/v1/admin/users?q={uuid.uuid4()}", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0


async def test_list_users_search_escapes_ilike_wildcards(
    client: AsyncClient, db_session: AsyncSession
):
    """security review M-3対応: q に含まれる `_`/`%` はリテラル文字として扱われ、
    ワイルドカードとして意図せず他ユーザーにマッチしないこと。"""
    admin_token, _ = await _make_admin(client, db_session)
    await _signup_user(client, "uctl_escape_target@example.com")
    # "_" はエスケープ無しの ilike だと任意の1文字にマッチするため、
    # 対照実験として "_" の位置に別の文字を持つメールを用意する。
    await _signup_user(client, "uctlXescapeXtarget@example.com")

    r = await client.get(
        "/api/v1/admin/users?q=uctl_escape_target", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "uctl_escape_target@example.com"
    r = await client.get("/api/v1/admin/users?limit=9999", headers=_auth(admin_token))
    assert r.status_code == 422, r.text


# ──────────────────────────── admin 昇格／降格（R3再レビュー Critical対応） ────────────────────────────


async def test_promote_and_demote_user(client: AsyncClient, db_session: AsyncSession):
    """一般ユーザーを promote で admin にし、demote で元に戻せる正常系。"""
    admin_token, _ = await _make_admin(client, db_session)
    _, user_id = await _signup_user(client, "uctl_promote1@example.com")

    r = await client.post(
        f"/api/v1/admin/users/{user_id}/promote", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"id": user_id, "role": "admin"}

    user = await db_session.get(User, uuid.UUID(user_id))
    await db_session.refresh(user)
    assert user.role == "admin"

    r = await client.post(
        f"/api/v1/admin/users/{user_id}/demote", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"id": user_id, "role": "user"}

    await db_session.refresh(user)
    assert user.role == "user"


async def test_promote_requires_admin_target_must_be_plain_user(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token, admin_id = await _make_admin(client, db_session)
    user_token, user_id = await _signup_user(client, "uctl_promote2@example.com")

    # 非 admin では叩けない
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/promote", headers=_auth(user_token)
    )
    assert r.status_code in (401, 403), r.text

    # 未認証
    r = await client.post(f"/api/v1/admin/users/{user_id}/promote")
    assert r.status_code in (401, 403), r.text

    # 存在しないユーザー
    r = await client.post(
        f"/api/v1/admin/users/{uuid.uuid4()}/promote", headers=_auth(admin_token)
    )
    assert r.status_code == 404, r.text

    # 自己昇格は 409
    r = await client.post(
        f"/api/v1/admin/users/{admin_id}/promote", headers=_auth(admin_token)
    )
    assert r.status_code == 409, r.text

    # 停止中ユーザーは昇格不可
    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/promote", headers=_auth(admin_token)
    )
    assert r.status_code == 409, r.text
    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text

    # 既に admin なユーザーへの再昇格は 409
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/promote", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/promote", headers=_auth(admin_token)
    )
    assert r.status_code == 409, r.text


async def test_demote_rejects_self_and_last_remaining_admin(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token, admin_id = await _make_admin(client, db_session)

    # 自己降格は 409
    r = await client.post(
        f"/api/v1/admin/users/{admin_id}/demote", headers=_auth(admin_token)
    )
    assert r.status_code == 409, r.text

    # role=user のユーザーを降格しようとすると 409（対象外）
    _, user_id = await _signup_user(client, "uctl_demote1@example.com")
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/demote", headers=_auth(admin_token)
    )
    assert r.status_code == 409, r.text

    # 存在しないユーザー
    r = await client.post(
        f"/api/v1/admin/users/{uuid.uuid4()}/demote", headers=_auth(admin_token)
    )
    assert r.status_code == 404, r.text

    # 2人目の admin（元 user_id）を作ってから、admin_token（別 admin）が
    # user_id を降格 → 成功（demote 後も admin_id が残るため「最後の1人」ではない）。
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/promote", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/demote", headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"

    # 降格後の user_id は再びただの依頼者（role=user）に戻っている。
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "uctl_demote1@example.com", "password": _USER_PASSWORD},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "user"


async def test_has_other_active_admin_returns_false_for_sole_admin(
    client: AsyncClient, db_session: AsyncSession
):
    """demote の「最後の1人」ガード関数を直接検証する。

    ``POST /admin/users/{id}/demote`` はエンドポイント側の自己降格チェック
    （``user_id == admin.id``）が常に先に評価されるため、通常の HTTP 経由では
    「自分以外の全員が admin でなくなった状態で、他人が最後の admin を降格
    しようとする」状況を再現できない（呼び出し元は必ず現存する admin であり、
    その admin 自身が「対象を除く他の admin」としてカウントされてしまうため）。
    ガード関数 ``_has_other_active_admin`` 自体が「対象を除いて admin が
    1人も居ない」を正しく判定できることを、関数単体で直接検証する。
    """
    from app.api.v1.endpoints.admin import _has_other_active_admin

    _, admin_id = await _make_admin(client, db_session)
    assert (
        await _has_other_active_admin(db_session, exclude_user_id=uuid.UUID(admin_id))
        is False
    )

    other_admin = User(
        email="uctl_other_admin_guard@katadzoku.jp",
        password_hash=hash_password("adminpass123"),
        name="別の管理者",
        role="admin",
    )
    db_session.add(other_admin)
    await db_session.commit()
    await db_session.refresh(other_admin)
    assert (
        await _has_other_active_admin(db_session, exclude_user_id=uuid.UUID(admin_id))
        is True
    )
