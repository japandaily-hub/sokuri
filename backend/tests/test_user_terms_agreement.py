"""依頼者の利用規約・プライバシーポリシーへの同意をサーバーで判定・記録する（3周目の法務監査・中）。

従来は画面のチェックボックスだけで同意を判定し、サーバーには何も残らなかった。LINE 交換の入口
（/auth/line/exchange）を直接呼べば、チェックを通らずに新規アカウントを作れた。

- POST /auth/signup: ``agreed_terms: true`` が無ければ 422（日本語の理由・code 付き）で、ユーザーを作らない。
  あれば現行の版数（サーバーの定数。クライアントの terms_version は信用しない）と日時を保存する。
- terms_version が送られて現行と食い違うときは 409 terms_version_outdated（security review L-2）で、
  ユーザーを作らない。未送信（旧 web）は現行版への同意として記録して通す。
- POST /auth/line/exchange（Bearer なし）: 未登録の LINE アカウントからの新規作成だけ同意を必須にする。
  既存の LINE ユーザーのログインは同意なしで通る（後方互換）。新規作成時は版数と日時を保存する。
- 真偽値以外（"true"・1）は同意とみなさない（strict）。
- 拒否のログに個人情報（メールアドレス・LINE userId・送られた版数の文字列）を出さない。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import TERMS_AGREEMENT_REQUIRED_CODE, TERMS_VERSION_OUTDATED_CODE
from app.db.models.user import User
from app.schemas_katadzuke import CURRENT_USER_TERMS_VERSION
from tests.test_line_integration import (  # noqa: F401（autouse フィクスチャの再利用）
    _line_client_id_configured,
    _mock_line_get,
    create_test_app,
)

_LINE_USER_ID = "U0123456789abcdef0123456789abcdef"
_PII_EMAIL = "terms-probe@example.com"


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_test_app(db_session)), base_url="http://test"
    ) as ac:
        yield ac


async def _user_count(db_session: AsyncSession) -> int:
    return int(await db_session.scalar(select(func.count()).select_from(User)) or 0)


def _assert_terms_required(r: httpx.Response) -> None:
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == TERMS_AGREEMENT_REQUIRED_CODE
    assert "利用規約" in detail["message"]


def _assert_recent(value: datetime | None) -> None:
    assert value is not None
    if value.tzinfo is None:  # SQLite は naive で返す
        value = value.replace(tzinfo=timezone.utc)
    assert abs(datetime.now(timezone.utc) - value) < timedelta(minutes=1)


def test_orm_columns_match_migration_0048():
    """ORM の列（テストの create_all の正本）が 0048 の列と同じ形であること。"""
    table = User.__table__
    assert table.c.agreed_terms_version.nullable is True
    assert table.c.agreed_terms_version.type.length == 32
    assert table.c.agreed_at.nullable is True
    assert table.c.agreed_at.type.timezone is True
    # 現行の版数は列長に収まる（収まらないと登録が全件 500 になる）。
    assert 0 < len(CURRENT_USER_TERMS_VERSION) <= 32


# ──────────────────────────── POST /auth/signup ────────────────────────────


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"agreed_terms": False},
        {"agreed_terms": None},
    ],
    ids=["missing", "false", "null"],
)
async def test_signup_without_agreement_is_rejected(client, db_session, extra, caplog):
    body = {"email": _PII_EMAIL, "password": "password123", "name": "規約 太郎", **extra}
    caplog.set_level(logging.INFO)
    r = await client.post("/api/v1/auth/signup", json=body)
    if extra.get("agreed_terms", False) is None:
        # null は真偽値でないためスキーマの検証で 422（同意とはみなさない点は同じ）。
        assert r.status_code == 422, r.text
    else:
        _assert_terms_required(r)
    assert await _user_count(db_session) == 0
    assert _PII_EMAIL not in caplog.text
    assert "規約 太郎" not in caplog.text


@pytest.mark.parametrize("value", ["true", 1, "1"])
async def test_signup_non_boolean_agreement_is_not_consent(client, db_session, value):
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": _PII_EMAIL, "password": "password123", "agreed_terms": value},
    )
    assert r.status_code == 422, r.text
    assert await _user_count(db_session) == 0


def _assert_terms_outdated(r: httpx.Response) -> None:
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == TERMS_VERSION_OUTDATED_CODE
    assert detail["message"] == "利用規約が更新されています。ページを再読み込みしてください。"


@pytest.mark.parametrize(
    "version_extra",
    [{}, {"terms_version": None}, {"terms_version": CURRENT_USER_TERMS_VERSION}],
    ids=["missing_old_web", "null", "current"],
)
async def test_signup_with_agreement_records_server_version_and_time(
    client, db_session, caplog, version_extra
):
    caplog.set_level(logging.INFO)
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": _PII_EMAIL, "password": "password123", "agreed_terms": True, **version_extra},
    )
    assert r.status_code == 201, r.text
    user = await db_session.scalar(select(User).where(User.email == _PII_EMAIL))
    assert user is not None
    assert user.agreed_terms_version == CURRENT_USER_TERMS_VERSION
    _assert_recent(user.agreed_at)
    assert _PII_EMAIL not in caplog.text


async def test_signup_with_outdated_terms_version_is_409(client, db_session, caplog):
    """画面の版数が現行と食い違えば、現行版として記録せず 409（security review L-2）。"""
    caplog.set_level(logging.INFO)
    r = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _PII_EMAIL,
            "password": "password123",
            "agreed_terms": True,
            "terms_version": "1999-01-01-forged",
        },
    )
    _assert_terms_outdated(r)
    assert await _user_count(db_session) == 0
    assert "1999-01-01-forged" not in caplog.text
    assert _PII_EMAIL not in caplog.text


async def test_signup_terms_version_too_long_is_rejected(client, db_session):
    r = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": _PII_EMAIL,
            "password": "password123",
            "agreed_terms": True,
            "terms_version": "x" * 33,
        },
    )
    assert r.status_code == 422, r.text
    assert await _user_count(db_session) == 0


# ──────────────────────────── POST /auth/line/exchange ────────────────────────────


async def _line_exchange(client: AsyncClient, body_extra: dict, line_user_id: str = _LINE_USER_ID):
    with patch.object(httpx.AsyncClient, "get", new=_mock_line_get(line_user_id)):
        return await client.post(
            "/api/v1/auth/line/exchange",
            json={"line_access_token": "dummy-line-token", **body_extra},
        )


@pytest.mark.parametrize("extra", [{}, {"agreed_terms": False}], ids=["missing", "false"])
async def test_line_new_account_without_agreement_is_rejected(client, db_session, extra, caplog):
    caplog.set_level(logging.INFO)
    r = await _line_exchange(client, extra)
    _assert_terms_required(r)
    assert await _user_count(db_session) == 0
    assert _LINE_USER_ID not in caplog.text


async def test_line_new_account_with_agreement_records_version_and_time(client, db_session):
    r = await _line_exchange(client, {"agreed_terms": True, "terms_version": CURRENT_USER_TERMS_VERSION})
    assert r.status_code == 200, r.text
    assert r.json()["account_type"] == "user"
    user = await db_session.scalar(select(User).where(User.line_user_id == _LINE_USER_ID))
    assert user is not None
    assert user.agreed_terms_version == CURRENT_USER_TERMS_VERSION
    _assert_recent(user.agreed_at)


async def test_existing_line_user_logs_in_without_agreement(client, db_session):
    """既存の LINE ユーザー（0048 より前に作られ、同意記録が NULL の人を含む）は同意なしでログインできる。"""
    legacy = User(
        email=f"line-{_LINE_USER_ID}@line.katazuke.internal",
        password_hash=None,
        role="user",
        line_user_id=_LINE_USER_ID,
    )
    db_session.add(legacy)
    await db_session.commit()

    r = await _line_exchange(client, {})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(legacy.id)
    await db_session.refresh(legacy)
    # ログインでは同意記録を書き換えない（再同意は求めない・推測の値で埋めない）。
    assert legacy.agreed_terms_version is None
    assert legacy.agreed_at is None
    assert await _user_count(db_session) == 1


async def test_line_relogin_after_consented_creation_keeps_original_record(client, db_session):
    first = await _line_exchange(client, {"agreed_terms": True})
    assert first.status_code == 200, first.text
    user = await db_session.scalar(select(User).where(User.line_user_id == _LINE_USER_ID))
    assert user is not None
    recorded_at = user.agreed_at

    second = await _line_exchange(client, {})
    assert second.status_code == 200, second.text
    await db_session.refresh(user)
    assert user.agreed_terms_version == CURRENT_USER_TERMS_VERSION
    assert user.agreed_at == recorded_at


async def test_line_new_account_with_outdated_terms_version_is_409(client, db_session, caplog):
    caplog.set_level(logging.INFO)
    r = await _line_exchange(client, {"agreed_terms": True, "terms_version": "2000-01-01"})
    _assert_terms_outdated(r)
    assert await _user_count(db_session) == 0
    assert _LINE_USER_ID not in caplog.text
    assert "2000-01-01" not in caplog.text
