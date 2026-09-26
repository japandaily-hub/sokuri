"""運営の口コミ管理（GET /admin/reviews・PATCH /admin/reviews/{id}/hide）の統合テスト。

設計の正本: .agent-state/review-verdict/DESIGN-admin.md（段3 backend・2026-09-25）。

- 認可: 未ログインは 401、一般ユーザーは 403（一覧・削除とも）。
- 一覧: 状態（表示中／削除済み／すべて）・向き・評価・業者 ID の絞込とその組み合わせ。total は絞込後、
  counts は絞込に関わらない全件。q は UUID として読めれば口コミ ID・取引 ID の完全一致（部分 UUID は
  一致しない）、読めなければ業者名の部分一致（% と _ はエスケープ）。業者 ID と業者名の q を同時に
  指定すると AND。limit は 1〜200・q は 100 字以内。
  同時刻の行もページを跨いで重複・欠落しない。業者が退会（匿名化）しても行は出る。依頼者のメールは出さない。
  SQL の本数は行数によらず一定（N+1 なし）。
- 削除: 理由必須（欠落・空白・201 字・連絡先入りは 422 で何も書かない）。hidden_by_admin_id を記録し、
  二度押しは最初の値（人・時刻・理由）を保持して再計算しない。元に戻すで3列とも NULL（reason は無視）。
  依頼者→業者の口コミは件数・最新口コミ・公開プロフィールが増減し、業者→依頼者の口コミは業者の集計を
  変えない（再計算もしない）。応答 ReviewOut に hidden_reason・hidden_by_admin_id は出ない。
  存在しない ID は 404。
- 監査ログに本文・理由・q の中身を書かない。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.operator import Operator
from app.db.models.transaction import Review
from app.db.models.user import User
from app.services.review_stats import recalc_operator_review_stats
from tests.test_katadzuke_api import (
    _auth,
    _completed_transaction,
    _make_admin,
    _post_review,
    _signup_user,
    _verified_operator,
    create_test_app,
)

_ADMIN_LOGGER = "app.api.v1.endpoints.admin"
# tests.test_katadzuke_api._make_admin が作る運営のメール。
_ADMIN_EMAIL = "admin@katadzuke.jp"
_RECALC_PATH = "app.api.v1.endpoints.admin.recalc_operator_review_stats"
# 一覧の1件の項目（web の AdminReviewListItem と同じ契約。増減させるときは web と合わせる）。
_ITEM_KEYS = {
    "id",
    "transaction_id",
    "reviewer_type",
    "verdict",
    "comment",
    "created_at",
    "hidden_at",
    "hidden_reason",
    "hidden_by_admin_id",
    "operator_id",
    "company_name",
}
# 削除／元に戻すの応答（ReviewOut・当事者向けと同じ形）。理由と実施者は含めない。
_REVIEW_OUT_KEYS = {
    "id",
    "transaction_id",
    "reviewer_type",
    "verdict",
    "comment",
    "created_at",
    "hidden_at",
}


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    test_app = create_test_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


async def _admin_id(db_session: AsyncSession, email: str = _ADMIN_EMAIL) -> uuid.UUID:
    admin_id = await db_session.scalar(select(User.id).where(User.email == email))
    assert admin_id is not None
    return admin_id


async def _second_admin(client: AsyncClient, db_session: AsyncSession) -> tuple[str, uuid.UUID]:
    """2人目の運営（二度押し・同時押しで「最初に削除した人」が残ることの確認用）。"""
    email, password = "admin2_reviews@katadzuke.jp", "adminpass456"
    admin = User(email=email, password_hash=hash_password(password), name="管理者2", role="admin")
    db_session.add(admin)
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], admin.id


async def _hide(
    client: AsyncClient, token: str, review_id: str, *, hidden: bool, reason: str | None = None
):
    payload: dict = {"hidden": hidden}
    if reason is not None:
        payload["reason"] = reason
    return await client.patch(
        f"/api/v1/admin/reviews/{review_id}/hide", json=payload, headers=_auth(token)
    )


async def _list(client: AsyncClient, token: str, **params) -> dict:
    r = await client.get("/api/v1/admin/reviews", params=params, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _ids(body: dict) -> list[str]:
    return [item["id"] for item in body["items"]]


async def _hidden_columns(db_session: AsyncSession, review_id: str) -> tuple:
    """DB 上の (hidden_at, hidden_reason, hidden_by_admin_id)。列の SELECT なので常に DB の値。"""
    row = (
        await db_session.execute(
            select(Review.hidden_at, Review.hidden_reason, Review.hidden_by_admin_id).where(
                Review.id == uuid.UUID(review_id)
            )
        )
    ).one()
    return tuple(row)


async def _scenario(client: AsyncClient, db_session: AsyncSession) -> dict:
    """運営・依頼者・業者2社と口コミ4件（うち1件は削除済み）を用意する。

    - 業者 A「口コミ管理片付け株式会社」: 取引1（依頼者→業者 good・業者→依頼者 improve）、
      取引2（依頼者→業者 improve・運営が削除済み）
    - 業者 B「別の片付け有限会社」: 取引3（依頼者→業者 good）
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "rv_admin_user@example.com")
    op_a_token, op_a = await _verified_operator(
        client, db_session, admin_token, "rv_admin_op_a@example.com", "口コミ管理片付け株式会社"
    )
    op_b_token, op_b = await _verified_operator(
        client, db_session, admin_token, "rv_admin_op_b@example.com", "別の片付け有限会社"
    )
    txn1 = await _completed_transaction(client, user_token, op_a_token)
    txn2 = await _completed_transaction(client, user_token, op_a_token)
    txn3 = await _completed_transaction(client, user_token, op_b_token)
    r1_user = await _post_review(
        client, user_token, {"transaction_id": txn1, "verdict": "good", "comment": "搬出が丁寧でした"}
    )
    r1_op = await _post_review(client, op_a_token, {"transaction_id": txn1, "verdict": "improve"})
    r2_user = await _post_review(
        client, user_token, {"transaction_id": txn2, "verdict": "improve", "comment": "到着が遅れました"}
    )
    r3_user = await _post_review(client, user_token, {"transaction_id": txn3, "verdict": "good"})
    # 投稿は同じ秒に収まりうる（created_at の既定は SQLite では秒単位の CURRENT_TIMESTAMP）ため、
    # 並び順と「最新の口コミ」が決定的になるよう1分ずつずらす（r1_user が最も古く r3_user が最も新しい）。
    # 次の削除で業者 A の集計が再計算されるので、最新の口コミもこの日時で決まる。
    for minute, review in enumerate((r1_user, r1_op, r2_user, r3_user)):
        await db_session.execute(
            update(Review)
            .where(Review.id == uuid.UUID(review["id"]))
            .values(created_at=datetime(2026, 9, 20, 10, minute))
        )
    await db_session.commit()
    r = await _hide(client, admin_token, r2_user["id"], hidden=True, reason="その他")
    assert r.status_code == 200, r.text
    return {
        "admin_token": admin_token,
        "user_token": user_token,
        "op_a_token": op_a_token,
        "op_a": op_a,
        "op_b": op_b,
        "txn1": txn1,
        "txn2": txn2,
        "txn3": txn3,
        "r1_user": r1_user["id"],
        "r1_op": r1_op["id"],
        "r2_user": r2_user["id"],
        "r3_user": r3_user["id"],
    }


