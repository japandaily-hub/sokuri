"""運営による停止に伴うセッション失効（sessions_revoked_at）の回帰テスト。

背景: 運営がアカウント（依頼者・業者）を停止すると停止中は 403 になるが、停止を解除すると、
停止より前に発行されたアクセストークン（有効期限 7 日）が再び使えるようになっていた。
停止時刻を ``users`` / ``operators`` の ``sessions_revoked_at`` に記録し（実際の解除時は解除時刻へ
進める。NULL には戻さない）、iat がそれ以前のトークンを deps.py の失効ゲートで 401 にする
（解除後は再ログインを求める）。

本ファイルで固定する契約:

- 停止（suspended=true）で sessions_revoked_at が現在時刻になる（依頼者は suspended_at と
  同一時刻）。停止中の再送と、実際の解除（停止→解除）では境界が現在時刻へ進む（停止中は
  ログインできず新しいトークンが無いため、失効するのは停止前と停止に競合したログインの
  トークンだけ。デプロイ切替中に旧コードで停止され境界の無いアカウントも解除時に塞がる）。
  停止していないアカウントへの解除要求（解除→解除・一度も停止していない）では変わらない。
  409 で拒否された停止操作（admin 対象・退会済み業者）では設定されない。
- 停止中は従来どおり 403 ``account_suspended``（web の停止案内を維持するため、失効の 401
  より優先する）。
- 解除後、停止前に発行されたトークンは依頼者・業者を解決する全経路で 401（``_CRED_EXC``）:
  get_current_user / get_current_actor / get_case_viewer_actor / get_current_operator /
  line_exchange の Bearer 経路（有効な再認証トークンを添えても新トークンを発行せず、LINE
  連携も書き込まない）。任意認証（get_optional_user / get_optional_operator）は従来の方針
  どおり None（トークン無し扱い）。
- 解除後に改めてログインしたトークンは同じ全経路で通る（正常系を塞いでいないことの対照）。
- 判定の境界（単体）: iat が境界と同一秒以前なら失効・1 秒後なら有効・境界 NULL は失効なし・
  SQLite の tz-naive 値は UTC として扱う・iat 欠落は失効（fail closed）・停止中は本ゲートでは
  判定しない（403 優先）・退会は常に失効・パスワード変更ゲートの同一秒許容は従来どおり・
  トークンを受け取らない閲覧ゲートは境界を見ない。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。ヘルパーは
tests/test_deleted_operator_token_revocation.py と同様にこのファイル内へ自己完結で複製し、
LINE API も同じく ``httpx.AsyncClient.get`` を URL で出し分けてモックする。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Literal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    assert_operator_case_access,
    assert_operator_not_suspended,
    assert_user_not_suspended,
    get_optional_operator,
    get_optional_user,
    is_operator_token_revoked,
    is_user_token_revoked,
)
from app.api.v1.endpoints import auth as auth_endpoint
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import create_access_token, create_reauth_token, hash_password
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session

_TEST_LINE_CLIENT_ID = "test-line-channel-id"
_ADMIN_EMAIL = "sessions_admin@katadzuke.jp"
_ADMIN_PASSWORD = "adminpass123"
_USER_PASSWORD = "userpass123"
_OP_PASSWORD = "operatorpass1"
# deps._CRED_EXC の応答契約（web はこの status・ヘッダでサインアウトし再ログインへ誘導する）。
_CRED_DETAIL = "Invalid credentials. Please log in again."
_LINE_USER_ID_FOR_USER = "U0f1e2d3c4b5a69788796a5b4c3d2e1f0"
_LINE_USER_ID_FOR_OPERATOR = "U1f2e3d4c5b6a7980a9b8c7d6e5f4a3b2"

# 依頼者トークンで叩く閲覧系（それぞれ別の認証依存を通る）。
_USER_PATHS: tuple[tuple[str, str], ...] = (
    ("/api/v1/users/me/profile", "get_current_user"),
    ("/api/v1/auth/me", "get_current_actor"),
    ("/api/v1/cases", "get_case_viewer_actor"),
)
# 業者トークンで叩く閲覧系（同上）。
_OPERATOR_PATHS: tuple[tuple[str, str], ...] = (
    ("/api/v1/operator/profile", "get_current_operator"),
    ("/api/v1/auth/me", "get_current_actor"),
    ("/api/v1/cases", "get_case_viewer_actor"),
)


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


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    """任意認証の依存関数を直接呼ぶための資格情報。"""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _as_utc(moment: datetime) -> datetime:
    """SQLite から読み戻した tz なしの値を aware に揃える（保存値は UTC）。"""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _mock_line_get(line_user_id: str) -> AsyncMock:
    """LINE Verify API / Profile API を URL で出し分けるモック。"""
    verify_res = httpx.Response(
        200, json={"client_id": _TEST_LINE_CLIENT_ID, "expires_in": 3600, "scope": "profile"}
    )
    profile_res = httpx.Response(200, json={"userId": line_user_id, "displayName": "テスト"})

    async def _side_effect(url, *args, **kwargs):
        if url == auth_endpoint._LINE_VERIFY_ENDPOINT:
            return verify_res
        if url == auth_endpoint._LINE_PROFILE_ENDPOINT:
            return profile_res
        raise AssertionError(f"未想定のURLへのリクエスト: {url}")

    return AsyncMock(side_effect=_side_effect)


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email=_ADMIN_EMAIL,
        password_hash=hash_password(_ADMIN_PASSWORD),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str) -> tuple[str, uuid.UUID]:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": _USER_PASSWORD, "name": "依頼者太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"], uuid.UUID(r.json()["user"]["id"])


async def _verified_operator(
    client: AsyncClient, admin_token: str, email: str
) -> tuple[str, uuid.UUID]:
    """招待コード登録（pending）→ 許可証提出 → 運営承認まで済ませた業者の (token, operator_id)。"""
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": r.json()["code"],
            "company_name": "失効テスト片付け株式会社",
            "email": email,
            "password": _OP_PASSWORD,
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    # 招待コード経由でも signup 直後は pending（2026-09-25 ユーザー決定）。
    # 許可証画像の提出 → 運営承認を経て active にする（承認は許可証未提出だと 409）。
    r = await client.post(
        "/api/v1/operator/license-image",
        files={"file": ("license.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 256, "image/png")},
        headers=_auth(data["access_token"]),
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"/api/v1/admin/operators/{data['operator']['id']}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    return data["access_token"], uuid.UUID(data["operator"]["id"])


async def _set_suspended(
    client: AsyncClient,
    admin_token: str,
    kind: Literal["users", "operators"],
    account_id: uuid.UUID,
    suspended: bool,
) -> httpx.Response:
    body: dict = {"suspended": suspended}
    if suspended and kind == "users":
        body["reason"] = "調査のため一時停止"
    return await client.patch(
        f"/api/v1/admin/{kind}/{account_id}/suspend", json=body, headers=_auth(admin_token)
    )


def _assert_revoked(r: httpx.Response, label: str) -> None:
    """失効ゲートの 401（_CRED_EXC）であること（再認証要求など別の 401 と区別する）。"""
    assert r.status_code == 401, f"{label}: {r.status_code} {r.text}"
    assert r.json()["detail"] == _CRED_DETAIL, f"{label}: {r.text}"
    assert r.headers.get("www-authenticate") == "Bearer", label


def _assert_suspended(r: httpx.Response, label: str) -> None:
    """停止中の 403 account_suspended であること（web の停止案内の契約）。"""
    assert r.status_code == 403, f"{label}: {r.status_code} {r.text}"
    assert r.json()["detail"]["code"] == "account_suspended", f"{label}: {r.text}"


async def _simulate_time_passed_since_suspension(
    db_session: AsyncSession, account: User | Operator
) -> None:
    """停止から時間が経った状態を再現する（失効境界を 5 分前へずらす）。

    実運用では停止から解除・再ログインまでに時間が経つ。テストでは停止・解除・再ログインが
    同じ秒に収まりやすく、秒精度の iat では「停止後の発行」と証明できないため失効側に倒れる
    （仕様。test_boundary_is_inclusive_by_second 参照）。
    """
    account.sessions_revoked_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.commit()


# ──────────────── 停止操作が失効境界を記録すること ────────────────


async def test_user_suspend_sets_boundary_and_unsuspend_advances_it(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    _, user_id = await _signup_user(client, "boundary_user@example.com")
    user = await db_session.get(User, user_id)
    assert user is not None
    assert user.sessions_revoked_at is None, "一度も停止していない依頼者に境界があってはならない"

    before = datetime.now(timezone.utc)
    r = await _set_suspended(client, admin_token, "users", user_id, True)
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    await db_session.refresh(user)
    first_boundary = _as_utc(user.sessions_revoked_at)
    assert before <= first_boundary <= after
    assert first_boundary == _as_utc(user.suspended_at), "停止時刻と同一時刻にする"

    # 停止中の再送（停止→停止）では境界が進む（戻らない）。
    r = await _set_suspended(client, admin_token, "users", user_id, True)
    assert r.status_code == 200, r.text
    await db_session.refresh(user)
    second_boundary = _as_utc(user.sessions_revoked_at)
    assert second_boundary >= first_boundary

    # 実際の解除（停止→解除）では解除時刻へ進む（NULL には戻らない。戻すと停止前のトークンが復活する）。
    before_unsuspend = datetime.now(timezone.utc)
    r = await _set_suspended(client, admin_token, "users", user_id, False)
    after_unsuspend = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    await db_session.refresh(user)
    assert user.is_suspended is False
    assert user.suspended_at is None
    unsuspend_boundary = _as_utc(user.sessions_revoked_at)
    assert unsuspend_boundary >= second_boundary
    assert before_unsuspend <= unsuspend_boundary <= after_unsuspend

    # 解除済みへの再送（解除→解除）では変更しない。
    r = await _set_suspended(client, admin_token, "users", user_id, False)
    assert r.status_code == 200, r.text
    await db_session.refresh(user)
    assert _as_utc(user.sessions_revoked_at) == unsuspend_boundary

    # 一度も停止していない依頼者への解除要求でも境界は作らない（誤操作で利用者を締め出さない）。
    _, other_user_id = await _signup_user(client, "never_suspended_user@example.com")
    r = await _set_suspended(client, admin_token, "users", other_user_id, False)
    assert r.status_code == 200, r.text
    other_user = await db_session.get(User, other_user_id)
    assert other_user is not None
    assert other_user.sessions_revoked_at is None


async def test_operator_suspend_sets_boundary_and_unsuspend_advances_it(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    _, op_id = await _verified_operator(client, admin_token, "boundary_op@example.com")
    operator = await db_session.get(Operator, op_id)
    assert operator is not None
    assert operator.sessions_revoked_at is None

    before = datetime.now(timezone.utc)
    r = await _set_suspended(client, admin_token, "operators", op_id, True)
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    await db_session.refresh(operator)
    first_boundary = _as_utc(operator.sessions_revoked_at)
    assert before <= first_boundary <= after

    r = await _set_suspended(client, admin_token, "operators", op_id, True)
    assert r.status_code == 200, r.text
    await db_session.refresh(operator)
    second_boundary = _as_utc(operator.sessions_revoked_at)
    assert second_boundary >= first_boundary

    # 実際の解除（停止→解除）では解除時刻へ進む（NULL には戻らない）。
    before_unsuspend = datetime.now(timezone.utc)
    r = await _set_suspended(client, admin_token, "operators", op_id, False)
    after_unsuspend = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    await db_session.refresh(operator)
    assert operator.is_suspended is False
    assert operator.vendor_status == "active", "承認状態は変えない（従来どおり）"
    unsuspend_boundary = _as_utc(operator.sessions_revoked_at)
    assert unsuspend_boundary >= second_boundary
    assert before_unsuspend <= unsuspend_boundary <= after_unsuspend

    # 解除済みへの再送（解除→解除）では変更しない。
    r = await _set_suspended(client, admin_token, "operators", op_id, False)
    assert r.status_code == 200, r.text
    await db_session.refresh(operator)
    assert _as_utc(operator.sessions_revoked_at) == unsuspend_boundary


async def test_rejected_suspend_does_not_set_boundary(
    client: AsyncClient, db_session: AsyncSession
):
    """409 で拒否された停止操作（role=admin の依頼者・退会済み業者）では境界を設定しない。"""
    admin_token = await _make_admin(client, db_session)
    other_admin = User(
        email="sessions_other_admin@katadzuke.jp",
        password_hash=hash_password(_ADMIN_PASSWORD),
        name="別の管理者",
        role="admin",
    )
    deleted_operator = Operator(
        company_name="退会済み業者",
        contact_email="deleted-sessions@deleted.katazuke.internal",
        vendor_status="active",
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add_all([other_admin, deleted_operator])
    await db_session.commit()

    r = await _set_suspended(client, admin_token, "users", other_admin.id, True)
    assert r.status_code == 409, r.text
    r = await _set_suspended(client, admin_token, "operators", deleted_operator.id, True)
    assert r.status_code == 409, r.text

    await db_session.refresh(other_admin)
    await db_session.refresh(deleted_operator)
    assert other_admin.sessions_revoked_at is None
    assert deleted_operator.sessions_revoked_at is None


# ──────────────── 解除後の停止前トークンは全経路で 401 ────────────────


async def test_user_pre_suspension_token_is_revoked_after_unsuspend_on_every_path(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    old_token, user_id = await _signup_user(client, "revoked_user@example.com")

    # 前提: 停止前は同じトークンで全経路が通る（401 の原因が経路・権限の誤りでないことの担保）。
    for path, dep in _USER_PATHS:
        r = await client.get(path, headers=_auth(old_token))
        assert r.status_code == 200, f"{path}（{dep}・停止前）: {r.text}"

    r = await _set_suspended(client, admin_token, "users", user_id, True)
    assert r.status_code == 200, r.text
    # 停止中は従来どおり 403 account_suspended（失効の 401 にしない）。
    for path, dep in _USER_PATHS:
        _assert_suspended(await client.get(path, headers=_auth(old_token)), f"{path}（{dep}・停止中）")

    r = await _set_suspended(client, admin_token, "users", user_id, False)
    assert r.status_code == 200, r.text
    # 解除後: 停止前に発行されたトークンは復活しない（再ログインを求める 401）。
    for path, dep in _USER_PATHS:
        _assert_revoked(await client.get(path, headers=_auth(old_token)), f"{path}（{dep}・解除後）")

    # line_exchange（Bearer付き連携経路）: 有効な再認証トークンを添えても 401 で止まり、
    # 新しいトークンの発行（＝再ログイン要求の迂回）も LINE 連携の書き込みも起きない。
    with patch.object(
        httpx.AsyncClient, "get", new=_mock_line_get(_LINE_USER_ID_FOR_USER)
    ):
        r = await client.post(
            "/api/v1/auth/line/exchange",
            json={
                "line_access_token": "dummy-line-token",
                "reauth_token": create_reauth_token(user_id, "user"),
            },
            headers=_auth(old_token),
        )
    _assert_revoked(r, "POST /api/v1/auth/line/exchange（解除後）")
    assert "access_token" not in r.json()
    user = await db_session.get(User, user_id)
    assert user is not None
    await db_session.refresh(user)
    assert user.line_user_id is None

    # 任意認証（POST /contact の送信者解決）は 401 にせず、トークン無し扱い。
    assert await get_optional_user(_bearer(old_token), db_session) is None


async def test_operator_pre_suspension_token_is_revoked_after_unsuspend_on_every_path(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    old_token, op_id = await _verified_operator(client, admin_token, "revoked_op@example.com")

    for path, dep in _OPERATOR_PATHS:
        r = await client.get(path, headers=_auth(old_token))
        assert r.status_code == 200, f"{path}（{dep}・停止前）: {r.text}"

    r = await _set_suspended(client, admin_token, "operators", op_id, True)
    assert r.status_code == 200, r.text
    for path, dep in _OPERATOR_PATHS:
        _assert_suspended(await client.get(path, headers=_auth(old_token)), f"{path}（{dep}・停止中）")
    # 任意認証は停止中は業者を返し、配信側（GET /files）の停止ゲートで 403 にさせる（従来どおり）。
    suspended_view = await get_optional_operator(_bearer(old_token), db_session)
    assert suspended_view is not None and suspended_view.id == op_id

    r = await _set_suspended(client, admin_token, "operators", op_id, False)
    assert r.status_code == 200, r.text
    for path, dep in _OPERATOR_PATHS:
        _assert_revoked(await client.get(path, headers=_auth(old_token)), f"{path}（{dep}・解除後）")

    with patch.object(
        httpx.AsyncClient, "get", new=_mock_line_get(_LINE_USER_ID_FOR_OPERATOR)
    ):
        r = await client.post(
            "/api/v1/auth/line/exchange",
            json={
                "line_access_token": "dummy-line-token",
                "reauth_token": create_reauth_token(op_id, "operator"),
            },
            headers=_auth(old_token),
        )
    _assert_revoked(r, "POST /api/v1/auth/line/exchange（解除後）")
    assert "access_token" not in r.json()
    operator = await db_session.get(Operator, op_id)
    assert operator is not None
    await db_session.refresh(operator)
    assert operator.line_user_id is None

    # 任意認証（GET /files の業者解決）は 401 にせず、トークン無し扱い。
    assert await get_optional_operator(_bearer(old_token), db_session) is None


# ──────────────── 解除後の再ログインは通る（正常系の対照） ────────────────


async def test_user_relogin_after_unsuspend_restores_access(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    email = "relogin_user@example.com"
    _, user_id = await _signup_user(client, email)
    # 停止より前に発行されたトークン（停止前から使っていた端末のセッション）。
    old_token = create_access_token(
        user_id, "user", "user", issued_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )

    assert (await _set_suspended(client, admin_token, "users", user_id, True)).status_code == 200
    assert (await _set_suspended(client, admin_token, "users", user_id, False)).status_code == 200
    user = await db_session.get(User, user_id)
    assert user is not None
    await _simulate_time_passed_since_suspension(db_session, user)

    r = await client.post("/api/v1/auth/login", json={"email": email, "password": _USER_PASSWORD})
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]

    for path, dep in _USER_PATHS:
        r = await client.get(path, headers=_auth(new_token))
        assert r.status_code == 200, f"{path}（{dep}・再ログイン後）: {r.text}"
        _assert_revoked(await client.get(path, headers=_auth(old_token)), f"{path}（{dep}・旧トークン）")
    resolved = await get_optional_user(_bearer(new_token), db_session)
    assert resolved is not None and resolved.id == user_id


async def test_operator_relogin_after_unsuspend_restores_access(
    client: AsyncClient, db_session: AsyncSession
):
    admin_token = await _make_admin(client, db_session)
    email = "relogin_op@example.com"
    _, op_id = await _verified_operator(client, admin_token, email)
    old_token = create_access_token(
        op_id, "operator", "operator", issued_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )

    assert (await _set_suspended(client, admin_token, "operators", op_id, True)).status_code == 200
    assert (await _set_suspended(client, admin_token, "operators", op_id, False)).status_code == 200
    operator = await db_session.get(Operator, op_id)
    assert operator is not None
    await _simulate_time_passed_since_suspension(db_session, operator)

    r = await client.post(
        "/api/v1/auth/operator/login", json={"email": email, "password": _OP_PASSWORD}
    )
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]

    for path, dep in _OPERATOR_PATHS:
        r = await client.get(path, headers=_auth(new_token))
        assert r.status_code == 200, f"{path}（{dep}・再ログイン後）: {r.text}"
        _assert_revoked(await client.get(path, headers=_auth(old_token)), f"{path}（{dep}・旧トークン）")
    resolved = await get_optional_operator(_bearer(new_token), db_session)
    assert resolved is not None and resolved.id == op_id

    # 再ログイン後のトークンでは LINE 連携（Bearer経路）も従来どおり通る。
    with patch.object(
        httpx.AsyncClient, "get", new=_mock_line_get(_LINE_USER_ID_FOR_OPERATOR)
    ):
        r = await client.post(
            "/api/v1/auth/line/exchange",
            json={
                "line_access_token": "dummy-line-token",
                "reauth_token": create_reauth_token(op_id, "operator"),
            },
            headers=_auth(new_token),
        )
    assert r.status_code == 200, r.text
    await db_session.refresh(operator)
    assert operator.line_user_id == _LINE_USER_ID_FOR_OPERATOR


# ──────────────── 判定の境界（単体） ────────────────

# 秒未満（.9 秒）を含む境界。iat は秒精度のため、同一秒内の前後は区別できない。
_BOUNDARY = datetime(2026, 9, 25, 3, 0, 0, 900000, tzinfo=timezone.utc)
_BOUNDARY_SEC = int(_BOUNDARY.timestamp())


def _user(**overrides: object) -> User:
    fields: dict = {"email": "unit@example.com", "is_suspended": False}
    fields.update(overrides)
    return User(**fields)


def _operator(**overrides: object) -> Operator:
    fields: dict = {
        "company_name": "単体テスト業者",
        "contact_email": "unit-op@example.com",
        "vendor_status": "active",
        "is_suspended": False,
    }
    fields.update(overrides)
    return Operator(**fields)


@pytest.mark.parametrize("naive", [False, True], ids=["aware", "sqlite_naive"])
@pytest.mark.parametrize(
    ("iat_offset", "revoked"),
    [(-3600, True), (-1, True), (0, True), (1, False), (3600, False)],
    ids=["1h_before", "1s_before", "same_second", "1s_after", "1h_after"],
)
def test_boundary_is_inclusive_by_second(iat_offset: int, revoked: bool, naive: bool):
    """iat が境界と同一秒以前なら失効、1 秒以上後なら有効（依頼者・業者で同一）。

    同一秒を失効側に倒すのは、停止中は新しいトークンが発行されないため（deps.py の
    ``_is_session_revoked_by_suspension`` 参照）。SQLite が返す tz-naive 値は UTC として扱う
    （ローカルタイム解釈だと JST 環境で 9 時間ずれて判定が反転する）。
    """
    boundary = _BOUNDARY.replace(tzinfo=None) if naive else _BOUNDARY
    payload = {"iat": _BOUNDARY_SEC + iat_offset}
    assert is_user_token_revoked(_user(sessions_revoked_at=boundary), payload) is revoked
    assert is_operator_token_revoked(_operator(sessions_revoked_at=boundary), payload) is revoked


def test_no_boundary_never_revokes_and_missing_iat_fails_closed():
    """境界 NULL（一度も停止されていない）は失効させない。境界があるのに iat が無い
    トークンは発行時刻を示せないため失効扱い（正規のトークンは必ず iat を持つ）。"""
    assert is_user_token_revoked(_user(sessions_revoked_at=None), {"iat": 0}) is False
    assert is_user_token_revoked(_user(sessions_revoked_at=None), {}) is False
    assert is_operator_token_revoked(_operator(sessions_revoked_at=None), {"iat": 0}) is False
    assert is_operator_token_revoked(_operator(sessions_revoked_at=None), {}) is False

    assert is_user_token_revoked(_user(sessions_revoked_at=_BOUNDARY), {}) is True
    assert is_operator_token_revoked(_operator(sessions_revoked_at=_BOUNDARY), {}) is True


def test_suspended_account_defers_to_403_and_deleted_is_always_revoked():
    """停止中は本ゲートでは失効扱いにせず、停止ゲートの 403 account_suspended に任せる。
    退会（論理削除）は境界に関係なく常に失効（401）。"""
    old_payload = {"iat": _BOUNDARY_SEC - 60}
    suspended_user = _user(is_suspended=True, sessions_revoked_at=_BOUNDARY)
    suspended_operator = _operator(is_suspended=True, sessions_revoked_at=_BOUNDARY)
    assert is_user_token_revoked(suspended_user, old_payload) is False
    assert is_operator_token_revoked(suspended_operator, old_payload) is False
    for gate, account in (
        (assert_user_not_suspended, suspended_user),
        (assert_operator_not_suspended, suspended_operator),
    ):
        with pytest.raises(HTTPException) as exc_info:
            gate(account)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "account_suspended"

    fresh_payload = {"iat": int(datetime.now(timezone.utc).timestamp())}
    deleted_at = datetime.now(timezone.utc)
    assert is_user_token_revoked(_user(deleted_at=deleted_at), fresh_payload) is True
    assert is_operator_token_revoked(_operator(deleted_at=deleted_at), fresh_payload) is True


@pytest.mark.parametrize("naive", [False, True], ids=["aware", "sqlite_naive"])
@pytest.mark.parametrize(
    ("iat_offset", "revoked"),
    [(-1, True), (0, False), (1, False)],
    ids=["1s_before", "same_second", "1s_after"],
)
def test_password_change_gate_still_allows_same_second(iat_offset: int, revoked: bool, naive: bool):
    """パスワード変更ゲートは従来どおり同一秒を許す（変更直後に同じリクエストで新トークンを
    発行するため）。時刻の変換を共通化したことによる挙動の変化が無いことの固定。"""
    changed_at = _BOUNDARY.replace(tzinfo=None) if naive else _BOUNDARY
    user = _user(password_changed_at=changed_at)
    assert is_user_token_revoked(user, {"iat": _BOUNDARY_SEC + iat_offset}) is revoked


def test_case_access_gate_does_not_apply_session_boundary():
    """トークンを受け取らない閲覧ゲートは境界を見ない（解除後に再ログインした業者を
    弾かないため。iat の判定はトークンから業者を解決する側の責務）。"""
    assert_operator_case_access(_operator(sessions_revoked_at=_BOUNDARY))


# ──────────────── 復帰経路・再停止・旧コードで停止されたアカウント（QA 指摘の追加） ────────────────


async def _line_login(client: AsyncClient, line_user_id: str = _LINE_USER_ID_FOR_USER) -> httpx.Response:
    """Bearer を付けない LINE ログイン（交換）。パスワードを持たない利用者の唯一の入口。"""
    with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
        return await client.post(
            "/api/v1/auth/line/exchange", json={"line_access_token": "dummy-line-token"}
        )


async def test_line_only_user_recovers_via_line_login_after_unsuspend(
    client: AsyncClient, db_session: AsyncSession
):
    """LINE 専用の依頼者（パスワード無し）は、解除後に LINE ログインで復帰できる。

    パスワードを持たない利用者にとって LINE ログインは唯一の復帰経路。ここへ失効判定を
    誤って足すと恒久的に締め出されるため、解除後も新しいトークンが発行され通ることを固定する。
    """
    admin_token = await _make_admin(client, db_session)
    r = await _line_login(client)
    assert r.status_code == 200, r.text
    user_id = uuid.UUID(r.json()["user"]["id"])
    user = await db_session.get(User, user_id)
    assert user is not None and user.password_hash is None
    old_token = create_access_token(
        user_id, "user", "user", issued_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )

    assert (await _set_suspended(client, admin_token, "users", user_id, True)).status_code == 200
    r = await _line_login(client)
    _assert_suspended(r, "停止中の LINE ログイン")

    assert (await _set_suspended(client, admin_token, "users", user_id, False)).status_code == 200
    await _simulate_time_passed_since_suspension(db_session, user)
    r = await _line_login(client)
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]
    for path, dep in _USER_PATHS:
        r = await client.get(path, headers=_auth(new_token))
        assert r.status_code == 200, f"{path}（{dep}）: {r.text}"
        _assert_revoked(await client.get(path, headers=_auth(old_token)), f"{path}（旧トークン）")


async def test_resuspension_revokes_token_issued_after_previous_relogin(
    client: AsyncClient, db_session: AsyncSession
):
    """停止→解除→再ログイン→再停止→解除の2周目で、1周目の再ログインで得たトークンも失効する。"""
    admin_token = await _make_admin(client, db_session)
    email = "resuspend_cycle@example.com"
    _, user_id = await _signup_user(client, email)
    assert (await _set_suspended(client, admin_token, "users", user_id, True)).status_code == 200
    assert (await _set_suspended(client, admin_token, "users", user_id, False)).status_code == 200
    user = await db_session.get(User, user_id)
    assert user is not None
    await _simulate_time_passed_since_suspension(db_session, user)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": _USER_PASSWORD})
    assert r.status_code == 200, r.text
    relogin_token = r.json()["access_token"]
    r = await client.get("/api/v1/users/me/profile", headers=_auth(relogin_token))
    assert r.status_code == 200, r.text

    assert (await _set_suspended(client, admin_token, "users", user_id, True)).status_code == 200
    assert (await _set_suspended(client, admin_token, "users", user_id, False)).status_code == 200
    _assert_revoked(
        await client.get("/api/v1/users/me/profile", headers=_auth(relogin_token)), "2周目の解除後"
    )


@pytest.mark.parametrize("kind", ["users", "operators"])
async def test_unsuspend_blocks_old_tokens_of_account_suspended_without_boundary(
    client: AsyncClient, db_session: AsyncSession, kind: str
):
    """境界を持たないまま停止中のアカウント（デプロイ切替中に旧コードで停止された等）も、
    解除時に境界が解除時刻へ進むため、停止前のトークンは解除後に 401 になる。"""
    admin_token = await _make_admin(client, db_session)
    old_issued_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    if kind == "users":
        _, account_id = await _signup_user(client, "legacy_suspended_user@example.com")
        account: User | Operator | None = await db_session.get(User, account_id)
        old_token = create_access_token(account_id, "user", "user", issued_at=old_issued_at)
        probe_path = "/api/v1/users/me/profile"
    else:
        _, account_id = await _verified_operator(
            client, admin_token, "legacy_suspended_op@example.com"
        )
        account = await db_session.get(Operator, account_id)
        old_token = create_access_token(
            account_id, "operator", "operator", issued_at=old_issued_at
        )
        probe_path = "/api/v1/operator/profile"
    assert account is not None
    # 旧コードで停止された状態を再現する（is_suspended だけ立ち、境界は NULL）。
    account.is_suspended = True
    account.sessions_revoked_at = None
    await db_session.commit()

    assert (await _set_suspended(client, admin_token, kind, account_id, False)).status_code == 200
    await db_session.refresh(account)
    assert account.sessions_revoked_at is not None
    _assert_revoked(await client.get(probe_path, headers=_auth(old_token)), f"{kind} の旧トークン")


async def test_unsuspend_request_for_never_suspended_operator_keeps_boundary_null(
    client: AsyncClient, db_session: AsyncSession
):
    """一度も停止していない業者への解除要求では境界を作らない（誤操作で業者を締め出さない）。"""
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(client, admin_token, "never_suspended_op@example.com")
    r = await _set_suspended(client, admin_token, "operators", op_id, False)
    assert r.status_code == 200, r.text
    operator = await db_session.get(Operator, op_id)
    assert operator is not None
    assert operator.sessions_revoked_at is None
    r = await client.get("/api/v1/operator/profile", headers=_auth(op_token))
    assert r.status_code == 200, r.text


async def test_unsuspend_notifications_ask_for_relogin(monkeypatch):
    """解除通知（メール・LINE）は再ログインが必要なことを案内する（解除後は停止前のログインが
    無効のままのため、「使えない」という問い合わせを防ぐ）。"""
    from app.services import line_notify, notify

    sent: dict[str, str] = {}

    async def fake_send(to_email: str, subject: str, html: str) -> bool:
        sent["mail"] = html
        return True

    async def fake_push(line_user_id: str, text: str) -> bool:
        sent["line"] = text
        return True

    monkeypatch.setattr(notify, "_send", fake_send)
    monkeypatch.setattr(line_notify, "_push", fake_push)
    assert await notify.send_account_unsuspended("user@example.com", "user") is True
    assert await line_notify.push_account_unsuspended("U-test", "operator") is True
    assert "あらためてログイン" in sent["mail"]
    assert "あらためてログイン" in sent["line"]
    assert "これまでどおりご利用いただけます" not in sent["mail"] + sent["line"]
