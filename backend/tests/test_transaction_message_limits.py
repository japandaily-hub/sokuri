"""取引あたりの日程提示・チャット送信の件数上限とレート制限の統合テスト。

背景（2026-09-26 日程API入力検証のセキュリティレビュー L-4）:
- POST /transactions/{id}/schedule/propose（業者のみ・1回10候補まで）に、取引あたりの
  回数上限もレート制限も無かった。
- POST /transactions/{id}/messages（create_message）にも件数上限・レート制限が無く、
  GET /transactions/{id}/messages（list_messages）はページングなしで全件を返す。

検証観点:
- 件数上限（MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION / MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION）
  は境界値ちょうどで 409 になり、DB へは書き込まれない。境界の作り方は API を何百回も
  叩くのではなく、db_session に Message 行を直接 (上限-1) 件入れてから API で1回だけ検証する
  （create_test_app が get_session を db_session に差し替えているため、直接操作した内容が
  そのまま API 経由でも見える）。
- チャットの件数上限は当事者（sender_type）ごと。text 以外の kind（schedule_proposal 等）は
  数えない。
- 終了済み（cancelled）取引は、件数上限より先に従来の transaction_closed（dict detail）の
  409 が返ることを保つ。
- レート制限（アカウント軸のみ・全取引合計）は scope="message_send" / "schedule_propose" と
  して RateLimitGuard 経由で効き、429・Retry-After・専用文言を返す。上限到達後は
  存在しない取引 ID への送信も 404 ではなく 429 になる（hit_account が _get_txn より前に
  呼ばれている証拠）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit_deps import get_rate_limiter
from app.config import Settings
from app.core.limits import (
    MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION,
    MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION,
)
from app.core.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitConfig,
    RateLimiter,
    RateLimitRule,
)
from app.db.models.message import Message
from app.db.models.transaction import Transaction
from tests.test_katadzuke_api import (
    _auth,
    _create_transaction,
    _make_admin,
    _signup_user,
    _verified_operator,
    create_test_app,
)

_MESSAGE_LIMIT_DETAIL = "この取引で送れるメッセージの上限に達しました。運営へお問い合わせください。"
_SCHEDULE_LIMIT_DETAIL = (
    f"日程候補の提示は1取引につき{MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION}"
    "回までです。調整はメッセージでご相談ください。"
)
_MESSAGE_SEND_RATE_LIMIT_MSG = "メッセージの送信が集中しています。しばらく時間をおいて再度お試しください。"
_SCHEDULE_PROPOSE_RATE_LIMIT_MSG = "日程候補の提示が集中しています。しばらく時間をおいて再度お試しください。"
_SCHEDULE_ACCEPT_RATE_LIMIT_MSG = "日程の確定が集中しています。しばらく時間をおいて再度お試しください。"


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    test_app = create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


def _propose_payload(days_ahead: int) -> dict:
    """日程候補の提示（構造化）の本文。日付は本日起点（日本時間の範囲判定に掛からない +7 日以降）。"""
    visit_day = (date.today() + timedelta(days=days_ahead)).isoformat()
    return {"candidates": [{"date": visit_day, "start": "09:00", "end": "12:00"}]}


def _rate_limiter_for_tests(
    *, message_send_max: int = 2, schedule_propose_max: int = 1, schedule_accept_max: int = 1
) -> RateLimiter:
    """レート制限を有効化したテスト専用インスタンス。

    ``test_case_cancel.py::test_cancel_rate_limited_returns_429`` と同じパターンで、
    conftest.py の既定 ``RATE_LIMIT_ENABLED=false`` に依存せず明示的に注入する。
    ``RateLimitConfig`` のうちデフォルト値を持たない既存の必須フィールド
    （login_account 等）は明示し、今回のスコープ（message_send_account /
    schedule_propose_account）はテスト用の小さい値を渡す。それ以外
    （case_create_* / public_read_ip 等）は ``RateLimitConfig`` 側のデフォルトに
    委ねる。
    """
    return RateLimiter(
        config=RateLimitConfig(
            enabled=True,
            login_account=RateLimitRule(5, 900),
            login_ip=RateLimitRule(20, 900),
            sensitive_account=RateLimitRule(5, 900),
            signup_ip=RateLimitRule(10, 3600),
            line_ip=RateLimitRule(20, 900),
            max_keys=10000,
            message_send_account=RateLimitRule(message_send_max, 60),
            schedule_propose_account=RateLimitRule(schedule_propose_max, 600),
            schedule_accept_account=RateLimitRule(schedule_accept_max, 600),
        ),
        store=InMemoryRateLimitStore(),
    )


def _seed_messages(
    txn_id: uuid.UUID,
    *,
    count: int,
    sender_type: str,
    kind: str = "text",
) -> list[Message]:
    """境界値検証用に Message 行を直接組み立てる（commit は呼び出し側で行う）。"""
    return [
        Message(
            transaction_id=txn_id,
            sender_type=sender_type,
            sender_id=None,
            body=f"既存メッセージ {i}",
            kind=kind,
            meta={"slots": ["仮の候補"]} if kind == "schedule_proposal" else None,
        )
        for i in range(count)
    ]


async def _count_kind(session: AsyncSession, txn_id: uuid.UUID, kind: str) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Message).where(
            Message.transaction_id == txn_id, Message.kind == kind
        )
    )
    return int(count or 0)


async def _count_text_by_sender(
    session: AsyncSession, txn_id: uuid.UUID, sender_type: str
) -> int:
    """kind="text" のうち sender_type だけを数える（当事者ごとの件数上限と同じ絞り込み）。"""
    count = await session.scalar(
        select(func.count()).select_from(Message).where(
            Message.transaction_id == txn_id,
            Message.kind == "text",
            Message.sender_type == sender_type,
        )
    )
    return int(count or 0)


# ──────────────────────────── 日程提示の件数上限 ────────────────────────────


async def test_schedule_propose_409_at_limit_and_db_unchanged(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.WARNING, logger="app.api.v1.endpoints.transactions")
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "sched_limit_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "sched_limit_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    txn_uuid = uuid.UUID(txn_id)

    for message in _seed_messages(
        txn_uuid, count=MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION - 1, sender_type="operator",
        kind="schedule_proposal",
    ):
        db_session.add(message)
    await db_session.commit()

    r_ok = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json=_propose_payload(7),
        headers=_auth(op_token),
    )
    assert r_ok.status_code == 201, r_ok.text
    assert await _count_kind(db_session, txn_uuid, "schedule_proposal") == (
        MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION
    )

    r_over = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json=_propose_payload(8),
        headers=_auth(op_token),
    )
    assert r_over.status_code == 409, r_over.text
    assert r_over.json()["detail"] == _SCHEDULE_LIMIT_DETAIL
    # 拒否されたリクエストは書き込まれていない（件数が増えていない）。
    assert await _count_kind(db_session, txn_uuid, "schedule_proposal") == (
        MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION
    )
    # ログの書式が壊れていないこと（引数の数が合わないと logging は例外を出さずに
    # 崩れるため、実際に文言として出ることまで確認する）。
    assert any("提示上限に到達" in record.getMessage() for record in caplog.records)


# ──────────────────────────── チャットの件数上限（当事者ごと） ────────────────────────────


async def test_text_message_409_at_limit_per_party(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.WARNING, logger="app.api.v1.endpoints.transactions")
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "msg_limit_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "msg_limit_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    txn_uuid = uuid.UUID(txn_id)

    for message in _seed_messages(
        txn_uuid, count=MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION - 1, sender_type="operator",
    ):
        db_session.add(message)
    await db_session.commit()

    r_ok = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "上限ちょうどの発言"},
        headers=_auth(op_token),
    )
    assert r_ok.status_code == 201, r_ok.text

    r_over = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "上限超過の発言"},
        headers=_auth(op_token),
    )
    assert r_over.status_code == 409, r_over.text
    assert r_over.json()["detail"] == _MESSAGE_LIMIT_DETAIL
    # ログの書式が壊れていないこと（引数の数が合わないと logging は例外を出さずに
    # 崩れるため、実際に文言として出ることまで確認する）。管理者ではない送信者
    # なので by_admin=False になる。
    assert any(
        "送信上限に到達" in record.getMessage() and "by_admin=False" in record.getMessage()
        for record in caplog.records
    )
    # 拒否されたリクエストは書き込まれていない（依頼者が送る前に確認する）。
    assert await _count_kind(db_session, txn_uuid, "text") == (
        MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION
    )

    # 当事者ごとに数えるため、依頼者はまだ送信できる。
    r_user = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "依頼者からの発言"},
        headers=_auth(user_token),
    )
    assert r_user.status_code == 201, r_user.text


async def test_non_text_kind_does_not_count_toward_text_limit(
    client: AsyncClient, db_session: AsyncSession
):
    """schedule_proposal / system 等 text 以外の kind は text 上限に数えない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "msg_kind_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "msg_kind_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    txn_uuid = uuid.UUID(txn_id)

    # text の上限と同数の非 text 行を積んでも、text 側のカウントには影響しない。
    for message in _seed_messages(
        txn_uuid,
        count=MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION,
        sender_type="operator",
        kind="schedule_proposal",
    ):
        db_session.add(message)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "text以外の行が多くても送れる"},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text