# ──────────────────────────── 認可 ────────────────────────────


async def test_admin_reviews_require_admin(client: AsyncClient, db_session: AsyncSession):
    """未ログインは 401、一般ユーザー・業者は運営の口コミ管理を使えない（一覧・削除とも）。"""
    s = await _scenario(client, db_session)
    body = {"hidden": True, "reason": "誹謗中傷・名誉毀損のおそれ"}

    r = await client.get("/api/v1/admin/reviews")
    assert r.status_code == 401
    r = await client.get("/api/v1/admin/reviews", headers=_auth(s["user_token"]))
    assert r.status_code == 403
    r = await client.get("/api/v1/admin/reviews", headers=_auth(s["op_a_token"]))
    assert r.status_code in (401, 403)

    r = await client.patch(f"/api/v1/admin/reviews/{s['r1_user']}/hide", json=body)
    assert r.status_code == 401
    r = await client.patch(
        f"/api/v1/admin/reviews/{s['r1_user']}/hide", json=body, headers=_auth(s["user_token"])
    )
    assert r.status_code == 403
    r = await client.patch(
        f"/api/v1/admin/reviews/{s['r1_user']}/hide", json=body, headers=_auth(s["op_a_token"])
    )
    assert r.status_code in (401, 403)
    # 何も書かれていない。
    assert await _hidden_columns(db_session, s["r1_user"]) == (None, None, None)


