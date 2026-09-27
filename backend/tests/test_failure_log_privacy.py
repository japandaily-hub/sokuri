"""失敗時のログに個人情報・capability URL を残さないことの検査（2026-09-27 のログ点検の QA 指摘）。

- ローカルディスクの削除失敗: OSError の文言には失敗したファイルの絶対パス（storage_key＝無認証の
  capability URL を含む）が入るため、丸めたキーと例外の種類・errno だけを残す（R2Backend と同じ）。
- 業者事前申込の保存失敗: SQLAlchemy の例外は INSERT の引数（メール・氏名・住所・電話番号）を、
  PostgreSQL の例外は DETAIL（重複したキーの値）を文言に含むため、例外の型と SQLSTATE だけを残す。
"""
from __future__ import annotations

import logging
import pathlib
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import get_settings
from app.db.session import get_session
from app.services.storage_backends.local_disk import LocalDiskBackend

_STORAGE_KEY = "0123456789abcdef0123456789abcdef.jpg"


async def test_local_disk_delete_failure_log_keeps_storage_key_masked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))

    def _deny(self: pathlib.Path, missing_ok: bool = False) -> None:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(pathlib.Path, "unlink", _deny)
    with caplog.at_level(logging.WARNING, logger="app.services.storage_backends.local_disk"):
        await LocalDiskBackend().delete(_STORAGE_KEY)  # 例外は漏れない（ベストエフォート）
    assert "key=01234567... PermissionError errno=13" in caplog.text
    assert _STORAGE_KEY not in caplog.text
    assert str(tmp_path) not in caplog.text


class _FakeUniqueViolation(Exception):
    """asyncpg の UniqueViolationError に見立てた例外（sqlstate を持ち、文言に DETAIL を含む）。"""

    sqlstate = "23505"


_APPLICATION = {
    "company_name": "漏えい確認株式会社",
    "representative_name": "代表 漏太郎",
    "registered_address": "東京都港区芝公園4-2-8",
    "contact_name": "担当 漏花子",
    "email": "leak-check@example.com",
    "phone": "03-9876-5432",
    "business_type": "corp",
    "service_area": "東京都",
    "categories": "家電,家具",
    "license_number": "第987654321098号",
    "invoice_number": "T9876543210987",
    "bank_account": {
        "bank_name": "みずほ銀行",
        "branch_name": "東京営業部",
        "account_type": "ordinary",
        "account_number": "7654321",
        "account_holder": "ロウエイカクニンカブシキガイシャ",
    },
    "agreed": True,
}


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_operator_application_save_failure_log_has_no_personal_data(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    orig = _FakeUniqueViolation(
        'duplicate key value violates unique constraint "uq_x"\n'
        "DETAIL:  Key (contact_email)=(leak-check@example.com) already exists."
    )
    error = IntegrityError(
        "INSERT INTO operator_applications (company_name, contact_email, phone) VALUES ($1, $2, $3)",
        ("漏えい確認株式会社", "leak-check@example.com", "03-9876-5432"),
        orig,
    )

    async def _failing_commit() -> None:
        raise error

    monkeypatch.setattr(db_session, "commit", _failing_commit)
    with caplog.at_level(logging.ERROR, logger="app.api.v1.endpoints.operator_applications"):
        r = await client.post("/api/v1/operator-applications", json=_APPLICATION)
    assert r.status_code == 500, r.text

    records = [rec for rec in caplog.records if rec.name == "app.api.v1.endpoints.operator_applications"]
    messages = [rec.getMessage() for rec in records]
    assert messages == [
        "operator_applications: 申込の保存に失敗しました - error=IntegrityError cause=_FakeUniqueViolation sqlstate=23505"
    ]
    assert all(rec.exc_info is None for rec in records)  # トレースバック（例外の文言）も出さない
    for raw in ("leak-check@example.com", "漏えい確認株式会社", "03-9876-5432", "芝公園", "7654321", "漏太郎", "漏花子"):
        assert raw not in caplog.text