async def test_closed_transaction_returns_transaction_closed_even_at_text_limit(
    client: AsyncClient, db_session: AsyncSession
):
    """終了済み取引では、text が上限に達していても従来の transaction_closed が先に返る。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "msg_closed_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "msg_closed_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    txn_uuid = uuid.UUID(txn_id)

    for message in _seed_messages(
        txn_uuid, count=MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION, sender_type="operator",
    ):
        db_session.add(message)
    txn = await db_session.get(Transaction, txn_uuid)
    assert txn is not None
    txn.status = "cancelled"
    await db_session.commit()

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "終了済み取引への発言"},
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "transaction_closed"


async def test_closed_transaction_returns_transaction_closed_even_at_schedule_limit(
    client: AsyncClient, db_session: AsyncSession
):
    """終了済み取引では、提示が上限に達していても従来の transaction_closed が先に返る
    （_assert_txn_open が件数チェックより先に評価されるため）。
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "sched_closed_user@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "sched_closed_op@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)
    txn_uuid = uuid.UUID(txn_id)

    for message in _seed_messages(
        txn_uuid,
        count=MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION,
        sender_type="operator",
        kind="schedule_proposal",
    ):
        db_session.add(message)
    txn = await db_session.get(Transaction, txn_uuid)
    assert txn is not None
    txn.status = "cancelled"
    await db_session.commit()

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json=_propose_payload(7),
        headers=_auth(op_token),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "transaction_closed"