# ──────────────────────────── 一覧 ────────────────────────────


async def test_admin_reviews_list_filters_total_and_counts(
    client: AsyncClient, db_session: AsyncSession
):
    """各絞込とその組み合わせ。total は絞込後、counts は絞込に関わらない全件。項目は契約どおり。"""
    s = await _scenario(client, db_session)
    token = s["admin_token"]
    all_counts = {"all": 4, "visible": 3, "hidden": 1}

    body = await _list(client, token)
    assert set(body) == {"items", "total", "counts"}
    assert body["total"] == 4 and body["counts"] == all_counts
    assert all(set(item) == _ITEM_KEYS for item in body["items"])
    # 依頼者のメールは応答に出さない。
    r = await client.get("/api/v1/admin/reviews", headers=_auth(token))
    assert "rv_admin_user@example.com" not in r.text
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[s["r1_user"]]["comment"] == "搬出が丁寧でした"
    assert by_id[s["r1_user"]]["operator_id"] == s["op_a"]
    assert by_id[s["r1_user"]]["company_name"] == "口コミ管理片付け株式会社"
    assert by_id[s["r1_user"]]["transaction_id"] == s["txn1"]
    assert by_id[s["r1_op"]]["reviewer_type"] == "operator"
    assert by_id[s["r3_user"]]["company_name"] == "別の片付け有限会社"
    hidden_item = by_id[s["r2_user"]]
    assert hidden_item["hidden_at"] is not None and hidden_item["hidden_reason"] == "その他"
    assert hidden_item["hidden_by_admin_id"] == str(await _admin_id(db_session))
    assert by_id[s["r1_user"]]["hidden_by_admin_id"] is None

    # (絞込, 期待する口コミ)。counts はどの絞込でも全件の内訳のまま。
    cases = [
        ({"visibility": "visible"}, {s["r1_user"], s["r1_op"], s["r3_user"]}),
        ({"visibility": "hidden"}, {s["r2_user"]}),
        ({"visibility": "all"}, {s["r1_user"], s["r1_op"], s["r2_user"], s["r3_user"]}),
        ({"reviewer_type": "operator"}, {s["r1_op"]}),
        ({"reviewer_type": "user"}, {s["r1_user"], s["r2_user"], s["r3_user"]}),
        ({"verdict": "good"}, {s["r1_user"], s["r3_user"]}),
        ({"verdict": "improve"}, {s["r1_op"], s["r2_user"]}),
        ({"operator_id": s["op_b"]}, {s["r3_user"]}),
        ({"operator_id": s["op_a"]}, {s["r1_user"], s["r1_op"], s["r2_user"]}),
        (
            {"operator_id": s["op_a"], "visibility": "visible", "reviewer_type": "user"},
            {s["r1_user"]},
        ),
        ({"operator_id": str(uuid.uuid4())}, set()),
    ]
    for params, expected in cases:
        body = await _list(client, token, **params)
        assert set(_ids(body)) == expected, params
        assert body["total"] == len(expected), params
        assert body["counts"] == all_counts, params

    # 型の外の値は 422。
    for params in (
        {"visibility": "deleted"},
        {"reviewer_type": "admin"},
        {"verdict": "bad"},
        {"operator_id": "not-a-uuid"},
    ):
        r = await client.get("/api/v1/admin/reviews", params=params, headers=_auth(token))
        assert r.status_code == 422, params


