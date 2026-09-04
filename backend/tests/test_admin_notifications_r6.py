"""運営操作の通知と、/readyz の設定検証・通知失敗の可視化のテスト（r6 修正分）。

対象:
- r6-web-quality H3: 業者の入札可否切替（verify）の無通知
- r6-web-quality H1: アカウント停止解除（suspended=false）の無通知
- r6-web-quality H2: 本人確認書類の承認/却下の無通知
- r6-backend H-4: /readyz に本番必須設定の充足状況（bool のみ）を出す
- r6-backend H-3: メール/LINE の送信失敗を運営アラートで可視化する
- r6-backend M-7: 業者事前申込の承認に行ロックを掛ける（SQLite では no-op）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.models.user_identity_document import (
    DOCUMENT_STATUS_PENDING,
    UserIdentityDocument,
)
from app.db.session import get_session
from app.services import alerts, line_notify, notify


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


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="admin_r6_notify@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_r6_notify@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _make_operator(
    db_session: AsyncSession, email: str, *, with_license: bool = True
) -> Operator:
    operator = Operator(
        company_name="通知テスト業者",
        contact_email=email,
        password_hash=hash_password("operatorpass1"),
        license_number="第123456789012号",
        vendor_status="pending",
        license_image_uploaded_at=datetime.now(timezone.utc) if with_license else None,
    )
    db_session.add(operator)
    await db_session.commit()
    return operator


async def _signup_user(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "password123"}
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


# ──────────────── H3: 業者の入札可否切替の通知 ────────────────


async def test_verify_operator_notifies_operator(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    admin_token = await _make_admin(client, db_session)
    operator = await _make_operator(db_session, "verify_notify_op@example.com")
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_operator_verified", dispatch_mock
    )

    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["vendor_status"] == "active"
    dispatch_mock.assert_awaited_once()
    args = dispatch_mock.await_args.args
    assert args[1] == "verify_notify_op@example.com"
    assert args[3] is True


async def test_verify_operator_repeat_same_state_does_not_renotify(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """既に active な業者へ verified=True を再送しても通知は重複しない（r6-verify-fix M4）。"""
    admin_token = await _make_admin(client, db_session)
    operator = await _make_operator(db_session, "verify_repeat_op@example.com")
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_operator_verified", dispatch_mock
    )

    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()

    # 状態不変のまま再送（誤操作・二重送信を想定）。通知は増えない。
    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["vendor_status"] == "active"
    dispatch_mock.assert_awaited_once()


async def test_unverify_operator_notifies_with_inactive_flag(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    admin_token = await _make_admin(client, db_session)
    operator = await _make_operator(db_session, "unverify_notify_op@example.com")
    # 状態不変時は通知しない（r6-verify-fix M4）ため、実際に active → pending へ
    # 遷移する状態から出発させる（pending のまま unverify しても遷移が起きない）。
    operator.vendor_status = "active"
    await db_session.commit()
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_operator_verified", dispatch_mock
    )

    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/verify",
        json={"verified": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.await_args.args[3] is False


# ──────────────── H1: 停止解除の通知（停止時は送らない） ────────────────


async def test_operator_unsuspend_notifies_but_suspend_does_not(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    admin_token = await _make_admin(client, db_session)
    operator = await _make_operator(db_session, "suspend_notify_op@example.com")
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_account_unsuspended", dispatch_mock
    )

    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_not_awaited()

    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()
    args = dispatch_mock.await_args.args
    assert args[1] == "suspend_notify_op@example.com"
    assert args[2] == "operator"


async def test_operator_unsuspend_repeat_does_not_renotify(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """既に解除済みの業者へ suspended=false を再送しても通知は重複しない（r6-verify-fix M4）。"""
    admin_token = await _make_admin(client, db_session)
    operator = await _make_operator(db_session, "unsuspend_repeat_op@example.com")
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_account_unsuspended", dispatch_mock
    )

    await client.patch(
        f"/api/v1/admin/operators/{operator.id}/suspend",
        json={"suspended": True},
        headers=_auth(admin_token),
    )
    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()

    # 既に解除済み（is_suspended=False）へ再度 suspended=false を送っても増えない。
    r = await client.patch(
        f"/api/v1/admin/operators/{operator.id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_suspended"] is False
    dispatch_mock.assert_awaited_once()


async def test_user_unsuspend_repeat_does_not_renotify(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """一度も停止していない依頼者へ suspended=false を送っても通知しない（r7 M-2）。

    業者側（test_operator_unsuspend_repeat_does_not_renotify）と対称。停止→解除の
    遷移が実際に起きた時だけ通知する。
    """
    admin_token = await _make_admin(client, db_session)
    await _signup_user(client, "unsuspend_repeat_user@example.com")
    target = await db_session.scalar(
        select(User).where(User.email == "unsuspend_repeat_user@example.com")
    )
    assert target is not None
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_account_unsuspended", dispatch_mock
    )

    # 停止していない状態への suspended=false は状態が変わらない＝通知しない。
    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_suspended"] is False
    dispatch_mock.assert_not_awaited()

    # 停止 → 解除の遷移では1通だけ届く。
    await client.patch(
        f"/api/v1/admin/users/{target.id}/suspend",
        json={"suspended": True, "reason": "規約違反の疑い"},
        headers=_auth(admin_token),
    )
    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()

    # 解除済みへの再送では増えない。
    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()


async def test_user_unsuspend_notifies(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    admin_token = await _make_admin(client, db_session)
    await _signup_user(client, "suspend_notify_user@example.com")
    target = await db_session.scalar(
        select(User).where(User.email == "suspend_notify_user@example.com")
    )
    assert target is not None
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_account_unsuspended", dispatch_mock
    )

    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/suspend",
        json={"suspended": True, "reason": "規約違反の疑い"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_not_awaited()

    r = await client.patch(
        f"/api/v1/admin/users/{target.id}/suspend",
        json={"suspended": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.await_args.args[2] == "user"


# ──────────────── H2: 本人確認書類の審査結果通知 ────────────────


async def _make_identity_document(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    document = UserIdentityDocument(
        user_id=user_id,
        doc_type="drivers_license",
        front_image_data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        front_image_content_type="image/png",
        status=DOCUMENT_STATUS_PENDING,
        submitted_at=datetime.now(timezone.utc),
    )
    db_session.add(document)
    await db_session.commit()
    return document.id


async def test_identity_document_approve_and_reject_notify_user(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    admin_token = await _make_admin(client, db_session)
    await _signup_user(client, "identity_notify_user@example.com")
    target = await db_session.scalar(
        select(User).where(User.email == "identity_notify_user@example.com")
    )
    assert target is not None
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.notify_dispatch.dispatch_identity_document_reviewed", dispatch_mock
    )

    approved_id = await _make_identity_document(db_session, target.id)
    r = await client.patch(
        f"/api/v1/admin/identity-documents/{approved_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()
    args = dispatch_mock.await_args.args
    assert args[1] == "identity_notify_user@example.com"
    assert args[2] is True

    dispatch_mock.reset_mock()
    rejected_id = await _make_identity_document(db_session, target.id)
    r = await client.patch(
        f"/api/v1/admin/identity-documents/{rejected_id}/reject",
        json={"reject_reason": "氏名が読み取れません"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    dispatch_mock.assert_awaited_once()
    args = dispatch_mock.await_args.args
    assert args[2] is False
    assert args[3] == "氏名が読み取れません"


# ──────────────── M-7: 事前申込 承認の行ロック ────────────────


async def test_operator_application_approve_uses_row_lock(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """承認は行ロック付きヘルパ経由で申込を取得する（二重発行の直列化）。

    SQLite では ``FOR UPDATE`` が生成されないため、ここでは「ロック版ヘルパを
    通っていること」と「2回目の承認が 409 になること」を検証する。
    """
    admin_token = await _make_admin(client, db_session)
    r = await client.post(
        "/api/v1/operator-applications",
        json={
            "company_name": "申込テスト株式会社",
            "representative_name": "代表 太郎",
            "registered_address": "東京都千代田区丸の内1-1-1",
            "contact_name": "担当 花子",
            "email": "lock_app@example.com",
            "phone": "03-1234-5678",
            "business_type": "corp",
            "service_area": "東京都",
            "categories": "家電,家具",
            "license_number": "第123456789012号",
            "invoice_number": "T1234567890123",
            "bank_account": {
                "bank_name": "みずほ銀行",
                "branch_name": "東京営業部",
                "account_type": "ordinary",
                "account_number": "1234567",
                "account_holder": "モウシコミテストカブシキガイシャ",
            },
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    application_id = r.json()["application_id"]

    from app.api.v1.endpoints import admin as admin_module

    calls: list[uuid.UUID] = []
    original = admin_module._get_application_for_update_or_404

    async def _spy(session: AsyncSession, app_id: uuid.UUID):
        calls.append(app_id)
        return await original(session, app_id)

    monkeypatch.setattr(admin_module, "_get_application_for_update_or_404", _spy)

    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert calls == [uuid.UUID(application_id)]

    # 二度押し（同一申込の再承認）は 409。
    r = await client.patch(
        f"/api/v1/admin/operator-applications/{application_id}/approve",
        headers=_auth(admin_token),
    )
    assert r.status_code == 409, r.text


# ──────────────── H-4: /readyz の設定検証 ────────────────


def test_config_readiness_flags_are_bool_only(monkeypatch):
    """/readyz の config は bool のみを返し、値そのものは絶対に含めない。"""
    from app.main import _config_readiness

    settings = get_settings()
    flags = _config_readiness(settings)
    assert set(flags) == {
        "encryption_key",
        "brevo",
        "line_push",
        "gemini",
        "admin_emails",
        "frontend_base_url",
    }
    assert all(isinstance(v, bool) for v in flags.values())
    # conftest が有効な APP_ENCRYPTION_KEY を注入しているので True。
    assert flags["encryption_key"] is True

    monkeypatch.setattr(settings, "app_encryption_key", "not-a-valid-fernet-key")
    assert _config_readiness(settings)["encryption_key"] is False
    monkeypatch.setattr(settings, "app_encryption_key", "")
    assert _config_readiness(settings)["encryption_key"] is False


async def test_readyz_reports_degraded_config_but_stays_ready(db_engine, monkeypatch):
    """設定が欠けていても status は ready のまま、degraded_config に列挙される。"""
    import app.main as main_module

    # /readyz が参照するエンジンをテスト用 SQLite へ差し替える（本物は PostgreSQL）。
    monkeypatch.setattr(main_module, "engine", db_engine)
    head_rev: str | None = None
    try:
        from alembic.config import Config as _AlembicConfig
        from alembic.script import ScriptDirectory as _ScriptDirectory

        head_rev = _ScriptDirectory.from_config(_AlembicConfig("alembic.ini")).get_current_head()
    except Exception:  # noqa: BLE001 -- 読めない環境ではテーブル有無判定へフォールバック
        head_rev = None
    if head_rev is not None:
        async with db_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                {"rev": head_rev},
            )

    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "")
    monkeypatch.setattr(settings, "google_api_key", "")

    app = main_module.create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/readyz")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["status"] == "ready"
    assert payload["config"]["brevo"] is False
    assert payload["config"]["gemini"] is False
    assert "brevo" in payload["degraded_config"]
    assert "gemini" in payload["degraded_config"]
    # 値そのもの（キー文字列）は payload に一切現れない。
    assert "api_key" not in r.text.lower()


# ──────────────── H-3: 通知送信失敗の可視化 ────────────────


class _RaisingClient:
    """httpx.AsyncClient の代替。post で必ず例外を投げる（送信失敗の再現）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_RaisingClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(self, *args: Any, **kwargs: Any):
        raise RuntimeError("boom: upstream unavailable")