# ──────────────────────────── レート制限（アカウント軸・全取引合計） ────────────────────────────


async def test_message_send_rate_limited_returns_429_before_db_lookup(
    db_session: AsyncSession,
):
    test_app = create_test_app(db_session)
    limiter = _rate_limiter_for_tests()
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "rl_msg_user@example.com")
        op_token, _ = await _verified_operator(
            client, db_session, admin_token, "rl_msg_op@example.com"
        )
        _, txn_id = await _create_transaction(client, user_token, op_token)

        for _ in range(2):
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "テスト送信"},
                headers=_auth(user_token),
            )
            assert r.status_code == 201, r.text

        r_blocked = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "3件目"},
            headers=_auth(user_token),
        )
        assert r_blocked.status_code == 429
        assert "Retry-After" in r_blocked.headers
        assert r_blocked.json() == {"detail": _MESSAGE_SEND_RATE_LIMIT_MSG}

        # 業者（別アカウント）はまだ送信できる（アカウント軸はアカウントごとに独立）。
        r_op = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "業者からの発言"},
            headers=_auth(op_token),
        )
        assert r_op.status_code == 201, r_op.text

        # 上限到達後は、存在しない取引IDへの送信も404ではなく429になる
        # （hit_accountが重いDB参照（_get_txn）より前に呼ばれている証拠）。
        r_missing = await client.post(
            f"/api/v1/transactions/{uuid.uuid4()}/messages",
            json={"body": "存在しない取引"},
            headers=_auth(user_token),
        )
        assert r_missing.status_code == 429


