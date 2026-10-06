"""日程候補の構造化（日程構造化 DESIGN §13）の API テスト。

- POST /transactions/{id}/schedule/propose: {candidates: [{date, start, end}]} の形・meta v2 と seq・
  日本時間の日付範囲と境界・当日の終わった枠・重複・判定順・時刻の規則と余分なキー（Pydantic の 422）・
  開いたままの旧タブ（{slots}）の 422 と warning ログ
- POST /transactions/{id}/schedule/proposals/{proposal_id}/accept: 正常系（サーバーが作る値・通知）・
  IDOR の 404・最新の提示だけ（seq の最大値。v1 が混ざっても）・v1 / 未知の版の 422・添字の範囲外・
  期限切れ（日付と当日の終了時刻）・業者と第三者の 403・状態の 409・管理者の代理の confirmed_by
- POST /transactions/{id}/schedule/confirm（/schedule 専用）: 固定5種の許可リスト・日本時間の範囲・
  当日の終わった枠・ひとことの分離と制御文字・管理者の代理でのひとことの 422

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_txn_state_integrity.py・tests/test_r8_abnormal_guards.py と同様、ヘルパーはこの
ファイル内に自己完結で複製する。「今」は transactions._now_jst を固定して決める。
制御文字・紛らわしい記号はソースに生で書かず chr() で組み立てる。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Callable
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.message import Message
from app.db.models.transaction import Transaction
from app.db.models.user import User
from app.db.session import get_session
from app.services.visit_schedule import (
    FIXED_VISIT_TIME_SLOTS,
    JST,
    VisitCandidate,
    candidate_label,
    format_visit_label,
)

_WAVE_DASH = chr(0x301C)
_FULLWIDTH_TILDE = chr(0xFF5E)
_SLOT_MORNING, _SLOT_NOON, _SLOT_AFTERNOON, _SLOT_EVENING, _SLOT_ANY = FIXED_VISIT_TIME_SLOTS
assert _SLOT_MORNING == "9:00" + _WAVE_DASH + "12:00"
assert _SLOT_ANY == "時間指定なし"

#: テストの「今」: 2026年10月1日（木）10:30（日本時間）。
_NOW = datetime(2026, 10, 1, 10, 30, tzinfo=JST)
_TODAY = _NOW.date()

_LOGGER_NAME = "app.api.v1.endpoints.transactions"

_PROPOSE_OUTDATED = {
    "code": "schedule_client_outdated",
    "message": "画面が古いため送信できませんでした。ページを再読み込みしてから、もう一度候補日を送ってください。",
}
_CONFIRM_OUTDATED = {
    "code": "schedule_client_outdated",
    "message": "この画面からは確定できません。ページを再読み込みしてから、もう一度お選びください。",
}
_SUPERSEDED = {
    "code": "schedule_proposal_superseded",
    "message": "業者から新しい候補日が届いています。最新の候補からお選びください。",
}
_EXPIRED = {
    "code": "schedule_candidate_expired",
    "message": "この候補日は過ぎています。業者に新しい候補を依頼するか、日程調整ページからお選びください。",
}
_LEGACY = {
    "code": "schedule_proposal_legacy",
    "message": "この候補は古い形式のため、ここでは確定できません。日程調整ページからお選びください。",
}
_RANGE_DETAIL = "候補日は本日（日本時間）から1年以内の日付を選んでください。"
_ENDED_DETAIL = "終わった時間帯は候補にできません。"
_DUPLICATE_DETAIL = "同じ日付・時間帯の候補が重複しています。"
_NOT_PENDING_DETAIL = "日程確定できる状態ではありません。"
_USER_ONLY_DETAIL = "日程確定はユーザー側のみ行えます。"


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
def set_now(monkeypatch: pytest.MonkeyPatch) -> Callable[[datetime], None]:
    """transactions._now_jst を _NOW に固定する。返す関数で途中から別の時刻へ差し替えられる。"""

    def _set(moment: datetime) -> None:
        fixed = moment.astimezone(JST)
        monkeypatch.setattr("app.api.v1.endpoints.transactions._now_jst", lambda: fixed)

    _set(_NOW)
    return _set


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="sch_struct_admin@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "sch_struct_admin@katadzuke.jp", "password": "adminpass123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _signup_user(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"agreed_terms": True, "email": email, "password": "password123", "name": "テスト太郎"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _verified_operator(client: AsyncClient, admin_token: str, email: str) -> str:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": r.json()["code"],
            "company_name": "テスト片付け株式会社",
            "email": email,
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    # 招待コード経由でも signup 直後は pending。許可証画像の提出 → 運営承認で active にする。
    r = await client.post(
        "/api/v1/operator/license-image",
        files={"file": ("license.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 256, "image/png")},
        headers=_auth(data["access_token"]),
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"/api/v1/admin/operators/{data['operator']['id']}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    return data["access_token"]


async def _create_transaction(client: AsyncClient, user_token: str, op_token: str) -> str:
    """案件作成 → 入札 → 落札まで進め、transaction_id を返す。"""
    r = await client.post(
        "/api/v1/cases",
        json={
            "purpose": "遺品整理",
            "prefecture": "東京都",
            "city": "世田谷区",
            "address_detail": "桜丘1-2-3 メゾン桜 101号室",
            "housing_type": "マンション",
            "floor_plan": "2LDK",
            "floor_number": 1,
            "has_elevator": False,
            "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0}],
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids", json={"amount": 30000}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{r.json()['id']}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@dataclass
class _Txn:
    admin_token: str
    user_token: str
    op_token: str
    op_email: str
    txn_id: str


async def _setup(
    client: AsyncClient,
    db_session: AsyncSession,
    prefix: str,
    *,
    admin_token: str | None = None,
    user_token: str | None = None,
) -> _Txn:
    """運営・依頼者・承認済み業者・成約（pending）を用意する（運営と依頼者は使い回せる）。"""
    if admin_token is None:
        admin_token = await _make_admin(client, db_session)
    if user_token is None:
        user_token = await _signup_user(client, f"{prefix}_user@example.com")
    op_email = f"{prefix}_op@example.com"
    op_token = await _verified_operator(client, admin_token, op_email)
    txn_id = await _create_transaction(client, user_token, op_token)
    return _Txn(admin_token, user_token, op_token, op_email, txn_id)


def _cand(day_offset: int, start: str | None = "09:00", end: str | None = "12:00") -> dict:
    """_TODAY から day_offset 日後の候補（propose の candidates の1要素）。"""
    return {"date": (_TODAY + timedelta(days=day_offset)).isoformat(), "start": start, "end": end}


async def _propose(
    client: AsyncClient, t: _Txn, *candidates: dict, token: str | None = None
) -> Response:
    return await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/propose",
        json={"candidates": list(candidates)},
        headers=_auth(token or t.op_token),
    )


async def _accept(
    client: AsyncClient, t: _Txn, proposal_id: str, index: object = 0, token: str | None = None
) -> Response:
    return await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/proposals/{proposal_id}/accept",
        json={"candidate_index": index},
        headers=_auth(token or t.user_token),
    )


async def _confirm(
    client: AsyncClient,
    t: _Txn,
    day_offset: int,
    slot: str,
    *,
    note: str | None = None,
    token: str | None = None,
) -> Response:
    body: dict = {
        "visit_date": (_TODAY + timedelta(days=day_offset)).isoformat(),
        "visit_time_slot": slot,
    }
    if note is not None:
        body["note"] = note
    return await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/confirm",
        json=body,
        headers=_auth(token or t.user_token),
    )


async def _messages(client: AsyncClient, t: _Txn, token: str | None = None) -> list[dict]:
    r = await client.get(
        f"/api/v1/transactions/{t.txn_id}/messages", headers=_auth(token or t.user_token)
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _count_kind(db_session: AsyncSession, txn_id: str, kind: str) -> int:
    count = await db_session.scalar(
        select(func.count()).select_from(Message).where(
            Message.transaction_id == uuid.UUID(txn_id), Message.kind == kind
        )
    )
    return int(count or 0)


async def _insert_proposal(db_session: AsyncSession, txn_id: str, meta: object) -> str:
    """API を通さずに schedule_proposal を1行入れる（旧形式・未知の版のデータの再現用）。"""
    message = Message(
        transaction_id=uuid.UUID(txn_id),
        sender_type="operator",
        sender_id=None,
        body="訪問日程の候補を1件提示しました。",
        kind="schedule_proposal",
        meta=meta,
    )
    db_session.add(message)
    await db_session.commit()
    return str(message.id)


def _label(day_offset: int, start: str | None, end: str | None) -> str:
    return candidate_label(VisitCandidate(date=_TODAY + timedelta(days=day_offset), start=start, end=end))


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [rec.getMessage() for rec in caplog.records if rec.name == _LOGGER_NAME]


# ──────────────────────────── propose ────────────────────────────


async def test_propose_saves_v2_meta_with_server_labels(client: AsyncClient, db_session: AsyncSession):
    """meta は v2（seq・日付・時刻・サーバーが作る表示）。slots は持たない。"""
    t = await _setup(client, db_session, "prop_v2")
    r = await _propose(client, t, _cand(0, "12:00", "15:00"), _cand(2, None, None), _cand(3, "10:30", "12:00"))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["kind"] == "schedule_proposal"
    assert data["sender_type"] == "operator"
    assert data["mine"] is True
    assert data["body"] == "訪問日程の候補を3件提示しました。"
    assert data["meta"] == {
        "v": 2,
        "seq": 1,
        "candidates": [
            {**_cand(0, "12:00", "15:00"), "label": _label(0, "12:00", "15:00")},
            {**_cand(2, None, None), "label": _label(2, None, None)},
            {**_cand(3, "10:30", "12:00"), "label": _label(3, "10:30", "12:00")},
        ],
    }
    # 表示は日本時間の暦・全角括弧・波ダッシュ（組み立てを関数に頼らず1件は直書きで確かめる）。
    assert data["meta"]["candidates"][0]["label"] == "2026年10月1日（木）12:00" + _WAVE_DASH + "15:00"
    assert data["meta"]["candidates"][1]["label"] == "2026年10月3日（土）時間指定なし"


async def test_propose_seq_increments_per_transaction(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "prop_seq")
    other = await _setup(client, db_session, "prop_seq2", admin_token=t.admin_token)
    for expected_seq in (1, 2, 3):
        r = await _propose(client, t, _cand(expected_seq))
        assert r.status_code == 201, r.text
        assert r.json()["meta"]["seq"] == expected_seq
    # seq は取引ごとの通し番号（他の取引の提示とは独立）。
    r = await _propose(client, other, _cand(1))
    assert r.status_code == 201, r.text
    assert r.json()["meta"]["seq"] == 1


async def test_propose_ignores_unknown_top_level_keys(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "prop_topkey")
    r = await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/propose",
        json={"candidates": [_cand(1)], "note": "最上位の未知のキーは無視する"},
        headers=_auth(t.op_token),
    )
    assert r.status_code == 201, r.text


async def test_propose_legacy_slots_payload_returns_outdated_422_without_writing(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """旧タブの {slots} は 422 dict（再読み込みの案内）。書き込みゼロ・ラベル本文はログに出さない。"""
    t = await _setup(client, db_session, "prop_legacy")
    legacy_label = "9月7日（日）10:00" + _WAVE_DASH + "12:00"
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        r = await client.post(
            f"/api/v1/transactions/{t.txn_id}/schedule/propose",
            json={"slots": [legacy_label]},
            headers=_auth(t.op_token),
        )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _PROPOSE_OUTDATED
    assert await _count_kind(db_session, t.txn_id, "schedule_proposal") == 0
    logs = _warnings(caplog)
    assert any(
        "schedule.legacy_client path=propose" in line and t.txn_id in line for line in logs
    ), logs
    assert all(legacy_label not in line for line in logs)


async def test_propose_null_candidates_returns_outdated_422(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "prop_null")
    r = await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/propose",
        json={"candidates": None},
        headers=_auth(t.op_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _PROPOSE_OUTDATED


async def test_propose_legacy_payload_is_judged_after_authz_and_state(
    client: AsyncClient, db_session: AsyncSession
):
    """判定順: 認可（403）→ 状態（409）→ 旧タブの 422。"""
    t = await _setup(client, db_session, "prop_order")
    legacy = {"slots": ["9月7日 午前"]}
    r = await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/propose", json=legacy, headers=_auth(t.user_token)
    )
    assert r.status_code == 403, r.text
    r = await _confirm(client, t, 3, _SLOT_MORNING)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/propose", json=legacy, headers=_auth(t.op_token)
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "schedule_already_confirmed"


@pytest.mark.parametrize(("day_offset", "expected"), [(-1, 422), (0, 201), (365, 201), (366, 422)])
async def test_propose_date_range_is_today_to_365_days_in_jst(
    client: AsyncClient, db_session: AsyncSession, day_offset: int, expected: int
):
    t = await _setup(client, db_session, f"prop_range{day_offset + 1}")
    r = await _propose(client, t, _cand(day_offset))
    assert r.status_code == expected, r.text
    if expected == 422:
        assert r.json()["detail"] == _RANGE_DETAIL


async def test_propose_date_range_follows_jst_day_boundary(
    client: AsyncClient, db_session: AsyncSession, set_now: Callable[[datetime], None]
):
    """UTC 14:59（日本時間 23:59）は当日を選べ、UTC 15:00（翌日 0:00）では前日になる。"""
    t = await _setup(client, db_session, "prop_boundary")
    set_now(datetime(2026, 9, 30, 14, 59, tzinfo=timezone.utc))
    r = await _propose(client, t, _cand(-1, None, None))
    assert r.status_code == 201, r.text
    set_now(datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc))
    r = await _propose(client, t, _cand(-1, None, None))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _RANGE_DETAIL
    r = await _propose(client, t, _cand(0, "06:00", "07:00"))
    assert r.status_code == 201, r.text


async def test_propose_rejects_ended_window_today(
    client: AsyncClient, db_session: AsyncSession, set_now: Callable[[datetime], None]
):
    """当日で終了時刻を過ぎた枠（現在時刻 ≥ 終了）は候補にできない。時間指定なしの当日は可。"""
    t = await _setup(client, db_session, "prop_ended")
    set_now(datetime(2026, 10, 1, 12, 0, tzinfo=JST))
    r = await _propose(client, t, _cand(0, "09:00", "12:00"))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _ENDED_DETAIL
    r = await _propose(client, t, _cand(0, "12:00", "15:00"))
    assert r.status_code == 201, r.text
    set_now(datetime(2026, 10, 1, 23, 59, tzinfo=JST))
    r = await _propose(client, t, _cand(0, None, None))
    assert r.status_code == 201, r.text


async def test_propose_rejects_duplicate_candidates(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "prop_dup")
    r = await _propose(client, t, _cand(1), _cand(2), _cand(1))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _DUPLICATE_DETAIL
    r = await _propose(client, t, _cand(1, None, None), _cand(1, None, None))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _DUPLICATE_DETAIL
    # 同じ日付でも時間帯が違えば別の候補。
    r = await _propose(client, t, _cand(1), _cand(1, "12:00", "15:00"), _cand(1, None, None))
    assert r.status_code == 201, r.text


async def test_propose_semantic_checks_run_in_order(
    client: AsyncClient, db_session: AsyncSession, set_now: Callable[[datetime], None]
):
    """判定順: 日付範囲 → 当日の終わった枠 → 重複（DESIGN §13.3）。"""
    t = await _setup(client, db_session, "prop_semantic")
    set_now(datetime(2026, 10, 1, 12, 0, tzinfo=JST))
    ended = _cand(0, "09:00", "12:00")
    r = await _propose(client, t, _cand(2), _cand(2), ended, _cand(-1))
    assert r.json()["detail"] == _RANGE_DETAIL
    r = await _propose(client, t, _cand(2), _cand(2), ended)
    assert r.json()["detail"] == _ENDED_DETAIL
    r = await _propose(client, t, _cand(2), _cand(2))
    assert r.json()["detail"] == _DUPLICATE_DETAIL
    assert await _count_kind(db_session, t.txn_id, "schedule_proposal") == 0


async def test_propose_rejects_invalid_shapes_with_pydantic_422(
    client: AsyncClient, db_session: AsyncSession
):
    """書式・時刻の規則・片方だけ null・余分なキー・件数 0/11 は Pydantic の 422（配列）。"""
    t = await _setup(client, db_session, "prop_shape")
    cases: list[tuple[str, object]] = [
        ("empty", []),
        ("eleven", [_cand(day) for day in range(1, 12)]),
        ("not_list", _cand(1)),
        ("quarter_minutes", [_cand(1, "09:15", "12:00")]),
        ("no_zero_pad", [_cand(1, "9:00", "12:00")]),
        ("before_6", [_cand(1, "05:30", "07:00")]),
        ("after_22", [_cand(1, "21:30", "22:30")]),
        ("shorter_than_1h", [_cand(1, "10:00", "10:30")]),
        ("reversed", [_cand(1, "12:00", "09:00")]),
        ("end_null_only", [_cand(1, "09:00", None)]),
        ("end_key_missing", [{"date": _cand(1)["date"], "start": "09:00"}]),
        ("extra_label_key", [{**_cand(1), "label": "業者が作ったラベル"}]),
        ("slash_date", [{**_cand(1), "date": "2026/10/02"}]),
        ("unix_time_date", [{**_cand(1), "date": 1790000000}]),
        ("nonexistent_date", [{**_cand(1), "date": "2026-02-30"}]),
        ("datetime_date", [{**_cand(1), "date": "2026-10-02T00:00:00"}]),
    ]
    for name, candidates in cases:
        r = await client.post(
            f"/api/v1/transactions/{t.txn_id}/schedule/propose",
            json={"candidates": candidates},
            headers=_auth(t.op_token),
        )
        assert r.status_code == 422, (name, r.text)
        assert isinstance(r.json()["detail"], list), (name, r.text)
    assert await _count_kind(db_session, t.txn_id, "schedule_proposal") == 0


# ──────────────────────────── accept ────────────────────────────


async def test_accept_confirms_with_server_generated_values(client: AsyncClient, db_session: AsyncSession):
    """確定の値（visit_date・時刻だけの visit_time_slot・本文・meta v2）はサーバーが作る。"""
    t = await _setup(client, db_session, "acc_ok")
    r = await _propose(client, t, _cand(1), _cand(2, None, None))
    assert r.status_code == 201, r.text
    proposal_id = r.json()["id"]

    with patch(
        "app.api.v1.endpoints.transactions.notify_dispatch.dispatch_schedule_confirmed",
        new_callable=AsyncMock,
    ) as dispatch_mock:
        r = await _accept(client, t, proposal_id, 1)
    assert r.status_code == 200, r.text
    visit_date = (_TODAY + timedelta(days=2)).isoformat()
    data = r.json()
    assert data["status"] == "visiting"
    assert data["visit_date"] == visit_date
    assert data["visit_time_slot"] == _SLOT_ANY
    # 業者の line_user_id（未連携なので None）・email・txn_id・訪問日の順で完全一致。
    dispatch_mock.assert_called_once_with(None, t.op_email, t.txn_id, visit_date)

    confirmed = [m for m in await _messages(client, t) if m["kind"] == "schedule_confirmed"]
    assert len(confirmed) == 1
    label = _label(2, None, None)
    assert label == "2026年10月3日（土）時間指定なし"
    assert confirmed[0]["sender_type"] == "system"
    assert confirmed[0]["body"] == f"訪問日程が {label} に確定しました。"
    assert confirmed[0]["meta"] == {
        "v": 2,
        "source": "proposal",
        "proposal_id": proposal_id,
        "candidate_index": 1,
        "visit_date": visit_date,
        "visit_time_slot": _SLOT_ANY,
        "label": label,
        "confirmed_by": "user",
    }
    # 確定後の再提示は 409（lamarr の挙動のまま）。
    r = await _propose(client, t, _cand(5))
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "schedule_already_confirmed"


async def test_accept_custom_window_stores_time_only_slot(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "acc_custom")
    r = await _propose(client, t, _cand(1, "10:30", "12:00"))
    assert r.status_code == 201, r.text
    r = await _accept(client, t, r.json()["id"], 0)
    assert r.status_code == 200, r.text
    assert r.json()["visit_time_slot"] == "10:30" + _WAVE_DASH + "12:00"
    txn = await db_session.get(Transaction, uuid.UUID(t.txn_id))
    await db_session.refresh(txn)
    assert txn.visit_date == _TODAY + timedelta(days=1)


async def test_accept_rejects_ids_outside_this_transaction_with_404(
    client: AsyncClient, db_session: AsyncSession
):
    """他の取引の提示・通常のメッセージ・存在しない id では確定できない（IDOR 防止の3条件）。"""
    t = await _setup(client, db_session, "acc_idor")
    other = await _setup(
        client, db_session, "acc_idor2", admin_token=t.admin_token, user_token=t.user_token
    )
    r = await _propose(client, other, _cand(1))
    assert r.status_code == 201, r.text
    other_proposal_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/transactions/{t.txn_id}/messages",
        json={"body": "通常のメッセージです"},
        headers=_auth(t.op_token),
    )
    assert r.status_code == 201, r.text
    text_message_id = r.json()["id"]

    for proposal_id in (other_proposal_id, text_message_id, str(uuid.uuid4())):
        r = await _accept(client, t, proposal_id, 0)
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "候補日の提示が見つかりません。ページを再読み込みしてください。"
    r = await client.get(f"/api/v1/transactions/{t.txn_id}", headers=_auth(t.user_token))
    assert r.json()["status"] == "pending"
    r = await client.get(f"/api/v1/transactions/{other.txn_id}", headers=_auth(t.user_token))
    assert r.json()["status"] == "pending"


async def test_accept_only_latest_proposal(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "acc_latest")
    first = (await _propose(client, t, _cand(1))).json()["id"]
    second = (await _propose(client, t, _cand(2))).json()["id"]
    r = await _accept(client, t, first, 0)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == _SUPERSEDED
    r = await _accept(client, t, second, 0)
    assert r.status_code == 200, r.text
    assert r.json()["visit_date"] == (_TODAY + timedelta(days=2)).isoformat()


async def test_accept_latest_is_max_seq_even_with_v1_rows(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """seq を持たない v1 の提示は最新の判定（MAX(seq)）に影響せず、v1 自体は 422 legacy。"""
    t = await _setup(client, db_session, "acc_v1mix")
    v2_id = (await _propose(client, t, _cand(1))).json()["id"]
    v1_id = await _insert_proposal(
        db_session, t.txn_id, {"slots": ["9月7日（日）10:00" + _WAVE_DASH + "12:00"]}
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        r = await _accept(client, t, v1_id, 0)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _LEGACY
    assert any("schedule.legacy_proposal path=accept" in line for line in _warnings(caplog))
    r = await _accept(client, t, v2_id, 0)
    assert r.status_code == 200, r.text


async def test_accept_rejects_unknown_meta_versions_with_legacy_422(
    client: AsyncClient, db_session: AsyncSession
):
    t = await _setup(client, db_session, "acc_unknown")
    stored = {**_cand(1), "label": _label(1, "09:00", "12:00")}
    for meta in (None, {"v": 3, "seq": 1, "candidates": [stored]}, {"v": 2, "seq": 1, "candidates": []}):
        proposal_id = await _insert_proposal(db_session, t.txn_id, meta)
        r = await _accept(client, t, proposal_id, 0)
        assert r.status_code == 422, (meta, r.text)
        assert r.json()["detail"] == _LEGACY
    r = await client.get(f"/api/v1/transactions/{t.txn_id}", headers=_auth(t.user_token))
    assert r.json()["status"] == "pending"


async def test_accept_rejects_invalid_candidate_index(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "acc_index")
    proposal_id = (await _propose(client, t, _cand(1), _cand(2))).json()["id"]
    r = await _accept(client, t, proposal_id, 2)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "候補が見つかりません。ページを再読み込みしてください。"
    # StrictInt 0〜9・extra="forbid" は Pydantic の 422（配列）。
    for index in (10, -1, "0", True, 0.0, None):
        r = await _accept(client, t, proposal_id, index)
        assert r.status_code == 422, (index, r.text)
        assert isinstance(r.json()["detail"], list), (index, r.text)
    r = await client.post(
        f"/api/v1/transactions/{t.txn_id}/schedule/proposals/{proposal_id}/accept",
        json={"candidate_index": 0, "note": "受け付けないキー"},
        headers=_auth(t.user_token),
    )
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], list)
    r = await client.get(f"/api/v1/transactions/{t.txn_id}", headers=_auth(t.user_token))
    assert r.json()["status"] == "pending"


async def test_accept_rejects_expired_candidates(
    client: AsyncClient, db_session: AsyncSession, set_now: Callable[[datetime], None]
):
    """当日で終了時刻を過ぎた候補・日付が過ぎた候補は 409 expired。当日の時間指定なしは確定できる。"""
    t = await _setup(client, db_session, "acc_expired")
    proposal_id = (await _propose(client, t, _cand(0, "09:00", "12:00"), _cand(0, None, None))).json()["id"]
    set_now(datetime(2026, 10, 1, 12, 0, tzinfo=JST))
    r = await _accept(client, t, proposal_id, 0)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == _EXPIRED
    r = await _accept(client, t, proposal_id, 1)
    assert r.status_code == 200, r.text

    set_now(_NOW)
    other = await _setup(client, db_session, "acc_expired2", admin_token=t.admin_token)
    other_proposal = (await _propose(client, other, _cand(1, None, None))).json()["id"]
    set_now(datetime(2026, 10, 3, 0, 0, tzinfo=JST))
    r = await _accept(client, other, other_proposal, 0)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == _EXPIRED


async def test_accept_rejects_operator_and_non_party(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "acc_party")
    proposal_id = (await _propose(client, t, _cand(1))).json()["id"]
    r = await _accept(client, t, proposal_id, 0, token=t.op_token)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == _USER_ONLY_DETAIL
    stranger = await _signup_user(client, "acc_party_stranger@example.com")
    r = await _accept(client, t, proposal_id, 0, token=stranger)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "この成約への権限がありません。"
    r = await client.post(
        f"/api/v1/transactions/{uuid.uuid4()}/schedule/proposals/{proposal_id}/accept",
        json={"candidate_index": 0},
        headers=_auth(t.user_token),
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "成約情報が見つかりません。"


async def test_accept_rejects_when_not_pending(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "acc_state")
    proposal_id = (await _propose(client, t, _cand(1), _cand(2))).json()["id"]
    r = await _accept(client, t, proposal_id, 0)
    assert r.status_code == 200, r.text
    # 二重押し（同じ候補・別の候補とも）は 409。確定メッセージは増えない。
    for index in (0, 1):
        r = await _accept(client, t, proposal_id, index)
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == _NOT_PENDING_DETAIL
    assert await _count_kind(db_session, t.txn_id, "schedule_confirmed") == 1

    cancelled = await _setup(client, db_session, "acc_state2", admin_token=t.admin_token)
    cancelled_proposal = (await _propose(client, cancelled, _cand(1))).json()["id"]
    r = await client.post(
        f"/api/v1/transactions/{cancelled.txn_id}/cancel",
        json={"reason": "テスト都合"},
        headers=_auth(cancelled.user_token),
    )
    assert r.status_code == 200, r.text
    r = await _accept(client, cancelled, cancelled_proposal, 0)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == _NOT_PENDING_DETAIL


async def test_accept_by_admin_records_confirmed_by_admin(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "acc_admin")
    proposal_id = (await _propose(client, t, _cand(1))).json()["id"]
    r = await _accept(client, t, proposal_id, 0, token=t.admin_token)
    assert r.status_code == 200, r.text
    confirmed = [m for m in await _messages(client, t) if m["kind"] == "schedule_confirmed"]
    assert confirmed[0]["meta"]["confirmed_by"] == "admin"


# ──────────────────────────── confirm（/schedule 専用） ────────────────────────────


async def test_confirm_fixed_slot_writes_v2_meta(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "conf_ok")
    r = await _confirm(client, t, 3, _SLOT_EVENING)
    assert r.status_code == 200, r.text
    visit_date = (_TODAY + timedelta(days=3)).isoformat()
    assert r.json()["visit_date"] == visit_date
    assert r.json()["visit_time_slot"] == _SLOT_EVENING
    messages = await _messages(client, t)
    assert [m["kind"] for m in messages] == ["schedule_confirmed"]
    label = format_visit_label(_TODAY + timedelta(days=3), _SLOT_EVENING)
    assert label == "2026年10月4日（日）18:00" + _WAVE_DASH + "21:00"
    assert messages[0]["body"] == f"訪問日程が {label} に確定しました。"
    assert messages[0]["meta"] == {
        "v": 2,
        "source": "calendar",
        "visit_date": visit_date,
        "visit_time_slot": _SLOT_EVENING,
        "label": label,
        "confirmed_by": "user",
    }


async def test_confirm_rejects_non_fixed_slots_with_outdated_422(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """固定5種以外（旧依頼者タブの業者ラベル・全角チルダ・任意の時刻）は 422 dict。値はログに出さない。"""
    t = await _setup(client, db_session, "conf_legacy")
    r = await _confirm(client, t, 3, "午前", token=t.op_token)
    assert r.status_code == 403, r.text
    values = [
        "午前",
        "10:00-12:00",
        "2026年10月2日（金）9:00" + _WAVE_DASH + "12:00",
        "9:00" + _FULLWIDTH_TILDE + "12:00",
        "10:30" + _WAVE_DASH + "12:00",
    ]
    for value in values:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            # 日付が過去でも許可リストの判定が先（再読み込みの案内を優先する）。
            r = await _confirm(client, t, -1, value)
        assert r.status_code == 422, (value, r.text)
        assert r.json()["detail"] == _CONFIRM_OUTDATED
        logs = _warnings(caplog)
        assert any("schedule.legacy_client path=confirm" in line for line in logs), logs
        assert all(value not in line for line in logs)
    assert await _count_kind(db_session, t.txn_id, "schedule_confirmed") == 0


@pytest.mark.parametrize(
    ("day_offset", "expected_detail"),
    [
        (-1, "訪問日は本日以降を指定してください。"),
        (366, "訪問日は1年以内で指定してください。"),
        (365, None),
        (0, None),
    ],
)
async def test_confirm_date_range_in_jst(
    client: AsyncClient, db_session: AsyncSession, day_offset: int, expected_detail: str | None
):
    t = await _setup(client, db_session, f"conf_range{day_offset + 1}")
    r = await _confirm(client, t, day_offset, _SLOT_ANY)
    if expected_detail is None:
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == expected_detail


async def test_confirm_today_follows_jst_not_utc(
    client: AsyncClient, db_session: AsyncSession, set_now: Callable[[datetime], None]
):
    """日本時間 0:00〜9:00（UTC では前日）でも「今日」は日本の暦（F6: UTC の date.today の解消）。"""
    t = await _setup(client, db_session, "conf_jst")
    set_now(datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc))
    r = await _confirm(client, t, -1, _SLOT_ANY)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "訪問日は本日以降を指定してください。"
    set_now(datetime(2026, 9, 30, 14, 59, tzinfo=timezone.utc))
    r = await _confirm(client, t, -1, _SLOT_ANY)
    assert r.status_code == 200, r.text


async def test_confirm_rejects_ended_fixed_slot_today(
    client: AsyncClient, db_session: AsyncSession, set_now: Callable[[datetime], None]
):
    t = await _setup(client, db_session, "conf_ended")
    set_now(datetime(2026, 10, 1, 12, 0, tzinfo=JST))
    r = await _confirm(client, t, 0, _SLOT_MORNING)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "終わった時間帯は選べません。別の時間帯か日付をお選びください。"
    r = await _confirm(client, t, 0, _SLOT_NOON)
    assert r.status_code == 200, r.text


async def test_confirm_note_is_separated_as_user_message(client: AsyncClient, db_session: AsyncSession):
    """ひとことは運営名義の確定メッセージに連結せず、依頼者本人の発言として直後に並ぶ（改行は残す）。"""
    t = await _setup(client, db_session, "conf_note")
    note = "玄関前に置きます。" + chr(10) + "お電話ください。"
    r = await _confirm(client, t, 3, _SLOT_AFTERNOON, note=note)
    assert r.status_code == 200, r.text
    messages = await _messages(client, t, token=t.op_token)
    assert [m["kind"] for m in messages] == ["schedule_confirmed", "text"]
    assert note not in messages[0]["body"]
    assert messages[1]["body"] == note
    assert messages[1]["sender_type"] == "user"
    assert messages[1]["mine"] is False
    r = await client.get(f"/api/v1/transactions/{t.txn_id}", headers=_auth(t.op_token))
    assert r.json()["unread_count"] == 1


async def test_confirm_whitespace_only_note_creates_no_message(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "conf_blank")
    r = await _confirm(client, t, 3, _SLOT_ANY, note="  " + chr(0x3000) + chr(10) + " ")
    assert r.status_code == 200, r.text
    assert [m["kind"] for m in await _messages(client, t)] == ["schedule_confirmed"]


async def test_confirm_rejects_control_chars_in_note(client: AsyncClient, db_session: AsyncSession):
    t = await _setup(client, db_session, "conf_ctrl")
    for bad_char in (chr(0x202E), chr(0x200B), chr(0x2066), chr(9), chr(13), chr(0xE000)):
        r = await _confirm(client, t, 3, _SLOT_ANY, note=f"在宅{bad_char}です")
        assert r.status_code == 422, (hex(ord(bad_char)), r.text)
    assert await _count_kind(db_session, t.txn_id, "schedule_confirmed") == 0


async def test_confirm_by_admin_rejects_note_and_records_confirmed_by(
    client: AsyncClient, db_session: AsyncSession
):
    """運営の代理の確定ではひとことを受け付けない（SEC-I7）。ひとこと無しなら confirmed_by="admin"。"""
    t = await _setup(client, db_session, "conf_admin")
    r = await _confirm(client, t, 3, _SLOT_ANY, note="代理で書いたひとこと", token=t.admin_token)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "運営による代理の確定では、ひとことは送れません。"
    r = await _confirm(client, t, 3, _SLOT_ANY, note="  ", token=t.admin_token)
    assert r.status_code == 200, r.text
    messages = await _messages(client, t)
    assert [m["kind"] for m in messages] == ["schedule_confirmed"]
    assert messages[0]["meta"]["confirmed_by"] == "admin"