async def test_admin_reviews_q_matches_ids_exactly_and_escapes_company_name(
    client: AsyncClient, db_session: AsyncSession
):
    """q: UUID は口コミ ID・取引 ID の完全一致（部分 UUID は一致しない）、それ以外は業者名の部分一致で
    ``%``・``_`` は文字どおりに扱う（エスケープしないと全件に一致してしまう）。"""
    s = await _scenario(client, db_session)
    token = s["admin_token"]
    await db_session.execute(
        update(Operator).where(Operator.id == uuid.UUID(s["op_a"])).values(company_name="100%片付け")
    )
    await db_session.execute(
        update(Operator).where(Operator.id == uuid.UUID(s["op_b"])).values(company_name="片_付け舎")
    )
    await db_session.commit()
    op_a_reviews = {s["r1_user"], s["r1_op"], s["r2_user"]}

    cases = [
        (s["r1_user"], {s["r1_user"]}),
        (f"  {s['r3_user']}  ", {s["r3_user"]}),  # 前後の空白は除く
        (s["r1_user"].upper(), {s["r1_user"]}),  # UUID の大文字表記も同じ ID
        (s["txn1"], {s["r1_user"], s["r1_op"]}),  # 取引 ID は双方向の2件
        (s["r1_user"][:8], set()),  # 部分 UUID は業者名の部分一致として扱われ一致しない
        (s["r1_user"][:-1], set()),
        ("%", op_a_reviews),
        ("_", {s["r3_user"]}),
        ("0%片", op_a_reviews),
        ("片付け", op_a_reviews),  # 「片_付け舎」は含まない（_ は任意の1文字ではない）
        ("存在しない業者", set()),
    ]
    for q, expected in cases:
        body = await _list(client, token, q=q)
        assert set(_ids(body)) == expected, q
        assert body["total"] == len(expected), q
        assert body["counts"] == {"all": 4, "visible": 3, "hidden": 1}, q

    # 他の絞込と組み合わせても同じく効く。
    body = await _list(client, token, q="%", visibility="visible", reviewer_type="user")
    assert _ids(body) == [s["r1_user"]]
    # 空白だけの q は絞込なし。100 字ちょうどは受け付け、101 字は 422。
    assert (await _list(client, token, q="   "))["total"] == 4
    assert (await _list(client, token, q="あ" * 100))["total"] == 0
    r = await client.get("/api/v1/admin/reviews", params={"q": "あ" * 101}, headers=_auth(token))
    assert r.status_code == 422


async def test_admin_reviews_operator_id_and_company_name_q_are_combined_with_and(
    client: AsyncClient, db_session: AsyncSession
):
    """operator_id と q（業者名の部分一致）を同時に指定すると AND で絞り込む（業者名のリンクで業者を
    絞った画面から検索欄を使う組み合わせ）。どちらか一方にだけ当たる口コミは出さない。"""
    s = await _scenario(client, db_session)
    token = s["admin_token"]
    op_a_reviews = {s["r1_user"], s["r1_op"], s["r2_user"]}

    cases = [
        # 「片付け」は業者 A・B の両方の名前に含まれる → operator_id の業者の口コミだけ。
        ({"operator_id": s["op_b"], "q": "片付け"}, {s["r3_user"]}),
        ({"operator_id": s["op_a"], "q": "片付け"}, op_a_reviews),
        # 業者名が operator_id と別の業者にだけ一致する → 0 件（OR なら両方の業者の口コミが出る）。
        ({"operator_id": s["op_b"], "q": "口コミ管理"}, set()),
        ({"operator_id": s["op_a"], "q": "別の片付け"}, set()),
        # 状態・向きの絞込を重ねても AND のまま。
        (
            {"operator_id": s["op_a"], "q": "口コミ管理", "visibility": "hidden"},
            {s["r2_user"]},
        ),
        (
            {"operator_id": s["op_a"], "q": "口コミ管理", "reviewer_type": "operator"},
            {s["r1_op"]},
        ),
    ]
    for params, expected in cases:
        body = await _list(client, token, **params)
        assert set(_ids(body)) == expected, params
        assert body["total"] == len(expected), params
        assert body["counts"] == {"all": 4, "visible": 3, "hidden": 1}, params