async def test_schedule_propose_rate_limited_independent_of_message_send(
    db_session: AsyncSession,
):
    test_app = create_test_app(db_session)
    limiter = _rate_limiter_for_tests()
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "rl_sched_user@example.com")
        op_token, _ = await _verified_operator(
            client, db_session, admin_token, "rl_sched_op@example.com"
        )
        _, txn_id = await _create_transaction(client, user_token, op_token)

        r_ok = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/propose",
            json=_propose_payload(7),
            headers=_auth(op_token),
        )
        assert r_ok.status_code == 201, r_ok.text

        r_blocked = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/propose",
            json=_propose_payload(8),
            headers=_auth(op_token),
        )
        assert r_blocked.status_code == 429
        assert "Retry-After" in r_blocked.headers
        assert r_blocked.json() == {"detail": _SCHEDULE_PROPOSE_RATE_LIMIT_MSG}

        # 提示のバケットが枯渇していても、チャット送信は独立したバケットのため送れる。
        r_chat = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "提示の上限到達後でもチャットは送れる"},
            headers=_auth(op_token),
        )
        assert r_chat.status_code == 201, r_chat.text


async def test_schedule_accept_rate_limited_returns_429_before_db_lookup(
    db_session: AsyncSession,
):
    """accept（業者の提示からの確定）もアカウント軸でレート制限される。

    上限（テストでは1回）に達すると、成功・失敗を問わず次の呼び出しは 429 になる。
    hit_account はハンドラ冒頭（重い _get_txn より前）にあるため、存在しない取引・提示の
    id でも 404 ではなく 429 になる。
    """
    test_app = create_test_app(db_session)
    limiter = _rate_limiter_for_tests(schedule_propose_max=5, schedule_accept_max=1)
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "rl_accept_user@example.com")
        op_token, _ = await _verified_operator(
            client, db_session, admin_token, "rl_accept_op@example.com"
        )
        _, txn_id = await _create_transaction(client, user_token, op_token)

        r_propose = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/propose",
            json=_propose_payload(7),
            headers=_auth(op_token),
        )
        assert r_propose.status_code == 201, r_propose.text
        proposal_id = r_propose.json()["id"]

        r_ok = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/proposals/{proposal_id}/accept",
            json={"candidate_index": 0},
            headers=_auth(user_token),
        )
        assert r_ok.status_code == 200, r_ok.text

        r_blocked = await client.post(
            f"/api/v1/transactions/{uuid.uuid4()}/schedule/proposals/{uuid.uuid4()}/accept",
            json={"candidate_index": 0},
            headers=_auth(user_token),
        )
        assert r_blocked.status_code == 429
        assert "Retry-After" in r_blocked.headers
        assert r_blocked.json() == {"detail": _SCHEDULE_ACCEPT_RATE_LIMIT_MSG}


# ──────────────────────────── レート制限（非当事者・管理者、security review Info-2） ────────────────────────────


async def test_non_party_rate_limited_independently_and_owner_bucket_untouched(
    db_session: AsyncSession,
):
    """取引と無関係な第三者（別の依頼者）が他人の取引へ送信を試みても、
    hit_account はハンドラ冒頭（_assert_party より前）に呼ばれるため、403 で
    拒否されるリクエストも第三者自身のアカウント軸バケットで数えられる。
    取引の依頼者本人のバケットは別キー（``f"user:{依頼者のid}"``）のため消費されない。
    """
    test_app = create_test_app(db_session)
    limiter = _rate_limiter_for_tests(message_send_max=2)
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        admin_token = await _make_admin(client, db_session)
        owner_token = await _signup_user(client, "np_owner@example.com")
        op_token, _ = await _verified_operator(
            client, db_session, admin_token, "np_op@example.com"
        )
        _, txn_id = await _create_transaction(client, owner_token, op_token)
        other_user_token = await _signup_user(client, "np_other@example.com")

        for _ in range(2):
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "なりすまし試行"},
                headers=_auth(other_user_token),
            )
            assert r.status_code == 403, r.text

        r_blocked = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "3回目のなりすまし試行"},
            headers=_auth(other_user_token),
        )
        assert r_blocked.status_code == 429

        # 取引の依頼者本人はまだ送信できる（本人のバケットは消費されていない）。
        r_owner = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "依頼者本人の発言"},
            headers=_auth(owner_token),
        )
        assert r_owner.status_code == 201, r_owner.text

        # DB に書き込まれた text は依頼者本人の1件だけ（403 は書き込まない）。
        assert await _count_kind(db_session, uuid.UUID(txn_id), "text") == 1


