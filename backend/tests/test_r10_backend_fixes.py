"""r10 導線監査（第10周）で確定した backend 側の是正の統合テスト。

対象:
- ADD-M10: ``POST /cases`` の prefecture を対応4都県に限定（対応エリア外は422）
- V-M4:    ``TransactionDetailOut`` の reduction_request_count / _limit
- O-M1〜M4: ``GET /admin/identity-documents`` の {items,total,counts} 化・q検索・
           tie-breaker・提出時の admin 宛通知／``GET /admin/operators`` の
           counts.pending_with_license
- O-M5:    ``GET /admin/users`` の include_deleted / suspended 絞り込み
- O-M6:    ``POST /contact`` の DB 保存と ``/admin/contacts`` の一覧・対応済み化
- O-H3:    ``/readyz`` の config に alerts_line / alerts_webhook
- ADD-H1 / O-H2: ``scripts/uptime_check.py`` の通知全滅時 exit 1 と
           degraded_config の状態遷移通知

フィクスチャの作法は tests/test_admin_user_controls.py / tests/test_user_identity.py
と同じ（in-memory SQLite + ASGITransport をローカルに複製する）。
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.limits import MAX_REDUCTION_REQUESTS_PER_TRANSACTION
from app.core.security import hash_password
from app.db.models.contact_message import ContactMessage
from app.db.models.user import User
from app.db.models.user_identity_document import UserIdentityDocument
from app.db.session import get_session
from app.schemas_katadzuke import SERVICE_AREA_PREFECTURES, TransactionDetailOut

_JST = timezone(timedelta(hours=9), name="Asia/Tokyo")


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


async def _make_admin(client: AsyncClient, db_session: AsyncSession, email: str) -> str:
    admin = User(
        email=email, password_hash=hash_password("adminpass123"), name="管理者", role="admin"
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "adminpass123"}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str, name: str = "依頼者太郎") -> tuple[str, str]:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"], r.json()["user"]["id"]


def _case_payload(**overrides: object) -> dict:
    payload: dict = {
        "purpose": "片付け整理",
        "prefecture": "東京都",
        "city": "世田谷区",
        "address_detail": "桜丘1-2-3",
        "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0}],
    }
    payload.update(overrides)
    return payload


# ──────────────── ADD-M10: 案件の対応エリア（4都県）────────────────


class TestCaseServiceArea:
    def test_service_area_is_exactly_four_prefectures(self):
        """Literal と公開タプルが同一（get_args 由来なので構造的に一致する）。"""
        assert set(SERVICE_AREA_PREFECTURES) == {"東京都", "千葉県", "埼玉県", "神奈川県"}

    @pytest.mark.parametrize("prefecture", ["東京都", "千葉県", "埼玉県", "神奈川県"])
    async def test_supported_prefecture_creates_case(
        self, client: AsyncClient, prefecture: str
    ):
        token, _ = await _signup_user(client, f"area_ok_{prefecture}@example.com")
        r = await client.post(
            "/api/v1/cases",
            json=_case_payload(prefecture=prefecture),
            headers=_auth(token),
        )
        assert r.status_code == 201, r.text
        assert r.json()["prefecture"] == prefecture

    @pytest.mark.parametrize("prefecture", ["北海道", "大阪府", "東京", "", "TOKYO"])
    async def test_unsupported_prefecture_returns_422(
        self, client: AsyncClient, prefecture: str
    ):
        """対応エリア外・表記ゆれ・空文字はいずれも作成前に 422 で弾く。

        受け付けてしまうと入札0件のまま滞留し、依頼者は理由が分からないまま待つ。
        """
        token, _ = await _signup_user(client, f"area_ng_{prefecture or 'empty'}@example.com")
        r = await client.post(
            "/api/v1/cases",
            json=_case_payload(prefecture=prefecture),
            headers=_auth(token),
        )
        assert r.status_code == 422, r.text

    async def test_user_address_still_accepts_all_47_prefectures(self, client: AsyncClient):
        """住所（居住地）は47都道府県のまま。対応エリア制限は訪問先だけに掛ける。"""
        token, _ = await _signup_user(client, "area_address@example.com")
        r = await client.put(
            "/api/v1/users/me/address",
            json={
                "postal_code": "0600001",
                "prefecture": "北海道",
                "city": "札幌市中央区",
                "address_line1": "北1条西1-1",
            },
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text


# ──────────────── V-M4: 減額申請の回数・上限 ────────────────


class TestReductionCountContract:
    def test_detail_exposes_count_and_limit(self):
        """契約: reduction_request_count（既定0）と reduction_request_limit（=2）。"""
        out = TransactionDetailOut(
            id=uuid.uuid4(),
            case_id=uuid.uuid4(),
            bid_id=uuid.uuid4(),
            status="pending",
            initial_amount=10000,
            final_amount=None,
            fee_amount=0,
            visit_date=None,
            created_at=datetime.now(timezone.utc),
        )
        assert out.reduction_request_count == 0
        assert out.reduction_request_limit == 2

    def test_limit_shares_the_single_source_with_the_409_gate(self):
        """409 を出す側（reductions.py）と同一定数であること（ズレ防止）。"""
        from app.api.v1.endpoints import reductions

        assert reductions._MAX_REDUCTION_REQUESTS == MAX_REDUCTION_REQUESTS_PER_TRANSACTION == 2


# ──────────────── O-M1〜M3: 本人確認一覧 ────────────────


async def _submit_identity(client: AsyncClient, token: str) -> str:
    """生年月日を登録して身分証（パスポート・表面のみ）を提出し document_id を返す。"""
    today = datetime.now(_JST).date()
    r = await client.put(
        "/api/v1/users/me/profile",
        json={
            "family_name": "田中",
            "given_name": "太郎",
            "birth_date": date(today.year - 30, today.month, today.day).isoformat(),
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/v1/users/me/identity-documents",
        files={
            "doc_type": (None, "passport"),
            "front": ("front.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 256, "image/png"),
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()["document_id"]


class TestAdminIdentityDocumentList:
    async def test_items_total_counts_and_q_filter(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session, "r10_id_admin1@katadzuke.jp")
        token_a, _ = await _signup_user(client, "ident_alpha@example.com", name="山田 花子")
        token_b, _ = await _signup_user(client, "ident_bravo@example.com")
        doc_a = await _submit_identity(client, token_a)
        doc_b = await _submit_identity(client, token_b)

        r = await client.get("/api/v1/admin/identity-documents", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert body["counts"] == {"pending": 2, "approved": 0, "rejected": 0}
        assert {d["id"] for d in body["items"]} == {doc_a, doc_b}

        # q: 依頼者メールの部分一致
        r = await client.get(
            "/api/v1/admin/identity-documents",
            params={"q": "alpha"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert [d["id"] for d in body["items"]] == [doc_a]
        # counts は絞込に関わらない全件内訳（バッジ用の契約）
        assert body["counts"]["pending"] == 2

        # q: 氏名の部分一致（メールには含まれない語で引けること＝name 側の or 節の検証。
        # 表示名は本人確認の提出前に PUT /users/me/profile が姓名から確定させる）。
        r = await client.get(
            "/api/v1/admin/identity-documents",
            params={"q": "田中"},
            headers=_auth(admin_token),
        )
        assert {d["id"] for d in r.json()["items"]} == {doc_a, doc_b}

        # q: ilike のワイルドカードはエスケープされ、全件ヒットにならない
        r = await client.get(
            "/api/v1/admin/identity-documents",
            params={"q": "%"},
            headers=_auth(admin_token),
        )
        assert r.json()["total"] == 0

    async def test_counts_reflect_review_result(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session, "r10_id_admin2@katadzuke.jp")
        token, _ = await _signup_user(client, "ident_reviewed@example.com")
        document_id = await _submit_identity(client, token)

        r = await client.patch(
            f"/api/v1/admin/identity-documents/{document_id}/approve",
            headers=_auth(admin_token),
        )
        assert r.status_code == 200, r.text

        r = await client.get(
            "/api/v1/admin/identity-documents",
            params={"status": "all"},
            headers=_auth(admin_token),
        )
        assert r.json()["counts"] == {"pending": 0, "approved": 1, "rejected": 0}
        # 既定（status=pending）では 0 件・total も 0
        r = await client.get("/api/v1/admin/identity-documents", headers=_auth(admin_token))
        assert r.json()["total"] == 0
        assert r.json()["items"] == []

    async def test_order_is_deterministic_with_id_tie_breaker(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """submitted_at が完全に同時刻でも、id 降順で決定的に並ぶ（O-M2）。"""
        admin_token = await _make_admin(client, db_session, "r10_id_admin3@katadzuke.jp")
        token, user_id = await _signup_user(client, "ident_tie@example.com")
        same_moment = datetime.now(timezone.utc)
        ids = sorted(uuid.uuid4() for _ in range(3))
        for document_id in ids:
            db_session.add(
                UserIdentityDocument(
                    id=document_id,
                    user_id=uuid.UUID(user_id),
                    doc_type="passport",
                    front_image_data=b"\x89PNG\r\n\x1a\n",
                    front_image_content_type="image/png",
                    status="pending",
                    submitted_at=same_moment,
                )
            )
        await db_session.commit()

        first = await client.get(
            "/api/v1/admin/identity-documents",
            params={"limit": 2, "offset": 0},
            headers=_auth(admin_token),
        )
        second = await client.get(
            "/api/v1/admin/identity-documents",
            params={"limit": 2, "offset": 2},
            headers=_auth(admin_token),
        )
        page1 = [d["id"] for d in first.json()["items"]]
        page2 = [d["id"] for d in second.json()["items"]]
        assert page1 == [str(i) for i in reversed(ids)][:2]
        assert page2 == [str(i) for i in reversed(ids)][2:]
        # ページ跨ぎで重複・欠落が無いこと（tie-breaker が無いと崩れる）
        assert len(set(page1) | set(page2)) == 3


class TestIdentitySubmitAdminAlert:
    async def test_submit_notifies_admin_emails(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """提出時に ADMIN_EMAILS 宛の通知が1宛先1通ずつ送られる（O-M1）。"""
        monkeypatch.setattr(
            get_settings(), "admin_emails_raw", "ops1@example.com,ops2@example.com"
        )
        token, _ = await _signup_user(client, "ident_notify@example.com")
        with patch(
            "app.api.v1.endpoints.user_identity.notify.send_identity_submitted_admin_alert",
            new_callable=AsyncMock,
        ) as send_mock:
            await _submit_identity(client, token)
        assert [c.args[0] for c in send_mock.call_args_list] == [
            "ops1@example.com",
            "ops2@example.com",
        ]

    async def test_mail_body_contains_no_pii(self):
        """本人確認という文脈で、通知メールに提出者の PII を載せない。"""
        from app.services import notify

        with patch("app.services.notify._send", new_callable=AsyncMock) as send_mock:
            send_mock.return_value = True
            await notify.send_identity_submitted_admin_alert("ops@example.com")
        _, subject, html_body = send_mock.call_args.args
        assert "本人確認" in subject
        assert "@example" not in html_body.replace("ops@example.com", "")
        assert "/admin/identity-documents" in html_body


# ──────────────── O-M4: 業者 counts の pending_with_license ────────────────


class TestOperatorCountsPendingWithLicense:
    async def test_counts_include_pending_with_license(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.db.models.operator import Operator

        admin_token = await _make_admin(client, db_session, "r10_op_admin@katadzuke.jp")
        # 許可証未提出の pending / 提出済みの pending / active の3社
        db_session.add_all(
            [
                Operator(
                    company_name="未提出商店",
                    contact_email="pending_nolic@example.com",
                    password_hash=hash_password("operatorpass1"),
                    license_number="1234567890001",
                    vendor_status="pending",
                ),
                Operator(
                    company_name="提出済商店",
                    contact_email="pending_lic@example.com",
                    password_hash=hash_password("operatorpass1"),
                    license_number="1234567890002",
                    vendor_status="pending",
                    license_image_uploaded_at=datetime.now(timezone.utc),
                ),
                Operator(
                    company_name="承認済商店",
                    contact_email="active_lic@example.com",
                    password_hash=hash_password("operatorpass1"),
                    license_number="1234567890003",
                    vendor_status="active",
                    license_image_uploaded_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await db_session.commit()

        r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        counts = r.json()["counts"]
        assert counts["pending"] == 2
        # active の許可証提出済みは含めない（「いま承認できる」件数のみ）
        assert counts["pending_with_license"] == 1

    async def test_suspended_pending_excluded_from_pending_with_license(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """r10-review M6: 停止中は承認操作自体が無意味なため除外する。"""
        from app.db.models.operator import Operator

        admin_token = await _make_admin(client, db_session, "r10_op_admin_m6@katadzuke.jp")
        db_session.add_all(
            [
                Operator(
                    company_name="提出済停止中商店",
                    contact_email="pending_lic_suspended@example.com",
                    password_hash=hash_password("operatorpass1"),
                    license_number="1234567890004",
                    vendor_status="pending",
                    license_image_uploaded_at=datetime.now(timezone.utc),
                    is_suspended=True,
                ),
                Operator(
                    company_name="提出済商店2",
                    contact_email="pending_lic2@example.com",
                    password_hash=hash_password("operatorpass1"),
                    license_number="1234567890005",
                    vendor_status="pending",
                    license_image_uploaded_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await db_session.commit()

        r = await client.get("/api/v1/admin/operators", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        counts = r.json()["counts"]
        assert counts["pending"] == 2
        assert counts["pending_with_license"] == 1


# ──────────────── O-M5: 依頼者一覧の絞り込み ────────────────


class TestAdminUserListFilters:
    async def test_suspended_and_include_deleted_filters(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_token = await _make_admin(client, db_session, "r10_user_admin@katadzuke.jp")
        _, active_id = await _signup_user(client, "r10_active_user@example.com")
        _, suspended_id = await _signup_user(client, "r10_suspended_user@example.com")
        r = await client.patch(
            f"/api/v1/admin/users/{suspended_id}/suspend",
            json={"suspended": True, "reason": "調査中"},
            headers=_auth(admin_token),
        )
        assert r.status_code == 200, r.text

        # suspended=true: 停止中のみ
        r = await client.get(
            "/api/v1/admin/users", params={"suspended": True}, headers=_auth(admin_token)
        )
        assert r.status_code == 200
        assert [u["id"] for u in r.json()["items"]] == [suspended_id]
        assert r.json()["total"] == 1

        # suspended=false: 停止中以外（admin 自身を含む）
        r = await client.get(
            "/api/v1/admin/users", params={"suspended": False}, headers=_auth(admin_token)
        )
        returned = {u["id"] for u in r.json()["items"]}
        assert active_id in returned
        assert suspended_id not in returned

        # 省略時は絞り込まない
        r = await client.get("/api/v1/admin/users", headers=_auth(admin_token))
        assert {active_id, suspended_id} <= {u["id"] for u in r.json()["items"]}

        # include_deleted: 退会済みは既定で除外・明示指定で復活する
        target = await db_session.get(User, uuid.UUID(active_id))
        target.deleted_at = datetime.now(timezone.utc)
        await db_session.commit()
        r = await client.get("/api/v1/admin/users", headers=_auth(admin_token))
        assert active_id not in {u["id"] for u in r.json()["items"]}
        r = await client.get(
            "/api/v1/admin/users",
            params={"include_deleted": True},
            headers=_auth(admin_token),
        )
        assert active_id in {u["id"] for u in r.json()["items"]}
        # r10 fix: deleted_at が応答に含まれ、web 側が退会済み行を判別できる。
        by_id = {u["id"]: u for u in r.json()["items"]}
        assert by_id[active_id]["deleted_at"] is not None
        assert by_id[suspended_id]["deleted_at"] is None


# ──────────────── r10 fix: 成約一覧の visit_time_slot ────────────────


async def _verified_operator(
    client: AsyncClient,
    admin_token: str,
    email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
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
    op_id = data["operator"]["id"]
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    return data["access_token"], op_id


class TestTransactionListVisitTimeSlot:
    async def test_list_exposes_visit_time_slot_for_user_and_operator(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """一覧（依頼者・業者とも）が詳細と同じ visit_time_slot 契約を持つ（r10 fix）。"""
        admin_token = await _make_admin(client, db_session, "r10_visit_admin@katadzuke.jp")
        user_token, _ = await _signup_user(client, "r10_visit_user@example.com")
        op_token, _ = await _verified_operator(client, admin_token, "r10_visit_op@example.com")

        r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(user_token))
        assert r.status_code == 201, r.text
        case_id = r.json()["id"]
        r = await client.post(
            f"/api/v1/cases/{case_id}/bids", json={"amount": 30000}, headers=_auth(op_token)
        )
        assert r.status_code == 201, r.text
        bid_id = r.json()["id"]
        r = await client.post(
            f"/api/v1/cases/{case_id}/bids/{bid_id}/select", headers=_auth(user_token)
        )
        assert r.status_code == 201, r.text
        txn_id = r.json()["id"]

        # 日程確定前は None（詳細と同じ既定値）。
        for token in (user_token, op_token):
            r = await client.get("/api/v1/transactions", headers=_auth(token))
            assert r.status_code == 200, r.text
            item = next(t for t in r.json() if t["id"] == txn_id)
            assert item["visit_time_slot"] is None

        visit_date = (date.today() + timedelta(days=7)).isoformat()
        r = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/confirm",
            json={"visit_date": visit_date, "visit_time_slot": "10:00-12:00"},
            headers=_auth(user_token),
        )
        assert r.status_code == 200, r.text

        for token in (user_token, op_token):
            r = await client.get("/api/v1/transactions", headers=_auth(token))
            assert r.status_code == 200, r.text
            item = next(t for t in r.json() if t["id"] == txn_id)
            assert item["visit_time_slot"] == "10:00-12:00"


# ──────────────── O-M6: お問い合わせの受信台帳 ────────────────


def _contact_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "問合 太郎",
        "email": "asker@example.com",
        "category": "trouble",
        "message": "アカウントの停止解除をお願いしたく連絡しました。",
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _reset_contact_process_cap():
    """contact.py のプロセス内キャップはモジュールグローバルで共有されるためリセット。"""
    from app.api.v1.endpoints import contact as contact_endpoint

    contact_endpoint._recent_notification_timestamps.clear()
    contact_endpoint._alert_threshold_notified = False
    yield
    contact_endpoint._recent_notification_timestamps.clear()
    contact_endpoint._alert_threshold_notified = False


class TestContactPersistence:
    async def test_contact_is_persisted_even_without_admin_emails(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """ADMIN_EMAILS 未設定でも DB には残る（従来は痕跡ゼロで消えていた）。"""
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "")
        r = await client.post("/api/v1/contact", json=_contact_payload())
        assert r.status_code == 202, r.text
        rows = (await db_session.scalars(select(ContactMessage))).all()
        assert len(rows) == 1
        assert rows[0].email == "asker@example.com"
        assert rows[0].category == "trouble"
        assert rows[0].handled_at is None
        assert rows[0].handled_by_admin_id is None

    async def test_existing_mail_delivery_is_preserved(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "ops@example.com")
        with patch(
            "app.api.v1.endpoints.contact.notify.send_contact_received",
            new_callable=AsyncMock,
        ) as send_mock:
            r = await client.post("/api/v1/contact", json=_contact_payload())
        assert r.status_code == 202
        assert send_mock.await_count == 1
        assert (await db_session.scalars(select(ContactMessage))).all()

    async def test_admin_list_filter_and_handle(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "")
        admin_token = await _make_admin(client, db_session, "r10_contact_admin@katadzuke.jp")
        for i in range(3):
            r = await client.post(
                "/api/v1/contact",
                json=_contact_payload(email=f"asker{i}@example.com"),
            )
            assert r.status_code == 202, r.text

        r = await client.get("/api/v1/admin/contacts", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        assert all(item["handled_at"] is None for item in body["items"])
        target_id = body["items"][0]["id"]

        r = await client.patch(
            f"/api/v1/admin/contacts/{target_id}/handle", headers=_auth(admin_token)
        )
        assert r.status_code == 200, r.text
        handled_at = r.json()["handled_at"]
        assert r.json()["id"] == target_id
        assert handled_at is not None

        # 再実行は冪等（最初の対応時刻を上書きしない）
        r = await client.patch(
            f"/api/v1/admin/contacts/{target_id}/handle", headers=_auth(admin_token)
        )
        assert r.status_code == 200
        assert r.json()["handled_at"] == handled_at

        r = await client.get(
            "/api/v1/admin/contacts", params={"handled": False}, headers=_auth(admin_token)
        )
        assert r.json()["total"] == 2
        assert target_id not in {i["id"] for i in r.json()["items"]}

        r = await client.get(
            "/api/v1/admin/contacts", params={"handled": True}, headers=_auth(admin_token)
        )
        assert [i["id"] for i in r.json()["items"]] == [target_id]

        r = await client.patch(
            f"/api/v1/admin/contacts/{uuid.uuid4()}/handle", headers=_auth(admin_token)
        )
        assert r.status_code == 404

    async def test_admin_contacts_require_admin(self, client: AsyncClient):
        token, _ = await _signup_user(client, "r10_contact_notadmin@example.com")
        r = await client.get("/api/v1/admin/contacts", headers=_auth(token))
        assert r.status_code == 403
        r = await client.patch(
            f"/api/v1/admin/contacts/{uuid.uuid4()}/handle", headers=_auth(token)
        )
        assert r.status_code == 403
        r = await client.get("/api/v1/admin/contacts")
        assert r.status_code == 401


# ──────────────── r10-review M1: 問い合わせ削除API・退会時の匿名化 ────────────────


class TestContactDeletionAndWithdrawalAnonymization:
    async def test_admin_delete_contact_removes_row(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """privacy:110 の削除請求に応える最小実装（物理削除・204・監査ログ）。"""
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "")
        admin_token = await _make_admin(client, db_session, "r10_contact_del_admin@katadzuke.jp")
        r = await client.post("/api/v1/contact", json=_contact_payload())
        assert r.status_code == 202, r.text
        contact_id = (await db_session.scalars(select(ContactMessage))).one().id

        r = await client.delete(
            f"/api/v1/admin/contacts/{contact_id}", headers=_auth(admin_token)
        )
        assert r.status_code == 204, r.text
        assert (await db_session.scalars(select(ContactMessage))).all() == []

        # 再削除は 404（既に存在しない）
        r = await client.delete(
            f"/api/v1/admin/contacts/{contact_id}", headers=_auth(admin_token)
        )
        assert r.status_code == 404

    async def test_admin_delete_contact_requires_admin(self, client: AsyncClient):
        token, _ = await _signup_user(client, "r10_contact_del_notadmin@example.com")
        r = await client.delete(f"/api/v1/admin/contacts/{uuid.uuid4()}", headers=_auth(token))
        assert r.status_code == 403
        r = await client.delete(f"/api/v1/admin/contacts/{uuid.uuid4()}")
        assert r.status_code == 401

    async def test_withdrawal_anonymizes_matching_contact_messages(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        """退会時、同一メールの問い合わせは name/email/message を匿名化する。"""
        monkeypatch.setattr(get_settings(), "admin_emails_raw", "")
        email = "r10_withdraw_contact@example.com"
        token, user_id = await _signup_user(client, email)
        r = await client.post(
            "/api/v1/contact", json=_contact_payload(email=email, name="退会予定 花子")
        )
        assert r.status_code == 202, r.text

        r = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"password": "password123", "confirm": True},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text

        contact = (await db_session.scalars(select(ContactMessage))).one()
        assert contact.email == f"deleted-{user_id}@deleted.katazuke.internal"
        assert contact.name == f"deleted-{user_id}"
        assert contact.message == "[削除済み]"


# ──────────────── O-H3: /readyz の config にアラート経路 ────────────────


class TestConfigReadinessAlerts:
    def test_alerts_flags_follow_alerts_module_settings(self, monkeypatch):
        from app.main import _config_readiness

        settings = get_settings()
        monkeypatch.setattr(settings, "alert_line_channel_access_token", "")
        monkeypatch.setattr(settings, "alert_line_user_ids_raw", "")
        monkeypatch.setattr(settings, "alert_webhook_url", "")
        flags = _config_readiness(settings)
        assert flags["alerts_line"] is False
        assert flags["alerts_webhook"] is False

        # _send_line はトークンと宛先の両方が必要（片方だけは False）
        monkeypatch.setattr(settings, "alert_line_channel_access_token", "token")
        assert _config_readiness(settings)["alerts_line"] is False
        monkeypatch.setattr(settings, "alert_line_user_ids_raw", "U0001")
        assert _config_readiness(settings)["alerts_line"] is True

        monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example/x")
        assert _config_readiness(settings)["alerts_webhook"] is True

    async def test_readyz_degraded_config_excludes_alerts_webhook(self, db_engine, monkeypatch):
        """alerts_webhook は config に bool で出るが degraded_config には出ない（r10 fix）。

        LINE/メールという代替経路があるため、Webhook 未設定単体は運用上の劣化ではない。
        """
        import app.main as main_module

        monkeypatch.setattr(main_module, "engine", db_engine)
        # テスト DB は create_all で alembic_version を持たないため、期待ヘッドの解決を
        # None に固定してテーブル有無ベースの判定へ落とす（Linux CI では alembic.ini が
        # 読めて 0032 が返り、alembic_version=None と不一致で 503 になっていた）。
        from alembic.script import ScriptDirectory as _SD
        monkeypatch.setattr(_SD, "get_current_head", lambda self: None)
        settings = get_settings()
        monkeypatch.setattr(settings, "alert_webhook_url", "")
        monkeypatch.setattr(settings, "alert_line_channel_access_token", "")
        monkeypatch.setattr(settings, "alert_line_user_ids_raw", "")

        app = main_module.create_app(settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/readyz")
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["config"]["alerts_webhook"] is False
        assert "alerts_webhook" not in payload["degraded_config"]
        # alerts_line は代替経路の議論対象外のため、未設定なら引き続き degraded。
        assert payload["config"]["alerts_line"] is False
        assert "alerts_line" in payload["degraded_config"]


# ──────────────── ADD-H1 / O-H2: 外形監視スクリプト ────────────────


def _load_uptime_check():
    """scripts/uptime_check.py を単体モジュールとして読み込む（パッケージ外のため）。"""
    path = Path(__file__).resolve().parents[2] / "scripts" / "uptime_check.py"
    spec = importlib.util.spec_from_file_location("uptime_check_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestUptimeCheckScript:
    @pytest.fixture(autouse=True)
    def _isolated_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        yield

    def _result(self, module, name, ok, degraded=None):
        return module.CheckResult(name, ok, "detail", 10, list(degraded or []))

    def test_returns_1_when_all_notification_channels_fail(self, monkeypatch):
        """障害を検知したのに1通も送れなかった実行は exit 1（ADD-H1）。"""
        module = _load_uptime_check()
        monkeypatch.setattr(module, "check_health", lambda: self._result(module, "h", False))
        monkeypatch.setattr(module, "check_readyz", lambda: self._result(module, "r", True))
        monkeypatch.setattr(module, "check_frontend", lambda: self._result(module, "f", True))
        monkeypatch.setattr(module, "notify", lambda subject, text: [])
        assert module.main() == 1

    def test_returns_0_when_at_least_one_channel_succeeds(self, monkeypatch):
        module = _load_uptime_check()
        monkeypatch.setattr(module, "check_health", lambda: self._result(module, "h", False))
        monkeypatch.setattr(module, "check_readyz", lambda: self._result(module, "r", True))
        monkeypatch.setattr(module, "check_frontend", lambda: self._result(module, "f", True))
        monkeypatch.setattr(module, "notify", lambda subject, text: ["line"])
        assert module.main() == 0

    def test_returns_0_when_no_notification_was_needed(self, monkeypatch):
        """正常時は notify を1回も呼ばないため、通知全滅とは区別される。"""
        module = _load_uptime_check()
        for name in ("check_health", "check_readyz", "check_frontend"):
            monkeypatch.setattr(module, name, lambda: self._result(module, "x", True))
        calls: list[str] = []

        def _spy(subject, text):
            calls.append(subject)
            return []

        monkeypatch.setattr(module, "notify", _spy)
        assert module.main() == 0
        assert calls == []

    def test_degraded_config_notifies_only_on_transition(self, monkeypatch):
        """degraded_config は「変化した時だけ」通知する（O-H2）。"""
        module = _load_uptime_check()
        monkeypatch.setattr(module, "check_health", lambda: self._result(module, "h", True))
        monkeypatch.setattr(module, "check_frontend", lambda: self._result(module, "f", True))
        subjects: list[str] = []

        def _spy(subject, text):
            subjects.append(subject)
            return ["webhook"]

        monkeypatch.setattr(module, "notify", _spy)

        monkeypatch.setattr(
            module, "check_readyz", lambda: self._result(module, "r", True, ["brevo"])
        )
        assert module.main() == 0
        assert len(subjects) == 1 and "本番必須設定の未充足" in subjects[0]

        # 同じ内容が続く間は再送しない
        assert module.main() == 0
        assert len(subjects) == 1

        # 解消したら1回だけ解消通知
        monkeypatch.setattr(
            module, "check_readyz", lambda: self._result(module, "r", True, [])
        )
        assert module.main() == 0
        assert len(subjects) == 2 and "解消" in subjects[1]
        assert module.main() == 0
        assert len(subjects) == 2

    def test_degraded_config_transition_skipped_when_readyz_unreachable(self, monkeypatch):
        """/readyz 到達不能時に「解消した」と誤検知しない。"""
        module = _load_uptime_check()
        monkeypatch.setattr(module, "check_health", lambda: self._result(module, "h", True))
        monkeypatch.setattr(module, "check_frontend", lambda: self._result(module, "f", True))
        subjects: list[str] = []
        monkeypatch.setattr(
            module, "notify", lambda subject, text: (subjects.append(subject), ["line"])[1]
        )
        monkeypatch.setattr(
            module, "check_readyz", lambda: self._result(module, "r", True, ["brevo"])
        )
        assert module.main() == 0
        assert len(subjects) == 1

        # 到達不能（ok=False・degraded_config は取得できない）
        monkeypatch.setattr(
            module, "check_readyz", lambda: self._result(module, "r", False, [])
        )
        module.main()
        # 障害検知の通知は出るが、「解消しました」は出ない
        assert not any("解消" in s for s in subjects)