async def test_admin_reviews_paging_is_stable_for_same_timestamp_and_limit_is_bounded(
    client: AsyncClient, db_session: AsyncSession
):
    """同時刻の行でも created_at 降順・id 降順で決まり、ページを跨いで重複・欠落しない。limit は 1〜200。"""
    s = await _scenario(client, db_session)
    token = s["admin_token"]
    same_time = datetime(2026, 9, 25, 12, 0, 0)
    await db_session.execute(update(Review).values(created_at=same_time))
    await db_session.commit()
    all_ids = {s["r1_user"], s["r1_op"], s["r2_user"], s["r3_user"]}

    seen: list[str] = []
    for offset in (0, 2, 4):
        body = await _list(client, token, limit=2, offset=offset)
        assert body["total"] == 4
        seen.extend(_ids(body))
    assert len(seen) == 4 and set(seen) == all_ids
    assert seen == sorted(all_ids, key=lambda rid: uuid.UUID(rid), reverse=True)

    assert len(_ids(await _list(client, token, limit=200))) == 4
    assert len(_ids(await _list(client, token, limit=1))) == 1
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        r = await client.get("/api/v1/admin/reviews", params=params, headers=_auth(token))
        assert r.status_code == 422, params


async def test_admin_reviews_list_uses_constant_number_of_queries(
    client: AsyncClient, db_session: AsyncSession, db_engine
):
    """N+1 の防止: 一覧1回で reviews を読む SQL は行数によらず3本（件数・全件の内訳・本体）だけ。
    業者 ID・業者名は本体の外部結合で同時に取る（行ごとの追加 SELECT をしない）。"""
    s = await _scenario(client, db_session)
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        body = await _list(client, s["admin_token"])
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)
    assert len(body["items"]) == 4
    review_queries = [sql for sql in statements if "FROM reviews" in sql]
    assert len(review_queries) == 3, review_queries
    assert not [sql for sql in statements if "FROM operators" in sql or "FROM bids" in sql]


async def test_admin_reviews_list_keeps_rows_of_deleted_operator(
    client: AsyncClient, db_session: AsyncSession
):
    """業者が退会（運営による強制退会＝匿名化）しても、その業者の口コミの行は一覧に出る。"""
    s = await _scenario(client, db_session)
    token = s["admin_token"]
    r = await client.delete(f"/api/v1/admin/operators/{s['op_b']}", headers=_auth(token))
    assert r.status_code == 200, r.text
    deleted_at = await db_session.scalar(
        select(Operator.deleted_at).where(Operator.id == uuid.UUID(s["op_b"]))
    )
    assert deleted_at is not None

    body = await _list(client, token, operator_id=s["op_b"])
    assert _ids(body) == [s["r3_user"]]
    assert body["items"][0]["operator_id"] == s["op_b"]
    assert body["counts"]["all"] == 4 and (await _list(client, token))["total"] == 4


# ──────────────────────────── 削除／元に戻す ────────────────────────────


async def test_admin_review_hide_requires_reason_and_writes_nothing_when_rejected(
    client: AsyncClient, db_session: AsyncSession
):
    """削除は理由必須: 欠落・null・空白だけ・201 字・連絡先入りは 422 で、何も書かない。200 字ちょうどは可。"""
    s = await _scenario(client, db_session)
    token = s["admin_token"]
    for payload in (
        {"hidden": True},
        {"hidden": True, "reason": None},
        {"hidden": True, "reason": ""},
        {"hidden": True, "reason": "   "},
        {"hidden": True, "reason": "　\t\n"},
        {"hidden": True, "reason": "あ" * 201},
        {"hidden": True, "reason": "詳細は https://example.com を参照"},
        {"reason": "理由だけ"},
    ):
        r = await client.patch(
            f"/api/v1/admin/reviews/{s['r1_user']}/hide", json=payload, headers=_auth(token)
        )
        assert r.status_code == 422, (payload, r.text)
        assert await _hidden_columns(db_session, s["r1_user"]) == (None, None, None), payload

    # 上限は前後の空白を除いて数える（200 字＋前後の空白は可）。保存も空白を除いた値。
    reason = "あ" * 200
    r = await _hide(client, token, s["r1_user"], hidden=True, reason=f"  {reason}\n ")
    assert r.status_code == 200, r.text
    _, stored_reason, _ = await _hidden_columns(db_session, s["r1_user"])
    assert stored_reason == reason
    # 自由入力と同じ無害化（NFKC 正規化）を掛けて保存する。
    r = await _hide(client, token, s["r3_user"], hidden=True, reason="ＡＢＣ（宣伝）")
    assert r.status_code == 200, r.text
    assert (await _hidden_columns(db_session, s["r3_user"]))[1] == "ABC(宣伝)"