async def test_admin_message_counts_toward_user_party_but_rate_limited_on_admin_account(
    db_session: AsyncSession,
):
    """管理者は _assert_party で "user" 側の当事者として通る既存仕様の固定化。
    件数は sender_type 単位のため、管理者の発言は依頼者側（sender_type="user"）の
    text 件数に入る。一方レート制限のアカウント軸キーは管理者自身のアカウント
    （actor.id）になるため、依頼者本人のバケットとは独立している。
    """
    test_app = create_test_app(db_session)
    limiter = _rate_limiter_for_tests(message_send_max=2)
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "admin_msg_user@example.com")
        op_token, _ = await _verified_operator(
            client, db_session, admin_token, "admin_msg_op@example.com"
        )
        _, txn_id = await _create_transaction(client, user_token, op_token)

        for _ in range(2):
            r = await client.post(
                f"/api/v1/transactions/{txn_id}/messages",
                json={"body": "運営からの発言"},
                headers=_auth(admin_token),
            )
            assert r.status_code == 201, r.text

        r_blocked = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "3件目の運営発言"},
            headers=_auth(admin_token),
        )
        assert r_blocked.status_code == 429

        # 依頼者本人のバケットは消費されていないため、まだ送信できる。
        r_user = await client.post(
            f"/api/v1/transactions/{txn_id}/messages",
            json={"body": "依頼者本人の発言"},
            headers=_auth(user_token),
        )
        assert r_user.status_code == 201, r_user.text

        # 管理者の発言2件 + 依頼者本人の発言1件 = sender_type="user" の text は3件。
        assert (
            await _count_text_by_sender(db_session, uuid.UUID(txn_id), sender_type="user") == 3
        )


# ──────────────────────────── get_rate_limiter の配線（settings → RateLimitConfig） ────────────────────────────


def test_get_rate_limiter_wires_settings_to_config(monkeypatch) -> None:
    """get_rate_limiter が settings の4項目を正しいフィールドへ配線していることを
    確認する（4項目とも別の値にして取り違えを検出できるようにする）。

    プロセス内シングルトン（``lru_cache``）には一切触れない
    （``get_rate_limiter`` の docstring の方針どおり）。``__wrapped__`` で
    キャッシュを経由せず素の関数を直接呼ぶ。
    """
    from app.api import rate_limit_deps

    monkeypatch.setattr(
        rate_limit_deps,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            rl_message_send_account_max=7,
            rl_message_send_window_sec=61,
            rl_schedule_propose_account_max=3,
            rl_schedule_propose_window_sec=601,
        ),
    )
    limiter = rate_limit_deps.get_rate_limiter.__wrapped__()
    assert limiter.config.message_send_account == RateLimitRule(7, 61)
    assert limiter.config.schedule_propose_account == RateLimitRule(3, 601)


# ──────────────────────────── 設定（Settings のバリデーション・env var 名） ────────────────────────────


