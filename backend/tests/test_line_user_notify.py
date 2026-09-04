"""依頼者・当事者宛のLINE通知（新規入札 / 新着メッセージ）の単体・統合テスト。

- line_notify.push_bid_received / push_message_received: 文面・URL・本文非含有
- notify_dispatch.dispatch_bid_received: LINE優先 / 未連携→メール / LINE失敗→メール /
  仮メール（LINE専用ユーザー）はメール送信スキップ
- notify_dispatch.dispatch_message_received: LINEのみ（未連携なら何もしない）
- create_bid / create_message: BackgroundTasks への積み込み内容

フィクスチャ流儀は tests/test_line_integration.py（単一 db_session を get_session に
override する create_test_app パターン）を踏襲する。
"""

from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import hash_password
from app.db.models.case import Case
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session
from app.services import line_notify, notify_dispatch


@pytest.fixture(autouse=True)
def _reset_message_push_ledger():
    """デバウンス台帳はモジュールグローバルなので、テスト間の汚染を断つ。"""
    notify_dispatch._MESSAGE_PUSH_LAST_SENT.clear()
    yield
    notify_dispatch._MESSAGE_PUSH_LAST_SENT.clear()


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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="admin_usernotify@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_usernotify@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _verified_operator(
    client: AsyncClient, admin_token: str, email: str, company: str = "テスト片付け株式会社"
) -> tuple[str, str]:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201
    code = r.json()["code"]
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
    assert r.status_code == 201, r.text
    data = r.json()
    token, op_id = data["access_token"], data["operator"]["id"]
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    return token, op_id


