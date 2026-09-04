"""POST /contact の統合テスト（R3-operator H1対応）と、通知テンプレートの内容確認
（M7: 落選通知に案件情報を含める / M8: メールフッターに事業者名・所在地・問い合わせ先）。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import contact as contact_endpoint
from app.api.v1.router import api_router
from app.config import get_settings
from app.db.session import get_session
from app.services import notify


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
def _reset_contact_process_cap() -> None:
    """R-M4対応: contact.py のプロセス内キャップ（N-4）はモジュールグローバルの
    deque でテスト間共有されるため、本ファイルの全テストの前後でリセットする。
    """
    contact_endpoint._recent_notification_timestamps.clear()
    contact_endpoint._alert_threshold_notified = False
    yield
    contact_endpoint._recent_notification_timestamps.clear()
    contact_endpoint._alert_threshold_notified = False


def _valid_payload() -> dict:
    return {
        "name": "テスト太郎",
        "email": "contact-sender@example.com",
        # web/src/app/contact/page.tsx の <select name="category"> が実際に送信する
        # value 属性（HTMLSelectElement.value）。日本語ラベルではなく英字スラッグ
        # （security review M-1対応・ContactCategory Literal と一致させる）。
        "category": "trouble",
        "message": "取引でトラブルが発生しました。ご確認をお願いします。",
    }


async def test_contact_success_sends_mail_to_admin_emails(
    client: AsyncClient, monkeypatch
):
    """ADMIN_EMAILS 宛にメールが送信され、202 + {"ok": true} が返る。"""
    monkeypatch.setattr(
        get_settings(), "admin_emails_raw", "admin1@example.com,admin2@example.com"
    )
    with patch(
        "app.api.v1.endpoints.contact.notify.send_contact_received",
        new_callable=AsyncMock,
    ) as send_mock:
        r = await client.post("/api/v1/contact", json=_valid_payload())
    assert r.status_code == 202, r.text
    assert r.json() == {"ok": True}
    assert send_mock.await_count == 2
    called_to = {c.args[0] for c in send_mock.await_args_list}
    assert called_to == {"admin1@example.com", "admin2@example.com"}


async def test_contact_without_admin_emails_still_returns_202(
    client: AsyncClient, monkeypatch
):
    """ADMIN_EMAILS 未設定でも依頼者には202を返す（運用ログで検知可能にする代わりに偽の失敗を見せない）。"""
    monkeypatch.setattr(get_settings(), "admin_emails_raw", "")
    with patch(
        "app.api.v1.endpoints.contact.notify.send_contact_received",
        new_callable=AsyncMock,
    ) as send_mock:
        r = await client.post("/api/v1/contact", json=_valid_payload())
    assert r.status_code == 202
    assert r.json() == {"ok": True}
    send_mock.assert_not_called()


@pytest.mark.parametrize(
    "override",
    [
        {"name": ""},
        {"email": "not-an-email"},
        {"category": ""},
        {"message": ""},
        {"name": "a" * 101},
        {"message": "a" * 4001},
        # security review M-1対応: category は web の <select> value と一致する
        # Literal のみ許容する。旧仕様の日本語ラベルや未知の値は拒否する。
        {"category": "トラブル・クレーム"},
        {"category": "unknown-category"},
        # M-1対応: 改行以外の制御文字・Unicode双方向制御文字（RLO 等）は拒否する。
        {"name": "テスト‮太郎"},
        {"message": "本文の途中に​ゼロ幅文字"},
    ],
)
async def test_contact_validation_errors_422(client: AsyncClient, override: dict):
    payload = {**_valid_payload(), **override}
    r = await client.post("/api/v1/contact", json=payload)
    assert r.status_code == 422, r.text


async def test_contact_message_allows_newlines(client: AsyncClient, monkeypatch):
    """M-1対応: message の改行（``\\n``）は制御文字拒否の対象外（複数行の本文を許容）。"""
    monkeypatch.setattr(get_settings(), "admin_emails_raw", "admin1@example.com")
    payload = {**_valid_payload(), "message": "1行目\n2行目\n3行目"}
    with patch(
        "app.api.v1.endpoints.contact.notify.send_contact_received",
        new_callable=AsyncMock,
    ) as send_mock:
        r = await client.post("/api/v1/contact", json=payload)
    assert r.status_code == 202, r.text
    send_mock.assert_awaited_once()


async def test_contact_name_allows_unassigned_unicode_category_cn(
    client: AsyncClient, monkeypatch
):
    """N-9対応: 制御文字拒否は Cc/Cf/Co/Cs のみが対象。Cn（未割り当て）は
    偽陽性源のため許容する（U+0378 は本テスト実行時点で未割り当て＝Cn）。
    """
    monkeypatch.setattr(get_settings(), "admin_emails_raw", "admin1@example.com")
    payload = {**_valid_payload(), "name": "テスト" + "͸" + "太郎"}
    with patch(
        "app.api.v1.endpoints.contact.notify.send_contact_received",
        new_callable=AsyncMock,
    ) as send_mock:
        r = await client.post("/api/v1/contact", json=payload)
    assert r.status_code == 202, r.text
    send_mock.assert_awaited_once()


async def test_contact_process_wide_cap_returns_503_after_limit(
    client: AsyncClient, monkeypatch
):
    """N-4対応: プロセス内キャップは「リクエスト数」で数え、超過時は202ではなく
    503を返す（黙って消音しない）。detail にはβ的な救済導線として運営の
    メールアドレスを含める。
    """
    monkeypatch.setattr(get_settings(), "admin_emails_raw", "cap-admin@example.com")
    monkeypatch.setattr(contact_endpoint, "_MAX_NOTIFICATIONS_PER_HOUR", 2)
    with patch(
        "app.api.v1.endpoints.contact.notify.send_contact_received",
        new_callable=AsyncMock,
    ) as send_mock, patch(
        "app.api.v1.endpoints.contact.alerts.send_alert",
        new_callable=AsyncMock,
    ) as alert_mock:
        for i in range(2):
            payload = {**_valid_payload(), "email": f"cap-sender-{i}@example.com"}
            r = await client.post("/api/v1/contact", json=payload)
            assert r.status_code == 202, r.text
        # 3回目はプロセス内キャップ（上限2）に達しているため 503 で拒否される。
        payload = {**_valid_payload(), "email": "cap-sender-final@example.com"}
        r = await client.post("/api/v1/contact", json=payload)
        await asyncio.sleep(0.05)  # fire_and_forget のタスクを消化
    assert r.status_code == 503, r.text
    assert "katazuke.info@gmail.com" in r.json()["detail"]
    # R3再レビュー Medium対応: 503にはRetry-Afterヘッダ（秒・正の整数）を付ける。
    retry_after = r.headers.get("retry-after")
    assert retry_after is not None
    assert int(retry_after) > 0
    # 上限2に対して3回リクエストしたが、送信されたのは最初の2回分のみ。
    assert send_mock.await_count == 2
    # 超過検知時に運営アラート（severity=warning）が1回発火する。
    alert_mock.assert_awaited_once()
    assert alert_mock.await_args.kwargs["severity"] == "warning"


async def test_contact_alert_threshold_warns_without_blocking(
    client: AsyncClient, monkeypatch
):
    """R3再レビュー Medium対応: ブロッキング上限（300/hour）はそのままに、
    従来の 30 は「アラート閾値」へ降格した。閾値超過時は202のまま処理を継続し、
    運営へ warning アラートを最初の1回だけ発火する（2回連続で超えても再送しない）。
    """
    monkeypatch.setattr(get_settings(), "admin_emails_raw", "threshold-admin@example.com")
    monkeypatch.setattr(contact_endpoint, "_ALERT_THRESHOLD_PER_HOUR", 1)
    with patch(
        "app.api.v1.endpoints.contact.notify.send_contact_received",
        new_callable=AsyncMock,
    ) as send_mock, patch(
        "app.api.v1.endpoints.contact.alerts.send_alert",
        new_callable=AsyncMock,
    ) as alert_mock:
        for i in range(3):
            payload = {**_valid_payload(), "email": f"threshold-sender-{i}@example.com"}
            r = await client.post("/api/v1/contact", json=payload)
            assert r.status_code == 202, r.text
        await asyncio.sleep(0.05)  # fire_and_forget のタスクを消化
    # ブロッキング上限（デフォルト300）には遠く及ばないため3回とも受理・送信される。
    assert send_mock.await_count == 3
    # 閾値（1）超過は2回目以降ずっと続くが、アラートは最初の1回だけ発火する。
    alert_mock.assert_awaited_once()
    assert alert_mock.await_args.kwargs["severity"] == "warning"


async def test_contact_process_wide_cap_counts_requests_not_recipients(
    client: AsyncClient, monkeypatch
):
    """N-4対応: 上限は「実送信通数」でなく「リクエスト数」。ADMIN_EMAILS が複数件
    あっても、1リクエストは1枠のみを消費する（従来は宛先数ぶん消費していた）。
    """
    monkeypatch.setattr(
        get_settings(), "admin_emails_raw", "admin1@example.com,admin2@example.com"
    )
    monkeypatch.setattr(contact_endpoint, "_MAX_NOTIFICATIONS_PER_HOUR", 1)
    with patch(
        "app.api.v1.endpoints.contact.notify.send_contact_received",
        new_callable=AsyncMock,
    ) as send_mock:
        r = await client.post("/api/v1/contact", json=_valid_payload())
    assert r.status_code == 202, r.text
    # ADMIN_EMAILS 2件でも消費される枠は1つ（宛先ごとに枠を消費しない）。
    assert send_mock.await_count == 2
    assert len(contact_endpoint._recent_notification_timestamps) == 1


# ──────────────────────────── 通知テンプレートの内容（M7 / M8） ────────────────────────────


async def test_send_bid_lost_includes_case_context_and_link(monkeypatch):
    """M7対応: 落選通知の本文に案件（地域・利用目的）とリンクが含まれる。"""
    captured: dict[str, str] = {}

    async def _fake_send(to_email: str, subject: str, html: str) -> bool:
        captured["subject"] = subject
        captured["html"] = html
        return True

    monkeypatch.setattr(notify, "_send", _fake_send)
    monkeypatch.setattr(get_settings(), "brevo_api_key", "dummy")

    await notify.send_bid_lost("op@example.com", "case-123", "東京都", "世田谷区", "遺品整理")

    assert "東京都" in captured["html"]
    assert "世田谷区" in captured["html"]
    assert "遺品整理" in captured["html"]
    assert "/operator/cases/case-123" in captured["html"]


def test_mail_footer_includes_operator_org_name_address_and_contact():
    """M8対応: メールフッターに事業者名・所在地・問い合わせ先が含まれる（legalページと同一の値）。"""
    footer_html = notify._wrap("<p>本文</p>")
    assert "カタヅケ運営事務局" in footer_html
    assert "神奈川県横浜市" in footer_html
    assert "katazuke.info@gmail.com" in footer_html


async def test_contact_notification_uses_japanese_category_label(monkeypatch):
    """QA M5対応: 運営宛メールの件名・本文の「種別」は英字スラッグではなく、
    web/src/app/contact/page.tsx の <option> と同一の日本語ラベルで出す。"""
    captured: dict[str, str] = {}

    async def _fake_send(to_email: str, subject: str, body_html: str) -> bool:
        captured["subject"] = subject
        captured["html"] = body_html
        return True

    monkeypatch.setattr(notify, "_send", _fake_send)
    monkeypatch.setattr(get_settings(), "brevo_api_key", "dummy")

    await notify.send_contact_received(
        "admin@example.com", "テスト太郎", "sender@example.com", "pricing", "本文"
    )

    assert "料金・費用について" in captured["subject"]
    assert "pricing" not in captured["subject"]
    assert "料金・費用について" in captured["html"]
    assert "pricing" not in captured["html"]
