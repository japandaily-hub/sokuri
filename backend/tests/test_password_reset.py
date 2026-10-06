"""メールによるパスワード再設定（POST /auth/password-reset/request・/confirm）の統合テスト。

- 要求は登録の有無にかかわらず同じ 202・同じ本文。案内メールは対象アカウントがある時だけ送る
  （退会・停止中・LINE 専用・内部用アドレスには送らない）。
- トークンは DB にハッシュだけを保存し、30分で期限切れ・1回限り・新しい要求で旧トークン無効。
- 確定で既存のログイン（JWT）が失効する（依頼者・業者）。
- レート制限（要求: IP 軸・アカウント軸、確定: IP 軸）。
- メールの件名・本文に個人情報を入れない。ログに平文のトークン・メールアドレスを出さない。

メール送信は ``notify._send`` を差し替えて呼び出し内容だけを確かめる（実際には送らない）。
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import get_rate_limiter
from app.api.v1.endpoints.password_reset import PASSWORD_RESET_ACCEPTED_DETAIL
from app.api.v1.router import api_router
from app.core.rate_limit import RateLimitConfig, RateLimiter, RateLimitRule
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.operator import Operator
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.user import User
from app.db.session import get_session
from app.services import notify
from app.services import password_reset as password_reset_service

_REQUEST_URL = "/api/v1/auth/password-reset/request"
_CONFIRM_URL = "/api/v1/auth/password-reset/confirm"
_PUBLIC_IP = {"X-Forwarded-For": "198.51.100.77"}
_USER_EMAIL = "reset-user@example.com"
_OPERATOR_EMAIL = "reset-operator@example.co.jp"
_OLD_PASSWORD = "old-password-123"
_NEW_PASSWORD = "new-password-456"
_TOKEN_IN_LINK_RE = re.compile(r"/password-reset/confirm\?token=([A-Za-z0-9_-]+)&amp;type=(user|operator)")


def _create_test_app(session: AsyncSession, limiter: RateLimiter | None = None) -> FastAPI:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    if limiter is not None:
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.include_router(api_router, prefix="/api/v1")
    return app


def _limiter(*, request_ip: int = 100, request_account: int = 100, confirm_ip: int = 100) -> RateLimiter:
    generous = RateLimitRule(1000, 3600)
    return RateLimiter(
        config=RateLimitConfig(
            enabled=True,
            login_account=generous,
            login_ip=generous,
            sensitive_account=generous,
            signup_ip=generous,
            line_ip=generous,
            max_keys=10000,
            password_reset_request_ip=RateLimitRule(request_ip, 3600),
            password_reset_request_account=RateLimitRule(request_account, 3600),
            password_reset_confirm_ip=RateLimitRule(confirm_ip, 3600),
        )
    )


@pytest.fixture
def sent_mail(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """``notify._send`` を差し替え、送信の呼び出しだけを記録する（実際には送らない）。"""
    mock = AsyncMock(return_value=True)
    monkeypatch.setattr(notify, "_send", mock)
    return mock


async def _create_user(db_session: AsyncSession, email: str = _USER_EMAIL, **overrides) -> User:
    user = User(email=email, password_hash=hash_password(_OLD_PASSWORD), name="再設定 太郎")
    for key, value in overrides.items():
        setattr(user, key, value)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _create_operator(db_session: AsyncSession, email: str = _OPERATOR_EMAIL, **overrides) -> Operator:
    operator = Operator(
        company_name="再設定テスト商会",
        contact_email=email,
        vendor_status="active",
        password_hash=hash_password(_OLD_PASSWORD),
    )
    for key, value in overrides.items():
        setattr(operator, key, value)
    db_session.add(operator)
    await db_session.commit()
    await db_session.refresh(operator)
    return operator


def _token_from_mail(sent_mail: AsyncMock, index: int = -1) -> tuple[str, str]:
    html = sent_mail.call_args_list[index].args[2]
    match = _TOKEN_IN_LINK_RE.search(html)
    assert match, html
    return match.group(1), match.group(2)


async def _request(client: AsyncClient, email: str, account_type: str = "user", headers=None):
    return await client.post(
        _REQUEST_URL,
        json={"email": email, "account_type": account_type},
        headers=headers if headers is not None else _PUBLIC_IP,
    )


async def _confirm(client: AsyncClient, token: str, account_type: str = "user", password: str = _NEW_PASSWORD):
    return await client.post(
        _CONFIRM_URL,
        json={"token": token, "account_type": account_type, "new_password": password},
        headers=_PUBLIC_IP,
    )


async def _rows(db_session: AsyncSession) -> list[PasswordResetToken]:
    db_session.expire_all()
    return list((await db_session.scalars(select(PasswordResetToken))).all())


# ──────────────────────────── 要求: 同一応答・送信の有無 ────────────────────────────


async def test_request_returns_identical_202_for_existing_and_unknown_accounts(db_session, sent_mail):
    await _create_user(db_session)
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        existing = await _request(client, _USER_EMAIL)
        unknown = await _request(client, "nobody@example.com")
        wrong_type = await _request(client, _USER_EMAIL, account_type="operator")

    for res in (existing, unknown, wrong_type):
        assert res.status_code == 202
        assert res.json() == {"detail": PASSWORD_RESET_ACCEPTED_DETAIL}
        assert res.headers.get("content-length") == existing.headers.get("content-length")
    # 送るのは実在する（種別も一致する）アカウントの1通だけ。
    assert sent_mail.await_count == 1
    assert sent_mail.call_args.args[0] == _USER_EMAIL
    assert len(await _rows(db_session)) == 1


async def test_request_matches_email_case_insensitively(db_session, sent_mail):
    await _create_user(db_session)
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await _request(client, "Reset-User@Example.COM")
    assert res.status_code == 202
    assert sent_mail.await_count == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"deleted_at": datetime.now(timezone.utc)},
        {"is_suspended": True},
        {"password_hash": None},  # LINE ログイン専用
    ],
    ids=["deleted", "suspended", "line_only"],
)
async def test_request_does_not_send_to_ineligible_users(db_session, sent_mail, overrides):
    await _create_user(db_session, **overrides)
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await _request(client, _USER_EMAIL)
    assert res.status_code == 202
    assert res.json() == {"detail": PASSWORD_RESET_ACCEPTED_DETAIL}
    sent_mail.assert_not_awaited()
    assert await _rows(db_session) == []


@pytest.mark.parametrize(
    "email",
    ["line-U0123456789abcdef@line.katazuke.internal", "deleted-1@deleted.katazuke.internal"],
)
async def test_request_never_sends_to_internal_placeholder_addresses(db_session, sent_mail, email):
    await _create_user(db_session, email=email)
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await _request(client, email)
    assert res.status_code == 202
    sent_mail.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [{"deleted_at": datetime.now(timezone.utc)}, {"is_suspended": True}],
    ids=["deleted", "suspended"],
)
async def test_request_does_not_send_to_ineligible_operators(db_session, sent_mail, overrides):
    await _create_operator(db_session, **overrides)
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await _request(client, _OPERATOR_EMAIL, account_type="operator")
    assert res.status_code == 202
    sent_mail.assert_not_awaited()


async def test_request_rejects_non_json_and_unknown_fields(db_session, sent_mail):
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        form = await client.post(
            _REQUEST_URL,
            content=f"email={_USER_EMAIL}&account_type=user",
            headers={**_PUBLIC_IP, "Content-Type": "application/x-www-form-urlencoded"},
        )
        extra = await client.post(
            _REQUEST_URL,
            json={"email": _USER_EMAIL, "account_type": "user", "redirect": "https://evil.example"},
            headers=_PUBLIC_IP,
        )
        bad_type = await _request(client, _USER_EMAIL, account_type="admin")
    assert form.status_code == 415
    assert extra.status_code == 422
    assert bad_type.status_code == 422
    sent_mail.assert_not_awaited()


async def test_background_failure_is_logged_without_secrets_and_response_is_unchanged(
    db_session, sent_mail, monkeypatch, caplog
):
    await _create_user(db_session)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(password_reset_service, "issue_reset_token", boom)
    app = _create_test_app(db_session)
    caplog.set_level(logging.INFO)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await _request(client, _USER_EMAIL)
    assert res.status_code == 202
    assert res.json() == {"detail": PASSWORD_RESET_ACCEPTED_DETAIL}
    sent_mail.assert_not_awaited()
    failures = [r for r in caplog.records if "発行に失敗" in r.getMessage()]
    assert len(failures) == 1
    assert _USER_EMAIL not in caplog.text


# ──────────────────────────── メール本文・トークンの保存 ────────────────────────────


async def test_mail_contains_only_link_and_no_personal_data_and_db_stores_hash_only(db_session, sent_mail):
    user = await _create_user(db_session)
    user_id = user.id
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _request(client, _USER_EMAIL)

    to_email, subject, html = sent_mail.call_args.args
    assert to_email == _USER_EMAIL
    assert subject == "【カタヅケ】パスワード再設定のご案内"
    for personal in (_USER_EMAIL, "再設定", "太郎"):
        if personal == "再設定":
            continue  # 件名・本文の定型句に含まれる語のため対象外（氏名は「太郎」で確かめる）
        assert personal not in subject
        assert personal not in html
    assert "心当たりがない場合は" in html
    assert "30分" in html
    raw_token, account_type = _token_from_mail(sent_mail)
    assert account_type == "user"
    assert len(raw_token) >= 43  # token_urlsafe(32)

    rows = await _rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.account_type == "user"
    assert row.account_id == user_id
    assert row.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert row.token_hash != raw_token
    assert row.used_at is None
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    remaining = expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < remaining <= timedelta(minutes=30)


# ──────────────────────────── 確定 ────────────────────────────


async def test_confirm_sets_new_password_and_token_is_single_use(db_session, sent_mail):
    user = await _create_user(db_session)
    user_id = user.id
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _request(client, _USER_EMAIL)
        raw_token, _ = _token_from_mail(sent_mail)
        ok = await _confirm(client, raw_token)
        again = await _confirm(client, raw_token, password="another-pass-789")
        login_new = await client.post(
            "/api/v1/auth/login", json={"email": _USER_EMAIL, "password": _NEW_PASSWORD}
        )
        login_old = await client.post(
            "/api/v1/auth/login", json={"email": _USER_EMAIL, "password": _OLD_PASSWORD}
        )

    assert ok.status_code == 200
    assert "再設定しました" in ok.json()["detail"]
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "password_reset_invalid"
    db_session.expire_all()
    refreshed = await db_session.get(User, user_id)
    assert verify_password(_NEW_PASSWORD, refreshed.password_hash)
    assert refreshed.password_changed_at is not None
    assert login_new.status_code == 200
    assert login_old.status_code == 401
    rows = await _rows(db_session)
    assert all(r.used_at is not None for r in rows)


async def test_confirm_failures_share_one_generic_response(db_session, sent_mail):
    await _create_user(db_session)
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _request(client, _USER_EMAIL)
        raw_token, _ = _token_from_mail(sent_mail)
        unknown = await _confirm(client, "A" * 43)
        wrong_type = await _confirm(client, raw_token, account_type="operator")
        # 種別違いの試行ではトークンは消費されない（正しい種別ならまだ使える）。
        await db_session.execute(
            update(PasswordResetToken).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await db_session.commit()
        expired = await _confirm(client, raw_token)

    assert unknown.status_code == wrong_type.status_code == expired.status_code == 400
    assert unknown.json() == wrong_type.json() == expired.json()


async def test_confirm_validates_password_and_token_format_before_lookup(db_session, sent_mail):
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        short_pw = await _confirm(client, "A" * 43, password="short")
        long_pw = await _confirm(client, "A" * 43, password="x" * 129)
        bad_token = await _confirm(client, "../../etc/passwd" + "A" * 30)
        short_token = await _confirm(client, "abc")
    assert {short_pw.status_code, long_pw.status_code, bad_token.status_code, short_token.status_code} == {422}


async def test_new_request_invalidates_previous_token(db_session, sent_mail):
    await _create_user(db_session)
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _request(client, _USER_EMAIL)
        first_token, _ = _token_from_mail(sent_mail, 0)
        await _request(client, _USER_EMAIL)
        second_token, _ = _token_from_mail(sent_mail, 1)
        await _request(client, _USER_EMAIL)
        third_token, _ = _token_from_mail(sent_mail, 2)
        old = await _confirm(client, first_token)
        older = await _confirm(client, second_token)
        latest = await _confirm(client, third_token)
    assert len({first_token, second_token, third_token}) == 3
    assert old.status_code == 400
    assert older.status_code == 400
    assert latest.status_code == 200
    # 使用済み・無効化済みの行は次の要求で削除されるため、行数は増え続けない。
    assert len(await _rows(db_session)) <= 2


async def test_confirm_rejects_account_deleted_after_issue_and_consumes_token(db_session, sent_mail):
    user = await _create_user(db_session)
    user_id = user.id
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _request(client, _USER_EMAIL)
        raw_token, _ = _token_from_mail(sent_mail)
        user.deleted_at = datetime.now(timezone.utc)
        await db_session.commit()
        res = await _confirm(client, raw_token)
    assert res.status_code == 400
    db_session.expire_all()
    refreshed = await db_session.get(User, user_id)
    assert verify_password(_OLD_PASSWORD, refreshed.password_hash)
    assert all(r.used_at is not None for r in await _rows(db_session))


# ──────────────────────────── 既存ログインの失効 ────────────────────────────


async def test_confirm_revokes_existing_user_sessions(db_session, sent_mail):
    user = await _create_user(db_session)
    user_id = user.id
    old_jwt = create_access_token(
        user.id, "user", user.role, issued_at=datetime.now(timezone.utc) - timedelta(seconds=30)
    )
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_jwt}"})
        await _request(client, _USER_EMAIL)
        raw_token, _ = _token_from_mail(sent_mail)
        assert (await _confirm(client, raw_token)).status_code == 200
        after = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_jwt}"})
    assert before.status_code == 200
    assert after.status_code == 401


async def test_operator_reset_flow_revokes_existing_operator_sessions(db_session, sent_mail):
    operator = await _create_operator(db_session)
    operator_id = operator.id
    old_jwt = create_access_token(
        operator.id, "operator", "operator", issued_at=datetime.now(timezone.utc) - timedelta(seconds=30)
    )
    app = _create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_jwt}"})
        await _request(client, _OPERATOR_EMAIL, account_type="operator")
        raw_token, account_type = _token_from_mail(sent_mail)
        assert account_type == "operator"
        # 業者のトークンを依頼者として使うことはできない。
        assert (await _confirm(client, raw_token, account_type="user")).status_code == 400
        assert (await _confirm(client, raw_token, account_type="operator")).status_code == 200
        after = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_jwt}"})
        login_new = await client.post(
            "/api/v1/auth/operator/login", json={"email": _OPERATOR_EMAIL, "password": _NEW_PASSWORD}
        )
    assert before.status_code == 200
    assert after.status_code == 401
    assert login_new.status_code == 200
    db_session.expire_all()
    refreshed = await db_session.get(Operator, operator_id)
    assert refreshed.sessions_revoked_at is not None


# ──────────────────────────── レート制限 ────────────────────────────


async def test_request_ip_axis_counts_every_request(db_session, sent_mail):
    app = _create_test_app(db_session, _limiter(request_ip=2))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        statuses = [
            (await _request(client, f"ip-axis-{i}@example.com")).status_code for i in range(3)
        ]
    assert statuses == [202, 202, 429]


async def test_request_account_axis_is_per_email_and_type_and_same_for_unknown(db_session, sent_mail):
    await _create_user(db_session)
    app = _create_test_app(db_session, _limiter(request_account=2))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        existing = [
            (await _request(client, _USER_EMAIL, headers={"X-Forwarded-For": f"198.51.100.{i}"})).status_code
            for i in range(1, 4)
        ]
        unknown = [
            (await _request(client, "ghost@example.com", headers={"X-Forwarded-For": f"203.0.113.{i}"})).status_code
            for i in range(1, 4)
        ]
        # 種別が違えば別のバケット（依頼者側の連打で業者側の案内を止められない）。
        other_type = await _request(
            client, _USER_EMAIL, account_type="operator", headers={"X-Forwarded-For": "192.0.2.9"}
        )
    assert existing == [202, 202, 429]
    assert unknown == existing  # 登録の有無で 429 の出方が変わらない
    assert other_type.status_code == 202
    assert sent_mail.await_count == 2


async def test_confirm_ip_axis_counts_every_attempt(db_session, sent_mail):
    app = _create_test_app(db_session, _limiter(confirm_ip=3))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        statuses = [(await _confirm(client, f"{'B' * 42}{i}")).status_code for i in range(4)]
    assert statuses == [400, 400, 400, 429]


# ──────────────────────────── ログに秘密を出さない ────────────────────────────


async def test_logs_never_contain_raw_token_or_email(db_session, sent_mail, caplog):
    await _create_user(db_session)
    await _create_operator(db_session)
    app = _create_test_app(db_session)
    # app.* は DEBUG まで全部見る。ドライバ（aiosqlite）の DEBUG はテスト用 SQLite が
    # バインド値を出すだけで本番（asyncpg・hide_parameters）には無いため INFO に留める。
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="app")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _request(client, _USER_EMAIL)
        user_token, _ = _token_from_mail(sent_mail)
        await _request(client, _OPERATOR_EMAIL, account_type="operator")
        operator_token, _ = _token_from_mail(sent_mail)
        await _request(client, "unknown-person@example.com")
        await _confirm(client, user_token)
        await _confirm(client, user_token)  # 再使用（失敗ログ）
        await _confirm(client, operator_token, account_type="operator")

    text = caplog.text
    assert "再設定の案内を発行しました" in text  # 陽性対照: ログ自体は出ている
    for secret in (
        user_token,
        operator_token,
        hashlib.sha256(user_token.encode()).hexdigest(),
        _USER_EMAIL,
        _OPERATOR_EMAIL,
        "unknown-person@example.com",
    ):
        assert secret not in text


async def test_missing_brevo_key_log_masks_recipient(db_session, monkeypatch, caplog):
    """実送信経路（_send_raw）で API キー未設定のとき、宛先はマスクされ本文（トークン）は出ない。"""
    from app.config import get_settings

    await _create_user(db_session)
    monkeypatch.setattr(get_settings(), "brevo_api_key", "")
    monkeypatch.setattr(notify.alerts, "fire_and_forget", lambda coro: coro.close())
    captured: dict[str, str] = {}
    real_send_raw = notify._send_raw

    async def spy_send_raw(to_email: str, subject: str, html: str):
        captured["html"] = html
        return await real_send_raw(to_email, subject, html)

    monkeypatch.setattr(notify, "_send_raw", spy_send_raw)
    app = _create_test_app(db_session)
    caplog.set_level(logging.INFO)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await _request(client, _USER_EMAIL)).status_code == 202
    match = _TOKEN_IN_LINK_RE.search(captured["html"])
    assert match
    assert match.group(1) not in caplog.text
    assert _USER_EMAIL not in caplog.text
    assert "mail_sent=False" in caplog.text


def test_reset_token_hash_is_sha256_hex():
    raw = "x" * 43
    assert password_reset_service.hash_reset_token(raw) == hashlib.sha256(raw.encode()).hexdigest()
    assert len(password_reset_service.hash_reset_token(str(uuid.uuid4()))) == 64