async def _create_case(client: AsyncClient, user_token: str) -> dict:
    r = await client.post(
        "/api/v1/cases",
        json={
            "purpose": "遺品整理",
            "prefecture": "東京都",
            "city": "世田谷区",
            "address_detail": "桜丘1-2-3 メゾン桜 101号室",
            "photos": [],
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


# ──────────────────────────── line_notify の文面 ────────────────────────────


class TestPushTextAndUrl:
    async def test_push_bid_received_text(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify._push", push_mock)

        result = await line_notify.push_bid_received("U123", "case-abc", "A社", 1234567)

        assert result is True
        line_user_id, text = push_mock.call_args.args
        assert line_user_id == "U123"
        base = get_settings().frontend_base_url
        assert text == (
            "【カタヅケ】新しい入札が届きました。\nA社：1,234,567 円\n" f"{base}/cases/case-abc"
        )

    async def test_push_bid_received_sanitizes_company_name(self, monkeypatch):
        """改行入りの社名で偽の案内行（フィッシングURL等）を作れないこと。"""
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify._push", push_mock)

        evil = "A社\n【カタヅケ】至急こちらへ\nhttps://evil.example.com/login\t 　" + "長" * 60
        await line_notify.push_bid_received("U123", "case-abc", evil, 1000)

        _, text = push_mock.call_args.args
        injected = text.split("\n")[1]
        # 社名は改行を失って1行に潰れ、40字上限で切り詰められる。
        assert injected.endswith("：1,000 円")
        company_part = injected.removesuffix("：1,000 円")
        assert "\n" not in company_part
        assert len(company_part) == 40
        assert company_part == "A社 【カタヅケ】至急こちらへ https://evil.example.com"
        # 本文全体は「見出し / 社名+金額 / URL」の3行のみ＝偽装行を差し込めない。
        assert len(text.split("\n")) == 3
        assert text.split("\n")[2] == f"{get_settings().frontend_base_url}/cases/case-abc"

    async def test_mask_line_user_id(self):
        """ログへ宛先IDを平文で残さない（Low指摘対応）。"""
        assert line_notify._mask_line_user_id("U290490d51e46a6b89d6f562abebf6028") == "U290…"
        assert line_notify._mask_line_user_id(None) == "(none)"
        assert line_notify._mask_line_user_id("") == "(none)"

    async def test_push_skip_log_does_not_leak_full_line_user_id(self, caplog):
        line_user_id = "U290490d51e46a6b89d6f562abebf6028"
        with caplog.at_level("INFO"):
            assert await line_notify._push(line_user_id, "text") is False
        assert line_user_id not in caplog.text
        assert "U290…" in caplog.text

    async def test_push_message_received_user_url(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify._push", push_mock)

        await line_notify.push_message_received("U123", "txn-1", "user")

        _, text = push_mock.call_args.args
        base = get_settings().frontend_base_url
        assert text == f"【カタヅケ】新しいメッセージが届きました。\n{base}/chat/txn-1"

    async def test_push_message_received_operator_url(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify._push", push_mock)

        await line_notify.push_message_received("U456", "txn-2", "operator")

        _, text = push_mock.call_args.args
        base = get_settings().frontend_base_url
        assert text == f"【カタヅケ】新しいメッセージが届きました。\n{base}/operator/chat/txn-2"

    async def test_push_message_received_does_not_leak_body(self, monkeypatch):
        """チャット本文は第三者チャネル（LINE）へ流さない（機微情報の漏えい防止）。"""
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify._push", push_mock)

        # push_message_received のシグネチャは本文を受け取らない＝構造的に漏えい不能。
        await line_notify.push_message_received("U123", "txn-1", "user")

        _, text = push_mock.call_args.args
        assert "住所" not in text
        assert text.count("\n") == 1


# ──────────────────────────── notify_dispatch ────────────────────────────


class TestDispatchBidReceived:
    async def test_prefers_line_when_available(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_received", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_received", email_mock)

        await notify_dispatch.dispatch_bid_received(
            "U123", "user@example.com", "case1", "A社", 10000
        )

        push_mock.assert_called_once_with("U123", "case1", "A社", 10000)
        email_mock.assert_not_called()

    async def test_falls_back_to_email_when_no_line(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_received", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_received", email_mock)

        await notify_dispatch.dispatch_bid_received(
            None, "user@example.com", "case1", "A社", 10000
        )

        push_mock.assert_not_called()
        email_mock.assert_called_once_with("user@example.com", "case1", "A社", 10000)

    async def test_falls_back_to_email_when_line_fails(self, monkeypatch):
        push_mock = AsyncMock(return_value=False)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_received", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_received", email_mock)

        await notify_dispatch.dispatch_bid_received(
            "U123", "user@example.com", "case1", "A社", 10000
        )

        push_mock.assert_called_once()
        email_mock.assert_called_once_with("user@example.com", "case1", "A社", 10000)

    async def test_placeholder_email_is_never_sent(self, monkeypatch):
        """LINE専用ユーザーの仮メール宛にはフォールバックしない（配送不能・ログ汚染防止）。"""
        push_mock = AsyncMock(return_value=False)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_received", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_received", email_mock)

        await notify_dispatch.dispatch_bid_received(
            "U123", "line-U123@line.katazuke.internal", "case1", "A社", 10000
        )

        push_mock.assert_called_once()
        email_mock.assert_not_called()

    async def test_no_line_and_placeholder_email_sends_nothing(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        email_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_bid_received", push_mock)
        monkeypatch.setattr("app.services.notify.send_bid_received", email_mock)

        await notify_dispatch.dispatch_bid_received(
            None, "line-U123@line.katazuke.internal", "case1", "A社", 10000
        )

        push_mock.assert_not_called()
        email_mock.assert_not_called()


class TestDispatchMessageReceived:
    async def test_line_only(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        await notify_dispatch.dispatch_message_received("U123", "txn1", "user")

        push_mock.assert_called_once_with("U123", "txn1", "user")

    async def test_no_op_when_not_linked(self, monkeypatch):
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        await notify_dispatch.dispatch_message_received(None, "txn1", "user")

        push_mock.assert_not_called()

    async def test_line_failure_is_swallowed(self, monkeypatch):
        """LINE失敗でも例外を投げない（通知はベストエフォート）。"""
        push_mock = AsyncMock(return_value=False)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        await notify_dispatch.dispatch_message_received("U123", "txn1", "operator")

        push_mock.assert_called_once()


class TestMessageDebounce:
    """同一 (transaction_id, recipient_party) への Push は5分に1通へ間引く。"""

    @staticmethod
    def _freeze(monkeypatch, clock: list[float]) -> None:
        monkeypatch.setattr("app.services.notify_dispatch._monotonic", lambda: clock[0])

    async def test_second_push_within_window_is_suppressed(self, monkeypatch):
        clock = [1000.0]
        self._freeze(monkeypatch, clock)
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")
        clock[0] += 299.0
        await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")

        push_mock.assert_called_once_with("U123", "txn-deb", "user")

    async def test_push_resumes_after_window(self, monkeypatch):
        clock = [1000.0]
        self._freeze(monkeypatch, clock)
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")
        clock[0] += 300.0
        await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")

        assert push_mock.await_count == 2

    async def test_debounce_is_scoped_per_recipient_party(self, monkeypatch):
        """同一成約でも送信方向が違えば別枠（相互のメッセージが互いを潰さない）。"""
        clock = [1000.0]
        self._freeze(monkeypatch, clock)
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")
        await notify_dispatch.dispatch_message_received("U456", "txn-deb", "operator")

        assert push_mock.await_count == 2

    async def test_failed_push_does_not_consume_window(self, monkeypatch):
        """送信失敗時は抑止せず、次のメッセージで再挑戦できる。"""
        clock = [1000.0]
        self._freeze(monkeypatch, clock)
        push_mock = AsyncMock(return_value=False)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")
        await notify_dispatch.dispatch_message_received("U123", "txn-deb", "user")

        assert push_mock.await_count == 2
        assert notify_dispatch._MESSAGE_PUSH_LAST_SENT == {}

    async def test_ledger_sweeps_expired_entries(self, monkeypatch):
        """台帳は閾値超過時に期限切れエントリを掃除する（無制限に太らない）。"""
        clock = [1000.0]
        self._freeze(monkeypatch, clock)
        push_mock = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.line_notify.push_message_received", push_mock)

        stale = {
            (f"old-{i}", "user"): 0.0
            for i in range(notify_dispatch._MESSAGE_PUSH_SWEEP_THRESHOLD + 1)
        }
        notify_dispatch._MESSAGE_PUSH_LAST_SENT.update(stale)

        await notify_dispatch.dispatch_message_received("U123", "txn-fresh", "user")

        assert notify_dispatch._MESSAGE_PUSH_LAST_SENT == {("txn-fresh", "user"): 1000.0}


class TestBestEffortIsolation:
    """通知起因の例外を BackgroundTask の外へ出さない（Low指摘対応）。"""

    async def test_bid_received_exception_is_swallowed(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "app.services.line_notify.push_bid_received",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        with caplog.at_level("ERROR"):
            await notify_dispatch.dispatch_bid_received(
                "U123", "user@example.com", "case1", "A社", 10000
            )
        assert "dispatch_bid_received" in caplog.text

    async def test_message_received_exception_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.line_notify.push_message_received",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        await notify_dispatch.dispatch_message_received("U123", "txn1", "user")

    async def test_bid_selected_exception_is_swallowed(self, monkeypatch):
        """既存3種の dispatch も同様に保護されている。"""
        monkeypatch.setattr(
            "app.services.line_notify.push_bid_selected",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        await notify_dispatch.dispatch_bid_selected("U123", "op@example.com", "txn1", 10000)


# ──────────────────────────── エンドポイントからの積み込み ────────────────────────────


class TestEndpointDispatchWiring:
    async def test_create_bid_dispatches_bid_received(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "bidrecv_user@example.com")
        op_token, _ = await _verified_operator(client, admin_token, "bidrecv_op@example.com", "A社")
        case = await _create_case(client, user_token)

        with patch(
            "app.api.v1.endpoints.bids.notify_dispatch.dispatch_bid_received", new=AsyncMock()
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/cases/{case['id']}/bids",
                json={"amount": 15000},
                headers=_auth(op_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_called_once_with(
            None, "bidrecv_user@example.com", case["id"], "A社", 15000
        )

    async def _setup_transaction(
        self, client: AsyncClient, db_session: AsyncSession, tag: str
    ) -> tuple[str, str, str]:
        """成約を1件作り、(txn_id, user_token, operator_token) を返す。"""
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, f"{tag}_user@example.com")
        op_token, _ = await _verified_operator(
            client, admin_token, f"{tag}_op@example.com", "A社"
        )
        case = await _create_case(client, user_token)
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids",
            json={"amount": 15000},
            headers=_auth(op_token),
        )
        assert r.status_code == 201, r.text
        bid = r.json()
        r = await client.post(
            f"/api/v1/cases/{case['id']}/bids/{bid['id']}/select",
            headers=_auth(user_token),
        )
        assert r.status_code == 201, r.text
        return r.json()["id"], user_token, op_token

    async def test_operator_message_notifies_owner_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        txn_id, _user_token, op_token = await self._setup_transaction(
            client, db_session, "msgop"
        )
        # 依頼者のみ LINE 連携済みにする。
        await db_session.execute(
            User.__table__.update()
            .where(User.email == "msgop_user@example.com")
            .values(line_user_id="U_owner_msgop")
        )
        await db_session.commit()

        with patch(
            "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
            new=AsyncMock(),
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "訪問日程のご相談です"},
                headers=_auth(op_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_called_once_with("U_owner_msgop", txn_id, "user")

    async def test_user_message_notifies_operator_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        txn_id, user_token, _op_token = await self._setup_transaction(
            client, db_session, "msguser"
        )
        await db_session.execute(
            Operator.__table__.update()
            .where(Operator.contact_email == "msguser_op@example.com")
            .values(line_user_id="U_op_msguser")
        )
        await db_session.commit()

        with patch(
            "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
            new=AsyncMock(),
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "よろしくお願いします"},
                headers=_auth(user_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_called_once_with("U_op_msguser", txn_id, "operator")

    async def test_no_dispatch_when_recipient_not_linked(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """受信者が LINE 未連携なら BackgroundTasks に積まない。"""
        txn_id, user_token, _ = await self._setup_transaction(client, db_session, "msgnone")

        with patch(
            "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
            new=AsyncMock(),
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "こんにちは"},
                headers=_auth(user_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_not_called()

    async def test_no_dispatch_when_case_owner_removed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """退会等で case.user_id が NULL の成約では、業者発言でも送信先が無く無送信。"""
        txn_id, _user_token, op_token = await self._setup_transaction(
            client, db_session, "msgnoowner"
        )
        await db_session.execute(
            Case.__table__.update()
            .where(Case.address_detail == "桜丘1-2-3 メゾン桜 101号室")
            .values(user_id=None)
        )
        await db_session.commit()

        with patch(
            "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
            new=AsyncMock(),
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "日程のご相談です"},
                headers=_auth(op_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_not_called()

    async def test_no_dispatch_when_operator_line_id_is_empty_string(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """line_user_id が空文字（NULLでない未連携相当）でも積まない。"""
        txn_id, user_token, _op_token = await self._setup_transaction(
            client, db_session, "msgempty"
        )
        await db_session.execute(
            Operator.__table__.update()
            .where(Operator.contact_email == "msgempty_op@example.com")
            .values(line_user_id="")
        )
        await db_session.commit()

        with patch(
            "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_message_received",
            new=AsyncMock(),
        ) as dispatch_mock:
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "よろしくお願いします"},
                headers=_auth(user_token),
            )
        assert r.status_code == 201, r.text
        dispatch_mock.assert_not_called()
