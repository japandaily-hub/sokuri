"""r12 導線監査で確定した backend 側の是正の統合テスト。

対象:
- 決定1: 未承認業者（vendor_status=pending / rejected）の案件閲覧を 403
         ``approval_required`` で止める（一覧・詳細・入札一覧・案件写真配信）。
         停止中は従来どおり ``account_suspended``。
- 決定2: 業者向け応答から他社の入札額・順位を落とす（``top_bid_amount`` 廃止・
         入札一覧は自社分のみ）。依頼者・運営は従来どおり全件見える。
- 決定3: リマインド定期処理（訪問日超過 / 入札ゼロ放置）の対象抽出と
         二重送信防止、``POST /admin/jobs/reminders`` の手動実行。

フィクスチャの作法は tests/test_r10_backend_fixes.py と同じ
（in-memory SQLite + ASGITransport をローカルに複製する）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import create_access_token, hash_password
from app.db.models.bid import Bid
from app.db.models.case import Case, CasePhoto
from app.db.models.operator import Operator
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.services import storage
from app.services.reminders import JST, REMINDER_LOOKBACK_DAYS, run_reminders


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


async def _make_user(
    db_session: AsyncSession, email: str, *, role: str = "user"
) -> tuple[User, str]:
    user = User(
        email=email, password_hash=hash_password("userpass123"), name="依頼者", role=role
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, create_access_token(user.id, "user", role)


async def _make_operator(
    db_session: AsyncSession,
    email: str,
    *,
    vendor_status: str = "active",
    company: str = "A社",
) -> tuple[Operator, str]:
    operator = Operator(
        company_name=company,
        contact_email=email,
        password_hash=hash_password("operatorpass1"),
        vendor_status=vendor_status,
    )
    db_session.add(operator)
    await db_session.commit()
    await db_session.refresh(operator)
    return operator, create_access_token(operator.id, "operator", "operator")


async def _make_case(
    db_session: AsyncSession,
    user: User,
    *,
    status: str = "open",
    created_at: datetime | None = None,
) -> Case:
    case = Case(
        user_id=user.id,
        purpose="遺品整理",
        status=status,
        prefecture="東京都",
        city="世田谷区",
        address_detail="桜丘1-2-3",
    )
    db_session.add(case)
    await db_session.commit()
    if created_at is not None:
        # server_default(now()) を上書きして「作成から N 日経過」を再現する。
        case.created_at = created_at
        await db_session.commit()
    await db_session.refresh(case)
    return case


# ──────────────────────── 決定1: 未承認業者の閲覧制限 ────────────────────────


@pytest.mark.parametrize("vendor_status", ["pending", "rejected"])
async def test_unapproved_operator_gets_403_on_case_endpoints(
    client: AsyncClient, db_session: AsyncSession, vendor_status: str
):
    """pending / rejected の業者は案件一覧・詳細・入札一覧のすべてで 403。"""
    user, _ = await _make_user(db_session, f"owner_{vendor_status}@example.com")
    case = await _make_case(db_session, user)
    _, op_token = await _make_operator(
        db_session, f"unapproved_{vendor_status}@example.com", vendor_status=vendor_status
    )

    for path in (
        "/api/v1/cases",
        f"/api/v1/cases/{case.id}",
        f"/api/v1/cases/{case.id}/bids",
    ):
        r = await client.get(path, headers=_auth(op_token))
        assert r.status_code == 403, f"{path}: {r.text}"
        assert r.json()["detail"] == {
            "code": "approval_required",
            "message": "運営の承認後に案件を閲覧できます。",
        }


async def test_active_operator_can_view_cases_and_suspended_keeps_account_suspended(
    client: AsyncClient, db_session: AsyncSession
):
    """承認済み（active）は 200。停止中は approval_required ではなく account_suspended。"""
    user, _ = await _make_user(db_session, "owner_active@example.com")
    case = await _make_case(db_session, user)
    operator, op_token = await _make_operator(db_session, "active_op@example.com")

    r = await client.get("/api/v1/cases", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert [c["id"] for c in r.json()] == [str(case.id)]
    r = await client.get(f"/api/v1/cases/{case.id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/cases/{case.id}/bids", headers=_auth(op_token))
    assert r.status_code == 200, r.text

    # 停止は「一度承認された業者が事後に止められた」状態で web の導線が異なるため
    # コードを分ける（承認前の approval_required に潰さない）。
    operator.is_suspended = True
    await db_session.commit()
    r = await client.get(f"/api/v1/cases/{case.id}", headers=_auth(op_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "account_suspended"


async def test_case_photo_delivery_blocks_unapproved_operator_token(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
):
    """案件写真の配信は、未承認業者トークン付きのリクエストだけを 403 にする。

    無認証（``<img>`` 経由）と承認済み業者は従来どおり配信される（capability URL の
    互換性を壊さないための多層防御という位置づけ）。
    """
    monkeypatch.setattr(storage, "_storage_root", lambda: tmp_path)
    user, _ = await _make_user(db_session, "photo_owner@example.com")
    case = await _make_case(db_session, user)
    storage_key = f"{uuid.uuid4().hex}.jpg"
    db_session.add(CasePhoto(case_id=case.id, storage_key=storage_key, sort_order=0))
    await db_session.commit()
    (tmp_path / storage_key).write_bytes(b"dummy-jpeg-bytes")

    _, pending_token = await _make_operator(
        db_session, "photo_pending@example.com", vendor_status="pending"
    )
    _, active_token = await _make_operator(db_session, "photo_active@example.com")

    r = await client.get(f"/api/v1/files/{storage_key}", headers=_auth(pending_token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "approval_required"

    assert (await client.get(f"/api/v1/files/{storage_key}")).status_code == 200
    r = await client.get(f"/api/v1/files/{storage_key}", headers=_auth(active_token))
    assert r.status_code == 200


# ──────────────────────── 決定2: 他社入札額の非開示 ────────────────────────


async def test_operator_bid_list_hides_other_operators_amount(
    client: AsyncClient, db_session: AsyncSession
):
    """業者向け入札一覧は自社入札のみ。他社の額は本文のどこにも現れない。"""
    user, user_token = await _make_user(db_session, "bidlist_owner@example.com")
    case = await _make_case(db_session, user, status="bidding")
    op1, op1_token = await _make_operator(db_session, "bidlist_op1@example.com", company="A社")
    op2, _ = await _make_operator(db_session, "bidlist_op2@example.com", company="B社")
    db_session.add_all(
        [
            Bid(case_id=case.id, operator_id=op1.id, amount=40000, status="pending"),
            Bid(case_id=case.id, operator_id=op2.id, amount=55000, status="pending"),
        ]
    )
    await db_session.commit()

    r = await client.get(f"/api/v1/cases/{case.id}/bids", headers=_auth(op1_token))
    assert r.status_code == 200, r.text
    assert [b["amount"] for b in r.json()] == [40000]
    assert "55000" not in r.text

    # 依頼者側は従来どおり全件（他社額も含む）見える
    r = await client.get(f"/api/v1/cases/{case.id}/bids", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    assert sorted(b["amount"] for b in r.json()) == [40000, 55000]


async def test_case_masked_out_has_no_top_bid_amount(
    client: AsyncClient, db_session: AsyncSession
):
    """業者向け案件詳細に順位・他社額の手がかり（top_bid_amount）を返さない。

    自社入札（my_bid）と件数（bid_count）は維持する。
    """
    user, _ = await _make_user(db_session, "masked_owner@example.com")
    case = await _make_case(db_session, user, status="bidding")
    op1, op1_token = await _make_operator(db_session, "masked_op1@example.com", company="A社")
    op2, _ = await _make_operator(db_session, "masked_op2@example.com", company="B社")
    db_session.add_all(
        [
            Bid(case_id=case.id, operator_id=op1.id, amount=40000, status="pending"),
            Bid(case_id=case.id, operator_id=op2.id, amount=99000, status="pending"),
        ]
    )
    await db_session.commit()

    r = await client.get(f"/api/v1/cases/{case.id}", headers=_auth(op1_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "top_bid_amount" not in body
    assert body["bid_count"] == 2
    assert body["my_bid"]["amount"] == 40000
    assert "99000" not in r.text


# ──────────────────────── 決定3: リマインド定期処理 ────────────────────────


async def _make_transaction(
    db_session: AsyncSession,
    case: Case,
    operator: Operator,
    *,
    visit_date: date,
    status: str,
) -> Transaction:
    bid = Bid(case_id=case.id, operator_id=operator.id, amount=30000, status="selected")
    db_session.add(bid)
    await db_session.commit()
    await db_session.refresh(bid)
    txn = Transaction(
        case_id=case.id,
        bid_id=bid.id,
        initial_amount=30000,
        fee_amount=0,
        status=status,
        visit_date=visit_date,
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)
    return txn


async def test_overdue_visit_reminder_selects_and_marks_once(db_session: AsyncSession):
    """訪問日超過の成約だけを拾い、依頼者・業者の双方へ1回だけ通知する。"""
    today = datetime.now(timezone.utc).date()
    user, _ = await _make_user(db_session, "overdue_owner@example.com")
    operator, _ = await _make_operator(db_session, "overdue_op@example.com")

    overdue_case = await _make_case(db_session, user, status="closed")
    overdue = await _make_transaction(
        db_session,
        overdue_case,
        operator,
        visit_date=today - timedelta(days=1),
        status="visiting",
    )
    # 対象外1: 訪問日が未来
    future_case = await _make_case(db_session, user, status="closed")
    future = await _make_transaction(
        db_session,
        future_case,
        operator,
        visit_date=today + timedelta(days=1),
        status="visiting",
    )
    # 対象外2: 既に完了（終端ステータス）
    done_case = await _make_case(db_session, user, status="closed")
    done = await _make_transaction(
        db_session,
        done_case,
        operator,
        visit_date=today - timedelta(days=5),
        status="completed",
    )

    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", new_callable=AsyncMock
    ) as dispatch:
        result = await run_reminders(db_session)

    assert result["overdue"] == 1
    # 依頼者宛・業者宛の2通（recipient_party が両方揃う）
    assert dispatch.await_count == 2
    assert {call.args[3] for call in dispatch.await_args_list} == {"user", "operator"}
    assert all(call.args[2] == str(overdue.id) for call in dispatch.await_args_list)

    await db_session.refresh(overdue)
    await db_session.refresh(future)
    await db_session.refresh(done)
    assert overdue.overdue_reminded_at is not None
    assert future.overdue_reminded_at is None
    assert done.overdue_reminded_at is None

    # 2周目は送信済みマーカーにより1通も飛ばない（二重送信防止）
    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", new_callable=AsyncMock
    ) as dispatch2:
        again = await run_reminders(db_session)
    assert again["overdue"] == 0
    assert dispatch2.await_count == 0


async def test_no_bid_reminder_selects_and_marks_once(db_session: AsyncSession):
    """作成から3日超・入札0・open の案件だけを拾い、依頼者へ1回だけ通知する。"""
    now = datetime.now(timezone.utc)
    user, _ = await _make_user(db_session, "nobid_owner@example.com")
    operator, _ = await _make_operator(db_session, "nobid_op@example.com")

    stale = await _make_case(db_session, user, created_at=now - timedelta(days=4))
    # 対象外1: まだ3日経っていない
    fresh = await _make_case(db_session, user, created_at=now - timedelta(days=1))
    # 対象外2: 3日超だが入札が付いている
    bid_case = await _make_case(db_session, user, created_at=now - timedelta(days=10))
    db_session.add(
        Bid(case_id=bid_case.id, operator_id=operator.id, amount=10000, status="pending")
    )
    # 対象外3: 3日超・入札0 だが取り下げ済み（open ではない）
    cancelled = await _make_case(
        db_session, user, status="cancelled", created_at=now - timedelta(days=10)
    )
    await db_session.commit()

    with patch(
        "app.services.notify_dispatch.dispatch_no_bid_reminder", new_callable=AsyncMock
    ) as dispatch:
        result = await run_reminders(db_session)

    assert result["no_bid"] == 1
    assert dispatch.await_count == 1
    assert dispatch.await_args.args[2] == str(stale.id)

    for case in (stale, fresh, bid_case, cancelled):
        await db_session.refresh(case)
    assert stale.no_bid_reminded_at is not None
    assert fresh.no_bid_reminded_at is None
    assert bid_case.no_bid_reminded_at is None
    assert cancelled.no_bid_reminded_at is None

    with patch(
        "app.services.notify_dispatch.dispatch_no_bid_reminder", new_callable=AsyncMock
    ) as dispatch2:
        again = await run_reminders(db_session)
    assert again["no_bid"] == 0
    assert dispatch2.await_count == 0


async def test_admin_jobs_reminders_requires_admin_and_returns_counts(
    client: AsyncClient, db_session: AsyncSession
):
    """POST /admin/jobs/reminders は admin 限定で {overdue, no_bid} を返す。"""
    user, user_token = await _make_user(db_session, "job_user@example.com")
    _, admin_token = await _make_user(db_session, "job_admin@example.com", role="admin")
    operator, op_token = await _make_operator(db_session, "job_op@example.com")

    today = datetime.now(timezone.utc).date()
    overdue_case = await _make_case(db_session, user, status="closed")
    await _make_transaction(
        db_session,
        overdue_case,
        operator,
        visit_date=today - timedelta(days=2),
        status="visiting",
    )
    await _make_case(
        db_session, user, created_at=datetime.now(timezone.utc) - timedelta(days=5)
    )

    # 依頼者は 403（admin ロールなし）、業者トークンは 401（typ が user でない）
    assert (
        await client.post("/api/v1/admin/jobs/reminders", headers=_auth(user_token))
    ).status_code == 403
    assert (
        await client.post("/api/v1/admin/jobs/reminders", headers=_auth(op_token))
    ).status_code == 401

    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", new_callable=AsyncMock
    ), patch(
        "app.services.notify_dispatch.dispatch_no_bid_reminder", new_callable=AsyncMock
    ):
        r = await client.post("/api/v1/admin/jobs/reminders", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        assert r.json() == {"overdue": 1, "no_bid": 1}

        # 連打しても二重に送らない（マーカーで冪等）
        r = await client.post("/api/v1/admin/jobs/reminders", headers=_auth(admin_token))
        assert r.json() == {"overdue": 0, "no_bid": 0}


async def test_overdue_reminder_covers_pending_and_respects_jst_boundary_and_window(
    db_session: AsyncSession,
):
    """pending + visit_date 経路・JST の日付境界・遡り窓を1本で押さえる（r12-review L-3 / H-1）。

    - ``pending``（日程は入っているが visiting へ進んでいない）も対象に含める。
    - JST の「今日」は対象外、「昨日」は対象（UTC 判定だと日本の 0:00〜9:00 の間だけ
      1日ズレる。UTC の日付を使うと today_jst が UTC 日付より先行する時間帯で
      境界がズレるため、判定は必ず JST で行う）。
    - :data:`REMINDER_LOOKBACK_DAYS` より古い放置は拾わない（デプロイ直後の一斉送信防止）。
    """
    today_jst = datetime.now(timezone.utc).astimezone(JST).date()
    user, _ = await _make_user(db_session, "jst_owner@example.com")
    operator, _ = await _make_operator(db_session, "jst_op@example.com")

    async def _txn(visit_date, status: str) -> Transaction:
        case = await _make_case(db_session, user, status="closed")
        return await _make_transaction(
            db_session, case, operator, visit_date=visit_date, status=status
        )

    yesterday_pending = await _txn(today_jst - timedelta(days=1), "pending")
    today_visiting = await _txn(today_jst, "visiting")
    too_old = await _txn(today_jst - timedelta(days=REMINDER_LOOKBACK_DAYS + 1), "visiting")

    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", new_callable=AsyncMock
    ) as dispatch:
        result = await run_reminders(db_session)

    assert result["overdue"] == 1
    assert {call.args[2] for call in dispatch.await_args_list} == {str(yesterday_pending.id)}

    for txn in (yesterday_pending, today_visiting, too_old):
        await db_session.refresh(txn)
    assert yesterday_pending.overdue_reminded_at is not None
    assert today_visiting.overdue_reminded_at is None, "JST の当日は対象外"
    assert too_old.overdue_reminded_at is None, "遡り窓の外は対象外"


async def test_reminder_claims_before_dispatch_and_never_resends_on_failure(
    db_session: AsyncSession,
):
    """通知前にマーカーを確定（claim→commit→通知）し、通知失敗でも再送しない（H-2 / M-5）。

    dispatch の内側から同じ DB を読み、その時点で既に ``overdue_reminded_at`` が
    入っていることを確認する（= 二重送信の窓が閉じている）。さらに dispatch が
    例外を投げても1周は完走し、次周で再送されないことを確認する。
    """
    today_jst = datetime.now(timezone.utc).astimezone(JST).date()
    user, _ = await _make_user(db_session, "claim_owner@example.com")
    operator, _ = await _make_operator(db_session, "claim_op@example.com")
    case = await _make_case(db_session, user, status="closed")
    txn = await _make_transaction(
        db_session, case, operator, visit_date=today_jst - timedelta(days=1), status="visiting"
    )

    marked_at_dispatch_time: list[bool] = []

    async def _explode(*args, **kwargs) -> None:
        marked = await db_session.scalar(
            select(Transaction.overdue_reminded_at).where(Transaction.id == txn.id)
        )
        marked_at_dispatch_time.append(marked is not None)
        raise RuntimeError("LINE API down")

    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", side_effect=_explode
    ), patch(
        # 渡されたコルーチンは close() する（未 await の RuntimeWarning を出さない）。
        "app.services.reminders.alerts.fire_and_forget",
        side_effect=lambda coro: coro.close(),
    ) as fire:
        result = await run_reminders(db_session)

    assert result["overdue"] == 1
    assert marked_at_dispatch_time == [True, True], "通知の時点でマーカーが未確定（二重送信の窓）"
    assert fire.call_count == 2, "通知失敗が運営アラート（warning）に落ちていない"

    # 2周目: 失敗した通知は再送しない（同じ催促が何通も飛ぶ害の方が大きい）。
    with patch(
        "app.services.notify_dispatch.dispatch_visit_overdue", new_callable=AsyncMock
    ) as dispatch2:
        again = await run_reminders(db_session)
    assert again["overdue"] == 0
    assert dispatch2.await_count == 0
