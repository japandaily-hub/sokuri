"""退会時の問い合わせ匿名化を送信者アカウント（contact_messages.user_id）に限定する回帰テスト。

security review 指摘（MEDIUM）: 退会処理（users._delete_and_anonymize_user）が公開フォームの
問い合わせを「メールアドレス一致」だけで匿名化していた。signup はメールの所有確認を
しないため、第三者が他人のアドレスで登録→即退会するだけで、その人が送った苦情・
削除請求などの記録を運営の受信台帳から消せた（先に登録しておき、後から来た
問い合わせを消す「仕込み」も可能だった）。

是正後の契約:
- ``POST /contact`` はログイン中の依頼者の送信だけを ``user_id`` に記録する
  （deps.get_optional_user。無効・期限切れ・業者・用途限定・停止中・退会済み・
  パスワード変更前のトークンはいずれも匿名送信扱いで受け付け、401/403 にしない）。
- 退会時の匿名化は ``user_id`` が一致する行だけ。

あわせて、最後の有効な管理者の自己退会（ADMIN_EMAILS による自動付与の窓が開く）を
409 で拒否する堅牢化も検証する。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import create_access_token, create_reauth_token, hash_password
from app.db.models.contact_message import ContactMessage
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
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _isolate_contact_side_effects(monkeypatch):
    """運営宛メールを送らない・プロセス内キャップ（モジュールグローバル）をリセットする。"""
    from app.api.v1.endpoints import contact as contact_endpoint

    monkeypatch.setattr(get_settings(), "admin_emails_raw", "")
    contact_endpoint._recent_notification_timestamps.clear()
    contact_endpoint._alert_threshold_notified = False
    yield
    contact_endpoint._recent_notification_timestamps.clear()
    contact_endpoint._alert_threshold_notified = False


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _contact_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "問合 太郎",
        "email": "asker@example.com",
        "category": "trouble",
        "message": "保有個人情報の削除を請求します。",
    }
    payload.update(overrides)
    return payload


async def _signup_user(client: AsyncClient, email: str) -> tuple[str, uuid.UUID]:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": "依頼者太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"], uuid.UUID(r.json()["user"]["id"])


async def _withdraw(client: AsyncClient, token: str, password: str = "password123"):
    return await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": password, "confirm": True},
        headers=_auth(token),
    )


async def _all_contacts(db_session: AsyncSession) -> list[ContactMessage]:
    # API と同一セッションの identity map に古い値が残らないよう、DB から読み直す。
    db_session.expire_all()
    return list(
        (
            await db_session.scalars(
                select(ContactMessage).order_by(ContactMessage.created_at, ContactMessage.id)
            )
        ).all()
    )


class TestWithdrawalOnlyAnonymizesOwnContacts:
    async def test_signup_with_someone_elses_email_then_withdraw_keeps_their_contacts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """他人のアドレスで登録→即退会しても、その人の問い合わせ記録は一切変わらない。"""
        victim_email = "victim@example.com"
        r = await client.post(
            "/api/v1/contact",
            json=_contact_payload(email=victim_email, name="被害 花子"),
        )
        assert r.status_code == 202, r.text

        attacker_token, _ = await _signup_user(client, victim_email)
        r = await _withdraw(client, attacker_token)
        assert r.status_code == 200, r.text

        [row] = await _all_contacts(db_session)
        assert row.user_id is None
        assert row.email == victim_email
        assert row.name == "被害 花子"
        assert row.message == "保有個人情報の削除を請求します。"

    async def test_prestaged_account_cannot_erase_later_contacts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """先に他人のアドレスで登録しておき、後から来た匿名の問い合わせを消す「仕込み」も不可。"""
        victim_email = "victim-later@example.com"
        attacker_token, _ = await _signup_user(client, victim_email)

        r = await client.post(
            "/api/v1/contact",
            json=_contact_payload(email=victim_email, name="後から 送信"),
        )
        assert r.status_code == 202, r.text

        r = await _withdraw(client, attacker_token)
        assert r.status_code == 200, r.text

        [row] = await _all_contacts(db_session)
        assert row.email == victim_email
        assert row.name == "後から 送信"
        assert row.message == "保有個人情報の削除を請求します。"

    async def test_logged_in_submission_is_linked_and_anonymized_on_withdrawal(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """本人がログイン中に送った問い合わせは user_id で紐付き、退会時に匿名化される。"""
        email = "self-withdraw@example.com"
        token, user_id = await _signup_user(client, email)
        r = await client.post(
            "/api/v1/contact",
            json=_contact_payload(email=email, name="退会予定 花子"),
            headers=_auth(token),
        )
        assert r.status_code == 202, r.text
        [row] = await _all_contacts(db_session)
        assert row.user_id == user_id

        r = await _withdraw(client, token)
        assert r.status_code == 200, r.text

        [row] = await _all_contacts(db_session)
        assert row.name == f"deleted-{user_id}"
        assert row.email == f"deleted-{user_id}@deleted.katazuke.internal"
        assert row.message == "[削除済み]"

    async def test_withdrawal_does_not_touch_other_users_linked_contacts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """別の依頼者に紐付いた問い合わせは、同じ文面・同じメールでも巻き添えにしない。"""
        leaving_token, leaving_id = await _signup_user(client, "leaving@example.com")
        staying_token, staying_id = await _signup_user(client, "staying@example.com")
        for token in (leaving_token, staying_token):
            r = await client.post(
                "/api/v1/contact",
                json=_contact_payload(email="shared@example.com"),
                headers=_auth(token),
            )
            assert r.status_code == 202, r.text

        r = await _withdraw(client, leaving_token)
        assert r.status_code == 200, r.text

        rows = {row.user_id: row for row in await _all_contacts(db_session)}
        assert rows[leaving_id].message == "[削除済み]"
        assert rows[staying_id].email == "shared@example.com"
        assert rows[staying_id].message == "保有個人情報の削除を請求します。"


class TestUnlinkedContactReviewNotice:
    """紐付かない同一メールの問い合わせは自動で消さず、運営へ本人確認のうえでの削除を依頼する。

    privacy 第7条（退会時は遅滞なく削除）を、他人の記録を消さずに運用で担保するための通知。
    """

    async def test_withdrawal_notifies_admins_about_unlinked_same_email_contacts(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "ops1@example.com,ops2@example.com")
        email = "Unlinked.Self@example.com"
        with patch(
            "app.api.v1.endpoints.contact.notify.send_contact_received", new_callable=AsyncMock
        ):
            for _ in range(2):
                r = await client.post("/api/v1/contact", json=_contact_payload(email=email))
                assert r.status_code == 202, r.text
        token, _ = await _signup_user(client, email.lower())

        with patch(
            "app.api.v1.endpoints.users.notify.send_withdrawn_contact_review_admin_alert",
            new_callable=AsyncMock,
        ) as review_mock:
            r = await _withdraw(client, token)
        assert r.status_code == 200, r.text

        assert review_mock.await_count == 2
        sent_to = {call.args[0] for call in review_mock.await_args_list}
        assert sent_to == {"ops1@example.com", "ops2@example.com"}
        for call in review_mock.await_args_list:
            assert call.args[1] == email.lower()
            assert call.args[2] == 2
        # 通知するだけで、紐付かない行そのものは変更しない。
        rows = await _all_contacts(db_session)
        assert all(row.message == "保有個人情報の削除を請求します。" for row in rows)

    async def test_no_notice_when_all_contacts_are_linked_or_absent(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "ops@example.com")
        email = "linked-only@example.com"
        token, _ = await _signup_user(client, email)
        with patch(
            "app.api.v1.endpoints.contact.notify.send_contact_received", new_callable=AsyncMock
        ):
            r = await client.post(
                "/api/v1/contact", json=_contact_payload(email=email), headers=_auth(token)
            )
            assert r.status_code == 202, r.text

        with patch(
            "app.api.v1.endpoints.users.notify.send_withdrawn_contact_review_admin_alert",
            new_callable=AsyncMock,
        ) as review_mock:
            r = await _withdraw(client, token)
        assert r.status_code == 200, r.text
        assert review_mock.await_count == 0

    async def test_notice_body_escapes_the_email_address(self, monkeypatch):
        """通知本文へ差し込む連絡先メールは HTML エスケープする（既存通知と同じ規約）。"""
        from app.services import notify

        captured: dict[str, str] = {}

        async def fake_send(to_email: str, subject: str, body: str) -> bool:
            captured["body"] = body
            return True

        monkeypatch.setattr(notify, "_send", fake_send)
        ok = await notify.send_withdrawn_contact_review_admin_alert(
            "ops@example.com", '"><script>x</script>@example.com', 3
        )
        assert ok is True
        assert "<script>" not in captured["body"]
        assert "&lt;script&gt;" in captured["body"]
        assert "3 件" in captured["body"]


class TestContactOptionalAuth:
    async def test_anonymous_submission_is_not_linked(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        r = await client.post("/api/v1/contact", json=_contact_payload())
        assert r.status_code == 202, r.text
        [row] = await _all_contacts(db_session)
        assert row.user_id is None

    @pytest.mark.parametrize(
        "token_kind",
        [
            "garbage",
            "expired",
            "operator",
            "reauth_purpose",
            "suspended_user",
            "withdrawn_user_old_token",
            "before_password_change",
        ],
    )
    async def test_invalid_or_revoked_tokens_are_accepted_as_anonymous(
        self, client: AsyncClient, db_session: AsyncSession, token_kind: str
    ):
        """無効・失効トークンでも 401/403 にせず匿名送信として受け付け、紐付けない。

        停止中の依頼者は停止の案内からお問い合わせ窓口へ誘導されるため、ここで弾くと
        唯一の連絡手段が塞がる（web の共通処理も 401/403 でサインアウトする）。
        """
        now = datetime.now(timezone.utc)
        token, user_id = await _signup_user(client, f"{token_kind}@example.com")
        user = await db_session.get(User, user_id)
        assert user is not None

        if token_kind == "garbage":
            sent_token = "not-a-jwt"
        elif token_kind == "expired":
            sent_token = create_access_token(
                user_id, "user", "user", expires_minutes=1, issued_at=now - timedelta(hours=1)
            )
        elif token_kind == "operator":
            operator = Operator(
                company_name="問合せ業者",
                contact_email="contact-op@example.com",
                vendor_status="active",
            )
            db_session.add(operator)
            await db_session.commit()
            sent_token = create_access_token(operator.id, "operator", "operator")
        elif token_kind == "reauth_purpose":
            sent_token = create_reauth_token(user_id, "user")
        elif token_kind == "suspended_user":
            user.is_suspended = True
            await db_session.commit()
            sent_token = token
        elif token_kind == "withdrawn_user_old_token":
            r = await _withdraw(client, token)
            assert r.status_code == 200, r.text
            sent_token = token
        else:  # before_password_change
            sent_token = create_access_token(
                user_id, "user", "user", issued_at=now - timedelta(hours=1)
            )
            user.password_changed_at = now
            await db_session.commit()

        r = await client.post(
            "/api/v1/contact",
            json=_contact_payload(email="anon@example.com"),
            headers=_auth(sent_token),
        )
        assert r.status_code == 202, r.text
        [row] = await _all_contacts(db_session)
        assert row.user_id is None
        assert row.email == "anon@example.com"

    async def test_db_failure_while_resolving_sender_keeps_contact_accepted(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """送信者の解決で DB 例外が出ても 500 にせず、匿名送信として 202・運営通知を維持する。

        contact.py は「保存に失敗してもメール通知と 202 は維持する」設計のため、任意認証の
        段階で 500 にするとログイン中の問い合わせだけが DB 障害で消えてしまう（QA 指摘 M3）。
        """
        from sqlalchemy.exc import OperationalError

        token, _ = await _signup_user(client, "db-down@example.com")
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "ops@example.com")
        monkeypatch.setattr(
            db_session,
            "get",
            AsyncMock(side_effect=OperationalError("SELECT users", {}, Exception("db down"))),
        )
        with patch(
            "app.api.v1.endpoints.contact.notify.send_contact_received", new_callable=AsyncMock
        ) as send_mock:
            r = await client.post(
                "/api/v1/contact",
                json=_contact_payload(email="db-down@example.com"),
                headers=_auth(token),
            )
        assert r.status_code == 202, r.text
        assert send_mock.await_count == 1
        [row] = await _all_contacts(db_session)
        assert row.user_id is None


async def _make_admin(
    client: AsyncClient, db_session: AsyncSession, email: str, *, deleted: bool = False
) -> str | None:
    admin = User(
        email=email, password_hash=hash_password("adminpass123"), name="管理者", role="admin"
    )
    if deleted:
        admin.deleted_at = datetime.now(timezone.utc)
    db_session.add(admin)
    await db_session.commit()
    if deleted:
        return None
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "adminpass123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestLastAdminSelfDelete:
    async def test_only_admin_cannot_withdraw(self, client: AsyncClient, db_session: AsyncSession):
        """唯一の有効な admin の自己退会は 409（ADMIN_EMAILS 自動付与の窓を開けない）。"""
        token = await _make_admin(client, db_session, "only-admin@katadzuke.jp")
        # 退会済みの元 admin は「有効な admin」に数えない（auth._admin_role_available と同一定義）。
        await _make_admin(client, db_session, "former-admin@katadzuke.jp", deleted=True)
        assert token is not None

        r = await _withdraw(client, token, password="adminpass123")
        assert r.status_code == 409, r.text
        assert "最後の管理者" in r.json()["detail"]

        db_session.expire_all()
        admin = await db_session.scalar(select(User).where(User.email == "only-admin@katadzuke.jp"))
        assert admin is not None
        assert admin.deleted_at is None
        assert admin.role == "admin"

    async def test_admin_can_withdraw_when_another_active_admin_exists(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await _make_admin(client, db_session, "leaving-admin@katadzuke.jp")
        await _make_admin(client, db_session, "remaining-admin@katadzuke.jp")
        assert token is not None

        r = await _withdraw(client, token, password="adminpass123")
        assert r.status_code == 200, r.text

    async def test_regular_user_withdrawal_is_unaffected_without_any_admin(
        self, client: AsyncClient
    ):
        token, _ = await _signup_user(client, "regular@example.com")
        r = await _withdraw(client, token)
        assert r.status_code == 200, r.text