@pytest.fixture
def _capture_alerts(monkeypatch):
    """alerts.fire_and_forget を捕捉する（コルーチンは close してリークさせない）。"""
    fired: list[str] = []

    def _fake_fire_and_forget(coro) -> None:  # noqa: ANN001
        fired.append(coro.cr_frame.f_locals.get("key") or "")
        coro.close()

    monkeypatch.setattr(alerts, "fire_and_forget", _fake_fire_and_forget)
    return fired


async def test_mail_send_failure_fires_warning_alert(monkeypatch, _capture_alerts):
    monkeypatch.setattr(get_settings(), "brevo_api_key", "dummy-key")
    monkeypatch.setattr("app.services.notify.httpx.AsyncClient", _RaisingClient)

    ok = await notify.send_case_created("someone@example.com", str(uuid.uuid4()))
    assert ok is False  # 送信失敗でも例外は投げない（ベストエフォート）
    assert _capture_alerts == ["notify_brevo_send_failed"]


async def test_line_push_failure_fires_warning_alert(monkeypatch, _capture_alerts):
    monkeypatch.setattr(get_settings(), "line_channel_access_token", "dummy-token")
    monkeypatch.setattr("app.services.line_notify.httpx.AsyncClient", _RaisingClient)

    ok = await line_notify.push_case_created("U" + "0" * 32, str(uuid.uuid4()))
    assert ok is False
    assert _capture_alerts == ["line_notify_push_failed"]
