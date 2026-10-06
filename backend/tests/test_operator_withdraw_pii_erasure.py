"""業者退会時の個人情報消去（プライバシーポリシー第8条）の回帰テスト。

固定する契約:
- 退会で許可証画像・許可番号・会社名・事前申込（代表者・所在地・電話・口座・備考）・
  招待のメール・プロフィールの営業情報が消える（行は残る）。
- 取引・メッセージ・入札履歴は残り、依頼者の取引画面には「退会済み業者」と出る。
- 進行中の取引があれば退会は 409 で、何も消えない。
- 消去は冪等（直接再実行しても壊れない）。
- 事前申込・招待は本人に紐づくもの（operator_id・本人が使った招待コード）だけを消す。
  同じメールアドレスの他人の申込・同じメール宛ての限定招待は消さない（security review High）。
- 退会後、他の業者・依頼者の画面（公開プロフィール・一覧・運営の申込一覧）に元の個人情報が出ない。
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.crypto import encrypt_json
from app.db.models.bid import Bid
from app.db.models.invite import Invite
from app.db.models.operator import Operator
from app.db.models.operator_application import OperatorApplication
from app.db.models.operator_profile import OperatorProfile
from app.db.models.transaction import Transaction
from app.db.session import get_session
from app.services.operator_pii_erasure import (
    DELETED_OPERATOR_DISPLAY_NAME,
    erase_operator_personal_data,
)
from tests.test_deleted_operator_token_revocation import (
    _OP_PASSWORD,
    _auth,
    _case_payload,
    _create_completed_transaction,
    _make_admin,
    _signup_user,
    _verified_operator,
)

_OP_EMAIL = "erase_op@example.com"
_COMPANY = "山田太郎片付け店"
_LICENSE_NO = "第987654321098号"
_SECRETS = ["山田太郎", "090-1234-5678", "東京都世田谷区桜丘9-9-9", _LICENSE_NO, _OP_EMAIL]


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _seed_application(db_session: AsyncSession, op_id: str) -> uuid.UUID:
    application = OperatorApplication(
        status="approved",
        operator_id=uuid.UUID(op_id),  # 本人に紐づく申込（招待コードでの登録時に書き戻される）
        company_name=_COMPANY,
        representative_name="山田太郎",
        registered_address="東京都世田谷区桜丘9-9-9",
        contact_name="山田太郎",
        contact_email=_OP_EMAIL,
        contact_phone="090-1234-5678",
        license_number=_LICENSE_NO,
        invoice_number="T1234567890123",
        message="自由記述の備考",
        categories="遺品整理",
        service_area="tokyo",
        client_ip="203.0.113.7",
        bank_account_enc=encrypt_json(
            {
                "bank_name": "A銀行",
                "branch_name": "B支店",
                "account_type": "ordinary",
                "account_number": "1234567",
                "account_holder": "ヤマダタロウ",
            }
        ),
    )
    db_session.add(application)
    db_session.add(Invite(code="ERASE-INV-1", email=_OP_EMAIL, operator_id=uuid.UUID(op_id)))
    await db_session.commit()
    return application.id


async def _prepare(client: AsyncClient, db_session: AsyncSession):
    admin = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(client, admin, _OP_EMAIL, company=_COMPANY)
    op = await db_session.get(Operator, uuid.UUID(op_id))
    op.license_number = _LICENSE_NO
    db_session.add(
        OperatorProfile(
            operator_id=op.id,
            areas=["東京都"],
            categories=["遺品整理"],
            business_hours="9-18時 090-1234-5678",
            intro_message="山田です",
            staff_count=3,
        )
    )
    await db_session.commit()
    app_id = await _seed_application(db_session, op_id)
    return admin, op_token, op_id, app_id


async def _withdraw(client: AsyncClient, op_token: str):
    return await client.request(
        "DELETE", "/api/v1/operator/me", json={"password": _OP_PASSWORD}, headers=_auth(op_token)
    )


async def _license_blob(db_session: AsyncSession, op_id: str):
    return (
        await db_session.execute(
            select(Operator.license_image_data).where(Operator.id == uuid.UUID(op_id))
        )
    ).scalar_one()


async def test_withdraw_erases_pii_and_keeps_transaction_records(
    client: AsyncClient, db_session: AsyncSession
):
    admin, op_token, op_id, app_id = await _prepare(client, db_session)
    user_token, _ = await _signup_user(client)
    _, txn_id = await _create_completed_transaction(client, user_token, op_token)
    assert await _license_blob(db_session, op_id) is not None

    bids_before = await db_session.scalar(select(func.count()).select_from(Bid))
    r = await _withdraw(client, op_token)
    assert r.status_code == 204, r.text
    db_session.expire_all()

    op = await db_session.get(Operator, uuid.UUID(op_id))
    assert op.deleted_at is not None
    assert op.company_name == DELETED_OPERATOR_DISPLAY_NAME
    assert op.license_number is None
    assert op.license_image_content_type is None
    assert op.license_image_uploaded_at is None
    assert await _license_blob(db_session, op_id) is None
    assert op.line_user_id is None and op.password_hash is None

    application = await db_session.get(OperatorApplication, app_id)
    assert application is not None  # 行は残る
    for column in (
        "representative_name",
        "registered_address",
        "contact_name",
        "contact_email",
        "contact_phone",
        "license_number",
    ):
        assert getattr(application, column) == "", column
    assert application.company_name == DELETED_OPERATOR_DISPLAY_NAME
    assert application.bank_account_enc is None
    assert application.message is None and application.invoice_number is None
    assert application.client_ip is None
    invite = (
        await db_session.execute(select(Invite).where(Invite.code == "ERASE-INV-1"))
    ).scalar_one()
    assert invite.email is None

    profile = await db_session.get(OperatorProfile, uuid.UUID(op_id))
    assert profile.areas is None and profile.categories is None
    assert profile.business_hours is None and profile.intro_message is None
    assert profile.staff_count is None and profile.is_public is False

    # 取引・入札は残る。依頼者の取引画面は「退会済み業者」表示で個人情報を含まない。
    assert await db_session.scalar(select(func.count()).select_from(Bid)) == bids_before
    assert await db_session.get(Transaction, uuid.UUID(txn_id)) is not None
    r = await client.get("/api/v1/transactions", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"] if isinstance(body, dict) else body
    row = next(t for t in items if t["id"] == txn_id)
    assert row["company_name"] == DELETED_OPERATOR_DISPLAY_NAME
    for secret in _SECRETS:
        assert secret not in r.text


async def test_withdraw_hides_pii_from_other_screens(
    client: AsyncClient, db_session: AsyncSession
):
    admin, op_token, op_id, _ = await _prepare(client, db_session)
    other_token, _ = await _verified_operator(client, admin, "erase_other@example.com", "別会社")
    user_token, _ = await _signup_user(client)
    assert (await _withdraw(client, op_token)).status_code == 204

    paths = [f"/api/v1/vendors/{op_id}", "/api/v1/vendors"]
    for token in (user_token, other_token):
        for path in paths:
            r = await client.get(path, headers=_auth(token))
            assert r.status_code in (200, 404), (path, r.text)
            for secret in _SECRETS + ["山田です"]:
                assert secret not in r.text, (path, secret)
    r = await client.get("/api/v1/admin/operator-applications", headers=_auth(admin))
    assert r.status_code == 200, r.text
    for secret in ["山田太郎", "090-1234-5678", "桜丘9-9-9", _LICENSE_NO]:
        assert secret not in r.text


async def test_withdraw_blocked_by_active_transaction_erases_nothing(
    client: AsyncClient, db_session: AsyncSession
):
    admin, op_token, op_id, app_id = await _prepare(client, db_session)
    user_token, _ = await _signup_user(client)
    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(user_token))
    case_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids", json={"amount": 30000}, headers=_auth(op_token)
    )
    bid_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid_id}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text

    r = await _withdraw(client, op_token)
    assert r.status_code == 409, r.text
    db_session.expire_all()
    op = await db_session.get(Operator, uuid.UUID(op_id))
    assert op.deleted_at is None and op.company_name == _COMPANY
    assert op.license_number == _LICENSE_NO
    assert await _license_blob(db_session, op_id) is not None
    application = await db_session.get(OperatorApplication, app_id)
    assert application.representative_name == "山田太郎"
    assert application.bank_account_enc is not None


async def test_erasure_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    admin, op_token, op_id, app_id = await _prepare(client, db_session)
    assert (await _withdraw(client, op_token)).status_code == 204
    # 退会後の旧トークンは 401（エラー応答で拒否されるだけで状態は変わらない）。
    assert (await _withdraw(client, op_token)).status_code == 401

    op = await db_session.get(Operator, uuid.UUID(op_id))
    # 墓標化済みのメールで直接再実行しても例外にならず、状態が変わらない。
    await erase_operator_personal_data(db_session, op, op.invite_code)
    await erase_operator_personal_data(db_session, op, op.invite_code)
    await db_session.commit()
    db_session.expire_all()
    application = await db_session.get(OperatorApplication, app_id)
    assert application.contact_phone == "" and application.bank_account_enc is None
    op = await db_session.get(Operator, uuid.UUID(op_id))
    assert op.company_name == DELETED_OPERATOR_DISPLAY_NAME


async def test_admin_forced_deletion_also_erases(client: AsyncClient, db_session: AsyncSession):
    admin, op_token, op_id, app_id = await _prepare(client, db_session)
    r = await client.delete(f"/api/v1/admin/operators/{op_id}", headers=_auth(admin))
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert await _license_blob(db_session, op_id) is None
    application = await db_session.get(OperatorApplication, app_id)
    assert application.bank_account_enc is None and application.representative_name == ""


def _victim_application(**overrides) -> OperatorApplication:
    """業者本人とは無関係な、同じメールアドレスでの事前申込（他人のもの）。"""
    values = dict(
        status="pending",
        company_name="別人の会社",
        representative_name="鈴木花子",
        registered_address="大阪府大阪市北区1-1-1",
        contact_name="鈴木花子",
        contact_email=_OP_EMAIL.upper(),
        contact_phone="080-9999-0000",
        license_number="第111122223333号",
        bank_account_enc=encrypt_json({"bank_name": "C銀行", "account_number": "7654321"}),
        client_ip="198.51.100.9",
    )
    values.update(overrides)
    return OperatorApplication(**values)


def _assert_victim_untouched(application: OperatorApplication) -> None:
    assert application.representative_name == "鈴木花子"
    assert application.contact_email == _OP_EMAIL.upper()
    assert application.contact_phone == "080-9999-0000"
    assert application.license_number == "第111122223333号"
    assert application.company_name == "別人の会社"
    assert application.bank_account_enc is not None
    assert application.client_ip == "198.51.100.9"


async def test_withdraw_keeps_other_persons_application_and_invite_with_same_email(
    client: AsyncClient, db_session: AsyncSession
):
    """他人の申込中メールアドレスで業者登録→退会しても、その他人の申込と招待は消えない。"""
    admin, op_token, op_id, own_app_id = await _prepare(client, db_session)
    user_token, _ = await _signup_user(client)
    _, txn_id = await _create_completed_transaction(client, user_token, op_token)

    victim_pending = _victim_application()
    # 承認済みで招待コード発行済み（まだ誰も登録していない）の他人の申込。
    victim_approved = _victim_application(status="approved", invite_code="VICTIM-INV-1")
    db_session.add_all([victim_pending, victim_approved])
    # 同じメール宛ての限定招待（未使用）。email が NULL になると誰でも使える招待になる。
    db_session.add(Invite(code="VICTIM-INV-1", email=_OP_EMAIL.upper()))
    db_session.add(Invite(code="VICTIM-INV-2", email=_OP_EMAIL))
    await db_session.commit()
    victim_ids = [victim_pending.id, victim_approved.id]

    assert (await _withdraw(client, op_token)).status_code == 204
    db_session.expire_all()

    for victim_id in victim_ids:
        _assert_victim_untouched(await db_session.get(OperatorApplication, victim_id))
    for code, email in (("VICTIM-INV-1", _OP_EMAIL.upper()), ("VICTIM-INV-2", _OP_EMAIL)):
        invite = (
            await db_session.execute(select(Invite).where(Invite.code == code))
        ).scalar_one()
        assert invite.email == email, code
        assert invite.used_at is None and invite.operator_id is None

    # 本人に紐づく申込・招待は消える。
    own_app = await db_session.get(OperatorApplication, own_app_id)
    assert own_app.representative_name == "" and own_app.bank_account_enc is None
    own_invite = (
        await db_session.execute(select(Invite).where(Invite.code == "ERASE-INV-1"))
    ).scalar_one()
    assert own_invite.email is None
    # 取引記録は残る。
    assert await db_session.get(Transaction, uuid.UUID(txn_id)) is not None

    # 冪等: 再実行しても他人の行は変わらず、本人の行も空のまま。
    op = await db_session.get(Operator, uuid.UUID(op_id))
    await erase_operator_personal_data(db_session, op, op.invite_code)
    await db_session.commit()
    db_session.expire_all()
    for victim_id in victim_ids:
        _assert_victim_untouched(await db_session.get(OperatorApplication, victim_id))
    own_app = await db_session.get(OperatorApplication, own_app_id)
    assert own_app.contact_phone == ""


async def test_withdraw_erases_application_linked_by_own_invite_code(
    client: AsyncClient, db_session: AsyncSession
):
    """本人が登録に使った招待コードに紐づく申込は、operator_id 未書き戻しでも消える。

    ただし同じコードでも別の業者に紐づいた申込は消さない。
    """
    admin, op_token, op_id, _ = await _prepare(client, db_session)
    other_token, other_id = await _verified_operator(
        client, admin, "erase_other2@example.com", "別会社2"
    )
    op = await db_session.get(Operator, uuid.UUID(op_id))
    op.invite_code = "OWN-INV-1"
    own_by_code = _victim_application(
        status="approved", invite_code="OWN-INV-1", contact_email="someone@example.com"
    )
    other_by_code = _victim_application(
        status="approved", invite_code="OWN-INV-1", operator_id=uuid.UUID(other_id)
    )
    db_session.add_all([own_by_code, other_by_code])
    db_session.add(
        Invite(code="OWN-INV-1", email="someone@example.com", operator_id=None)
    )
    await db_session.commit()
    own_id, other_app_id = own_by_code.id, other_by_code.id

    assert (await _withdraw(client, op_token)).status_code == 204
    db_session.expire_all()

    own = await db_session.get(OperatorApplication, own_id)
    assert own.representative_name == "" and own.contact_email == ""
    assert own.bank_account_enc is None
    _assert_victim_untouched(await db_session.get(OperatorApplication, other_app_id))
    invite = (
        await db_session.execute(select(Invite).where(Invite.code == "OWN-INV-1"))
    ).scalar_one()
    assert invite.email is None