class TestChatAndScheduleRateLimitSettings:
    @pytest.mark.parametrize(
        "field",
        [
            "rl_message_send_account_max",
            "rl_message_send_window_sec",
            "rl_schedule_propose_account_max",
            "rl_schedule_propose_window_sec",
        ],
    )
    def test_zero_is_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: 0})

    def test_defaults_are_30_60_10_600(self, monkeypatch) -> None:
        # 実行環境にたまたま該当の環境変数が設定されていても既定値の検証が
        # 揺れないよう、4項目とも明示的に削除してから検証する（QA-L1）。
        for env_name in (
            "RL_MESSAGE_SEND_ACCOUNT_MAX",
            "RL_MESSAGE_SEND_WINDOW_SEC",
            "RL_SCHEDULE_PROPOSE_ACCOUNT_MAX",
            "RL_SCHEDULE_PROPOSE_WINDOW_SEC",
        ):
            monkeypatch.delenv(env_name, raising=False)
        settings = Settings(_env_file=None)
        assert settings.rl_message_send_account_max == 30
        assert settings.rl_message_send_window_sec == 60
        assert settings.rl_schedule_propose_account_max == 10
        assert settings.rl_schedule_propose_window_sec == 600

    @pytest.mark.parametrize(
        "env_name, attr",
        [
            ("RL_MESSAGE_SEND_ACCOUNT_MAX", "rl_message_send_account_max"),
            ("RL_MESSAGE_SEND_WINDOW_SEC", "rl_message_send_window_sec"),
            ("RL_SCHEDULE_PROPOSE_ACCOUNT_MAX", "rl_schedule_propose_account_max"),
            ("RL_SCHEDULE_PROPOSE_WINDOW_SEC", "rl_schedule_propose_window_sec"),
        ],
    )
    def test_reads_from_documented_env_var_name(
        self, monkeypatch, env_name: str, attr: str
    ) -> None:
        """env_prefix が無いため環境変数名はフィールド名の大文字化と一致する
        （tests/test_main.py の RENDER_GIT_COMMIT と同じ回帰確認パターン）。"""
        monkeypatch.setenv(env_name, "45")
        settings = Settings(_env_file=None)
        assert getattr(settings, attr) == 45


@pytest.mark.asyncio
async def test_schedule_confirm_shares_the_accept_rate_limit_bucket(db_session: AsyncSession):
    """confirm（/schedule）も「日程の確定」の枠（アカウント軸）を共有して 429 になる（security review L-1）。

    検証エラーの連打で自分の取引の行ロックを取り続け、業者の propose や cancel を待たせられないようにする。
    """
    test_app = create_test_app(db_session)
    limiter = _rate_limiter_for_tests(schedule_propose_max=5, schedule_accept_max=1)
    test_app.dependency_overrides[get_rate_limiter] = lambda: limiter

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "rl_confirm_user@example.com")
        op_token, _ = await _verified_operator(
            client, db_session, admin_token, "rl_confirm_op@example.com"
        )
        _, txn_id = await _create_transaction(client, user_token, op_token)
        visit_day = (date.today() + timedelta(days=7)).isoformat()
        bad = {"visit_date": visit_day, "visit_time_slot": "固定5種に無い文字列"}

        r_first = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/confirm", json=bad, headers=_auth(user_token)
        )
        assert r_first.status_code == 422, r_first.text  # 検証エラーも数える
        r_second = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/confirm", json=bad, headers=_auth(user_token)
        )
        assert r_second.status_code == 429, r_second.text


@pytest.mark.asyncio
async def test_schedule_ten_candidates_and_last_index_boundary(db_session: AsyncSession):
    """境界: ちょうど 10 件の提示は 201、その末尾（candidate_index=9）の accept は 200（上限側の取り違え検知）。"""
    test_app = create_test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        admin_token = await _make_admin(client, db_session)
        user_token = await _signup_user(client, "boundary_user@example.com")
        op_token, _ = await _verified_operator(
            client, db_session, admin_token, "boundary_op@example.com"
        )
        _, txn_id = await _create_transaction(client, user_token, op_token)
        candidates = [
            {
                "date": (date.today() + timedelta(days=7 + i)).isoformat(),
                "start": "09:00",
                "end": "12:00",
            }
            for i in range(10)
        ]
        r_propose = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/propose",
            json={"candidates": candidates},
            headers=_auth(op_token),
        )
        assert r_propose.status_code == 201, r_propose.text
        r_accept = await client.post(
            f"/api/v1/transactions/{txn_id}/schedule/proposals/{r_propose.json()['id']}/accept",
            json={"candidate_index": 9},
            headers=_auth(user_token),
        )
        assert r_accept.status_code == 200, r_accept.text