async def test_admin_review_hide_records_admin_is_idempotent_and_restore_clears(
    client: AsyncClient, db_session: AsyncSession, caplog
):
    """削除で hidden_by_admin_id を記録。二度押し（別の運営・別の理由）は最初の値を保持して再計算しない。
    元に戻すで3列とも NULL（reason は無視）。応答に理由と実施者は出ない。ログに理由を書かない。"""
    caplog.set_level(logging.INFO, logger=_ADMIN_LOGGER)
    s = await _scenario(client, db_session)
    admin_id = await _admin_id(db_session)
    admin2_token, admin2_id = await _second_admin(client, db_session)
    review_id = s["r1_user"]
    first_reason = "第三者の個人情報を含むため"

    r = await _hide(client, s["admin_token"], review_id, hidden=True, reason=first_reason)
    assert r.status_code == 200, r.text
    assert set(r.json()) == _REVIEW_OUT_KEYS
    first_hidden_at = r.json()["hidden_at"]
    assert first_hidden_at is not None
    first_row = await _hidden_columns(db_session, review_id)
    assert first_row[1:] == (first_reason, admin_id)

    # 二度押し（別の運営・別の理由）: 何も書かず再計算もせず 200。最初の人・時刻・理由を保持する。
    with patch(_RECALC_PATH, new=AsyncMock()) as recalc:
        r = await _hide(client, admin2_token, review_id, hidden=True, reason="その他")
    assert r.status_code == 200, r.text
    assert r.json()["hidden_at"] == first_hidden_at
    assert set(r.json()) == _REVIEW_OUT_KEYS
    recalc.assert_not_awaited()
    assert await _hidden_columns(db_session, review_id) == first_row

    # 元に戻す（reason は中身も長さも見ずに無視）: 3列とも NULL。
    r = await _hide(client, admin2_token, review_id, hidden=False, reason="無視される理由" * 40)
    assert r.status_code == 200, r.text
    assert r.json()["hidden_at"] is None and set(r.json()) == _REVIEW_OUT_KEYS
    assert await _hidden_columns(db_session, review_id) == (None, None, None)

    # 表示中の口コミを元に戻す（二度押し）: 何もせず 200・再計算なし。
    with patch(_RECALC_PATH, new=AsyncMock()) as recalc:
        r = await _hide(client, s["admin_token"], review_id, hidden=False)
    assert r.status_code == 200, r.text
    recalc.assert_not_awaited()
    assert await _hidden_columns(db_session, review_id) == (None, None, None)

    # 再び削除すると、今削除した人（2人目）で記録し直す。
    r = await _hide(client, admin2_token, review_id, hidden=True, reason="送信防止措置の申出")
    assert r.status_code == 200, r.text
    assert (await _hidden_columns(db_session, review_id))[1:] == ("送信防止措置の申出", admin2_id)

    hide_logs = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == _ADMIN_LOGGER and rec.getMessage().startswith("admin_review_hide ")
    ]
    op_a = uuid.UUID(s["op_a"])
    assert hide_logs[-5:] == [
        f"admin_review_hide admin={admin_id} review={review_id} operator={op_a} hidden=True changed=True",
        f"admin_review_hide admin={admin2_id} review={review_id} operator={op_a} hidden=True changed=False",
        f"admin_review_hide admin={admin2_id} review={review_id} operator={op_a} hidden=False changed=True",
        f"admin_review_hide admin={admin_id} review={review_id} operator={op_a} hidden=False changed=False",
        f"admin_review_hide admin={admin2_id} review={review_id} operator={op_a} hidden=True changed=True",
    ]
    all_logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert first_reason not in all_logs and "無視される理由" not in all_logs


async def test_admin_review_hide_changes_operator_stats_only_for_user_reviews(
    client: AsyncClient, db_session: AsyncSession
):
    """依頼者→業者の口コミの削除／元に戻すは件数・最新口コミ・公開プロフィールを増減させる。
    業者→依頼者の口コミは業者の集計に入らないため、削除しても変わらず再計算もしない。"""
    s = await _scenario(client, db_session)
    token, op_a = s["admin_token"], s["op_a"]

    async def _public() -> tuple:
        r = await client.get(f"/api/v1/vendors/{op_a}")
        assert r.status_code == 200, r.text
        data = r.json()
        r = await client.get("/api/v1/vendors")
        row = next(v for v in r.json() if v["operator_id"] == op_a)
        return (
            (data["good_count"], data["improve_count"], data["review_count"]),
            [review["id"] for review in data["reviews"]],
            row["latest_review_comment"],
        )

    # 取引2の口コミ（伸びしろ）は _scenario で削除済み。
    assert await _public() == ((1, 0, 1), [s["r1_user"]], "搬出が丁寧でした")

    r = await _hide(client, token, s["r2_user"], hidden=False)
    assert r.status_code == 200, r.text
    counts, review_ids, latest = await _public()
    assert counts == (1, 1, 2) and set(review_ids) == {s["r1_user"], s["r2_user"]}
    assert latest == "到着が遅れました"

    r = await _hide(client, token, s["r2_user"], hidden=True, reason="取引と関係ない内容・宣伝")
    assert r.status_code == 200, r.text
    assert await _public() == ((1, 0, 1), [s["r1_user"]], "搬出が丁寧でした")

    # 業者→依頼者: 業者の集計は不変・再計算しない（削除自体は記録される）。
    with patch(_RECALC_PATH, new=AsyncMock(wraps=recalc_operator_review_stats)) as recalc:
        r = await _hide(client, token, s["r1_op"], hidden=True, reason="その他")
        assert r.status_code == 200, r.text
        r = await _hide(client, token, s["r1_op"], hidden=False)
        assert r.status_code == 200, r.text
    recalc.assert_not_awaited()
    assert await _public() == ((1, 0, 1), [s["r1_user"]], "搬出が丁寧でした")


async def test_admin_review_hide_unknown_or_malformed_id(
    client: AsyncClient, db_session: AsyncSession
):
    """存在しない口コミは 404、UUID でない ID は 422。"""
    admin_token = await _make_admin(client, db_session)
    r = await _hide(client, admin_token, str(uuid.uuid4()), hidden=True, reason="その他")
    assert r.status_code == 404
    assert r.json()["detail"] == "Review not found."
    r = await _hide(client, admin_token, "not-a-uuid", hidden=True, reason="その他")
    assert r.status_code == 422


async def test_admin_reviews_list_log_has_no_query_or_body(
    client: AsyncClient, db_session: AsyncSession, caplog
):
    """一覧のログは絞込の種類と件数だけ（q の中身・本文・理由を書かない）。"""
    caplog.set_level(logging.INFO, logger=_ADMIN_LOGGER)
    s = await _scenario(client, db_session)
    admin_id = await _admin_id(db_session)
    caplog.clear()

    await _list(client, s["admin_token"], q="秘密の業者名", visibility="hidden", verdict="improve")
    await _list(client, s["admin_token"], operator_id=s["op_a"])
    logs = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == _ADMIN_LOGGER and "口コミ一覧" in rec.getMessage()
    ]
    assert logs == [
        "admin: 口コミ一覧を取得しました - visibility=hidden reviewer_type=None verdict=improve"
        f" operator_filter=False has_q=True count=0 total=0 admin_id={admin_id}",
        "admin: 口コミ一覧を取得しました - visibility=all reviewer_type=None verdict=None"
        f" operator_filter=True has_q=False count=3 total=3 admin_id={admin_id}",
    ]
    all_logs = "\n".join(rec.getMessage() for rec in caplog.records)
    for secret in ("秘密の業者名", "搬出が丁寧でした", "到着が遅れました", s["op_a"]):
        assert secret not in all_logs
