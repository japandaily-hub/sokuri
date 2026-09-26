"""PostgreSQL 実機での同時実行チェック（行ロック / 部分一意索引 / 冪等制約の実証）。

SQLite（pytest）では ``SELECT ... FOR UPDATE`` が **no-op** のため、第6〜8周で
追加した直列化（``app/services/case_lock.py``）と 0028/0029 の一意制約は
「実装したが効いていることを一度も観測していない」状態だった。本スクリプトは
Docker で立てた実 PostgreSQL に実マイグレーションを当てた環境へ HTTP 経由で
同時リクエストを撃ち込み、**API の応答コード**と **DB の実行後状態**の両方で
不変条件を検証する（既存の pytest = SQLite には一切影響しない独立ツール）。

前提（手順の正本は docs/ops/e2e.md「PG 同時実行チェック」）:
  1. docker run -d --name kdz-pg -e POSTGRES_PASSWORD=kdz -e POSTGRES_DB=kdz \
       -p 55432:5432 postgres:16
  2. cd backend && PYTHONUTF8=1 \
       DATABASE_URL=postgresql+asyncpg://postgres:kdz@127.0.0.1:55432/kdz \
       .venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head
  3. .venv/Scripts/python.exe scripts/run_pg_e2e.py   （uvicorn を :8001 に起動）
  4. .venv/Scripts/python.exe scripts/pg_concurrency_check.py

環境変数:
  KDZ_API_BASE  既定 http://127.0.0.1:8001   （/api/v1 は本スクリプトが付与）
  KDZ_PG_DSN    既定 postgresql://postgres:kdz@127.0.0.1:55432/kdz （asyncpg 直結）
  KDZ_ROUNDS    既定 3                       （各シナリオの反復回数）

再実行可能性: アカウント・案件はすべて実行ごとの ``RUN_ID`` 付きで新規作成するため、
同じ DB に対して何度でも流せる（後片付け不要。DB ごと ``docker rm -f kdz-pg`` で捨てる）。

終了コード: 0=全シナリオ PASS / 1=不変条件違反あり / 2=環境不備（API/DB 未起動等）。
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import asyncpg
import httpx

API_BASE = os.environ.get("KDZ_API_BASE", "http://127.0.0.1:8001").rstrip("/")
V1 = f"{API_BASE}/api/v1"
PG_DSN = os.environ.get("KDZ_PG_DSN", "postgresql://postgres:kdz@127.0.0.1:55432/kdz")
ROUNDS = int(os.environ.get("KDZ_ROUNDS", "3"))

#: run_pg_e2e.py が ADMIN_EMAILS に載せる固定の運営アカウント。
ADMIN_EMAIL = "pgcheck-admin@example.com"
PASSWORD = "PgCheck-Pass-2026"

RUN_ID = uuid.uuid4().hex[:8]


# ──────────────────────────── 結果の器 ────────────────────────────
@dataclass
class Scenario:
    """1シナリオの集計。``failures`` が空なら PASS。"""

    key: str
    title: str
    codes: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def check(self, ok: bool, message: str) -> None:
        if not ok:
            self.failures.append(message)

    @property
    def passed(self) -> bool:
        return not self.failures


class ApiError(RuntimeError):
    """セットアップ段の想定外応答（シナリオ判定ではなく環境不備として扱う）。"""


# ──────────────────────────── HTTP ヘルパ ────────────────────────────
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def codes(responses: list[httpx.Response]) -> list[int]:
    return sorted(r.status_code for r in responses)


def must(r: httpx.Response, *ok: int) -> dict[str, Any]:
    if r.status_code not in ok:
        raise ApiError(f"{r.request.method} {r.request.url} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


async def volley(*factories: Any) -> list[httpx.Response]:
    """各コルーチンファクトリを**同一の合図**で一斉発火させる（接続も個別に張る）。

    ``factories`` は「``httpx.AsyncClient`` を受け取り Response を返す coroutine 関数」。
    クライアントを共有すると HTTP/1.1 のコネクション数で暗黙に直列化されうるため、
    タスクごとに独立クライアントを張ってから gate を待つ。
    """
    gate = asyncio.Event()

    async def wrapped(fn: Any) -> httpx.Response:
        async with httpx.AsyncClient(timeout=60) as client:
            await gate.wait()
            return await fn(client)

    tasks = [asyncio.create_task(wrapped(f)) for f in factories]
    await asyncio.sleep(0.05)  # 全タスクを gate.wait() まで進めてから解放する
    gate.set()
    return list(await asyncio.gather(*tasks))


async def signup_user(c: httpx.AsyncClient, email: str, name: str) -> tuple[str, dict[str, Any]]:
    """依頼者/運営アカウントを作成（既存なら login）して (token, user) を返す。

    ``AuthTokenResponse.user`` に ``id`` と ``role`` が入るため、別途 /users/me を
    叩く必要はない（``/users/me`` は GET 未定義でサブリソースのみ）。
    """
    r = await c.post(f"{V1}/auth/signup", json={"email": email, "password": PASSWORD, "name": name})
    if r.status_code == 409:
        d = must(await c.post(f"{V1}/auth/login", json={"email": email, "password": PASSWORD}), 200)
    else:
        d = must(r, 201)
    return d["access_token"], d.get("user") or {}


async def new_invite(c: httpx.AsyncClient, admin_token: str) -> str:
    return must(await c.post(f"{V1}/admin/invites", json={}, headers=auth(admin_token)), 201)["code"]


async def new_operator(c: httpx.AsyncClient, admin_token: str, label: str) -> tuple[str, str]:
    """入札できる（vendor_status="active"）業者を新規作成して (token, id) を返す。

    招待コード経由でも signup 直後は pending のため（2026-09-25）、許可証画像の提出と
    運営の承認（許可証未提出だと 409）まで通す。
    """
    body = {
        "company_name": f"同時実行検証業者 {label}",
        "email": f"pgop-{RUN_ID}-{label}@example.com",
        "password": PASSWORD,
        "license_number": "第301234567890号",
        "agreed": True,
        "invite_code": await new_invite(c, admin_token),
    }
    d = must(await c.post(f"{V1}/auth/operator/signup", json=body), 201)
    token, op_id = d["access_token"], d["operator"]["id"]
    license_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
    must(
        await c.post(
            f"{V1}/operator/license-image",
            files={"file": ("license.png", license_png, "image/png")},
            headers=auth(token),
        ),
        200,
    )
    must(await c.patch(f"{V1}/admin/operators/{op_id}/verify", json={"verified": True}, headers=auth(admin_token)), 200)
    return token, op_id


async def new_case(c: httpx.AsyncClient, user_token: str) -> str:
    """写真なしの最小案件を作る（AI 解析の成否は本チェックの不変条件に無関係）。"""
    payload: dict[str, Any] = {
        "purpose": "引っ越し",
        "prefecture": "東京都",
        "city": "世田谷区",
        "address_detail": "1-2-3 同時実行ハイツ 201",
        "housing_type": "マンション",
        "floor_plan": "2LDK",
        "items": [],
        "photos": [],
    }
    return must(await c.post(f"{V1}/cases", json=payload, headers=auth(user_token)), 201)["id"]


async def new_bid(c: httpx.AsyncClient, op_token: str, case_id: str, amount: int) -> str:
    r = await c.post(
        f"{V1}/cases/{case_id}/bids",
        json={"amount": amount, "message": "同時実行検証の入札です。"},
        headers=auth(op_token),
    )
    return must(r, 201)["id"]


async def new_transaction(
    c: httpx.AsyncClient, admin_token: str, user_token: str, label: str
) -> tuple[str, str]:
    """成約を1件作って (transaction_id, operator_token) を返す。"""
    op_token, _ = await new_operator(c, admin_token, label)
    case_id = await new_case(c, user_token)
    bid_id = await new_bid(c, op_token, case_id, 20000)
    txn = must(
        await c.post(f"{V1}/cases/{case_id}/bids/{bid_id}/select", headers=auth(user_token)), 201
    )
    return txn["id"], op_token


async def new_completed_transaction(c: httpx.AsyncClient, user_token: str, op_token: str) -> str:
    """指定の業者で成約を1件作り、依頼者の完了確定まで進めて transaction_id を返す（口コミを投稿できる状態）。

    完了確定は日程の確定を要しない（tests の _completed_transaction と同じ経路）。同じ業者の取引を
    複数作るため、呼ぶたびに業者を新規作成する new_transaction とは別に置く。
    """
    case_id = await new_case(c, user_token)
    bid_id = await new_bid(c, op_token, case_id, 20000)
    txn = must(
        await c.post(f"{V1}/cases/{case_id}/bids/{bid_id}/select", headers=auth(user_token)), 201
    )
    must(await c.post(f"{V1}/transactions/{txn['id']}/complete", headers=auth(user_token)), 200)
    return txn["id"]


async def new_review(
    c: httpx.AsyncClient, token: str, txn_id: str, verdict: str, comment: str
) -> str:
    body = {"transaction_id": txn_id, "verdict": verdict, "comment": comment}
    return must(await c.post(f"{V1}/reviews", json=body, headers=auth(token)), 201)["id"]


# ──────────────────────────── DB ヘルパ ────────────────────────────
def parse_ts(value: str | None) -> datetime | None:
    """API 応答の ISO 8601 の日時（末尾 Z を含む）を aware な datetime にする（asyncpg の値と比べる用）。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


async def review_hidden_columns(
    pg: asyncpg.Connection, review_id: str
) -> tuple[datetime | None, str | None, str | None]:
    """口コミの (hidden_at, hidden_reason, hidden_by_admin_id)。実施者 ID は API の表記（文字列）に揃える。"""
    row = await pg.fetchrow(
        "SELECT hidden_at, hidden_reason, hidden_by_admin_id FROM reviews WHERE id = $1",
        uuid.UUID(review_id),
    )
    by_admin = row["hidden_by_admin_id"]
    return row["hidden_at"], row["hidden_reason"], (str(by_admin) if by_admin is not None else None)


async def operator_review_counts(
    pg: asyncpg.Connection, op_id: str
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """業者の (good_count, improve_count, review_count) の（保存値, 数え直し）。

    数え直しの母集団は services/review_stats.py と同じ「依頼者→業者かつ非表示でない」口コミ。
    """
    stored = await pg.fetchrow(
        "SELECT good_count, improve_count, review_count FROM operators WHERE id = $1",
        uuid.UUID(op_id),
    )
    recount = await pg.fetchrow(
        "SELECT count(*) FILTER (WHERE r.verdict = 'good') AS good,"
        " count(*) FILTER (WHERE r.verdict = 'improve') AS improve, count(*) AS total"
        " FROM reviews r JOIN transactions t ON t.id = r.transaction_id"
        " JOIN bids b ON b.id = t.bid_id"
        " WHERE b.operator_id = $1 AND r.reviewer_type = 'user' AND r.hidden_at IS NULL",
        uuid.UUID(op_id),
    )
    return tuple(stored), tuple(recount)


# ──────────────────────────── シナリオ本体 ────────────────────────────
async def s1_select_bid_race(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, user_token: str, sc: Scenario
) -> None:
    """(1) 同一案件への同時 select_bid（2業者）→ 成約は1件のみ・他方は 409。"""
    for i in range(ROUNDS):
        op_a, _ = await new_operator(c, admin_token, f"s1a{i}")
        op_b, _ = await new_operator(c, admin_token, f"s1b{i}")
        case_id = await new_case(c, user_token)
        bid_a = await new_bid(c, op_a, case_id, 30000)
        bid_b = await new_bid(c, op_b, case_id, 45000)

        def select(bid_id: str) -> Any:
            async def _call(cc: httpx.AsyncClient) -> httpx.Response:
                return await cc.post(
                    f"{V1}/cases/{case_id}/bids/{bid_id}/select", headers=auth(user_token)
                )

            return _call

        rs = await volley(select(bid_a), select(bid_b))
        n_txn = await pg.fetchval(
            "SELECT count(*) FROM transactions WHERE case_id = $1", uuid.UUID(case_id)
        )
        n_selected = await pg.fetchval(
            "SELECT count(*) FROM bids WHERE case_id = $1 AND status = 'selected'",
            uuid.UUID(case_id),
        )
        sc.codes.append(f"r{i}: {codes(rs)}")
        sc.facts.append(f"r{i}: transactions={n_txn} selected_bids={n_selected}")
        sc.check(codes(rs) == [201, 409], f"r{i}: 応答が [201,409] でない: {codes(rs)}")
        sc.check(n_txn == 1, f"r{i}: 成約が {n_txn} 件（期待 1）")
        sc.check(n_selected == 1, f"r{i}: selected 入札が {n_selected} 件（期待 1）")


async def s2_delete_vs_select(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, user_token: str, sc: Scenario
) -> None:
    """(2) 業者退会と同時の select_bid → 退会済み業者の進行中成約が生まれない。"""
    for i in range(ROUNDS):
        op_token, op_id = await new_operator(c, admin_token, f"s2{i}")
        case_id = await new_case(c, user_token)
        bid_id = await new_bid(c, op_token, case_id, 25000)

        async def do_select(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(
                f"{V1}/cases/{case_id}/bids/{bid_id}/select", headers=auth(user_token)
            )

        async def do_delete(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.request(
                "DELETE", f"{V1}/operator/me", json={"password": PASSWORD}, headers=auth(op_token)
            )

        rs = await volley(do_select, do_delete)
        sel, dele = rs[0].status_code, rs[1].status_code
        deleted_at = await pg.fetchval(
            "SELECT deleted_at FROM operators WHERE id = $1", uuid.UUID(op_id)
        )
        n_active = await pg.fetchval(
            "SELECT count(*) FROM transactions t JOIN bids b ON b.id = t.bid_id"
            " WHERE b.operator_id = $1 AND t.status NOT IN ('completed', 'cancelled')",
            uuid.UUID(op_id),
        )
        sc.codes.append(f"r{i}: select={sel} delete={dele}")
        sc.facts.append(f"r{i}: deleted_at={'set' if deleted_at else 'null'} active_txn={n_active}")
        sc.check(
            not (sel == 201 and dele == 204),
            f"r{i}: 退会(204)と落札(201)が同時成立した（連絡不能な成約が生まれる）",
        )
        sc.check(
            deleted_at is None or n_active == 0,
            f"r{i}: 退会済み業者に進行中成約が {n_active} 件残った",
        )
        sc.check(
            sel in (201, 409) and dele in (204, 409),
            f"r{i}: 想定外の応答 select={sel} delete={dele}",
        )


async def s3_reduction_triple(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, user_token: str, sc: Scenario
) -> None:
    """(3) 減額申請の同時3連投 → pending は1件のみ（部分一意索引）。加えて逐次の上限2回も確認。"""
    for i in range(ROUNDS):
        txn_id, op_token = await new_transaction(c, admin_token, user_token, f"s3{i}")

        def reduce(n: int) -> Any:
            async def _call(cc: httpx.AsyncClient) -> httpx.Response:
                return await cc.post(
                    f"{V1}/transactions/{txn_id}/reduction",
                    json={
                        "requested_amount": 19000 - n,
                        "reason": "同時実行検証のため減額を申請します。",
                    },
                    headers=auth(op_token),
                )

            return _call

        rs = await volley(reduce(0), reduce(1), reduce(2))
        n_pending = await pg.fetchval(
            "SELECT count(*) FROM reduction_requests WHERE transaction_id = $1 AND status = 'pending'",
            uuid.UUID(txn_id),
        )
        n_rows = await pg.fetchval(
            "SELECT count(*) FROM reduction_requests WHERE transaction_id = $1", uuid.UUID(txn_id)
        )
        sc.codes.append(f"r{i}: 同時3連投 {codes(rs)}")
        sc.check(n_pending == 1, f"r{i}: pending が {n_pending} 件（期待 1・部分一意索引）")
        sc.check(codes(rs) == [201, 409, 409], f"r{i}: 応答が [201,409,409] でない: {codes(rs)}")

        # ── 逐次: 却下 → 再申請（2件目）→ 却下 → 3件目は上限 409 ──
        detail = must(await c.get(f"{V1}/transactions/{txn_id}", headers=auth(user_token)), 200)
        rid = next(r["id"] for r in detail["reduction_requests"] if r["status"] == "pending")
        must(
            await c.patch(
                f"{V1}/transactions/{txn_id}/reduction/{rid}",
                json={"action": "reject"},
                headers=auth(user_token),
            ),
            200,
        )
        r2 = await c.post(
            f"{V1}/transactions/{txn_id}/reduction",
            json={"requested_amount": 18000, "reason": "却下後の再申請（2件目）です。"},
            headers=auth(op_token),
        )
        if r2.status_code == 201:
            must(
                await c.patch(
                    f"{V1}/transactions/{txn_id}/reduction/{r2.json()['id']}",
                    json={"action": "reject"},
                    headers=auth(user_token),
                ),
                200,
            )
        r3 = await c.post(
            f"{V1}/transactions/{txn_id}/reduction",
            json={"requested_amount": 17000, "reason": "上限超過となる3件目の申請です。"},
            headers=auth(op_token),
        )
        n_rows2 = await pg.fetchval(
            "SELECT count(*) FROM reduction_requests WHERE transaction_id = $1", uuid.UUID(txn_id)
        )
        sc.facts.append(
            f"r{i}: 同時投入後 pending={n_pending} rows={n_rows} / 逐次 2件目={r2.status_code}"
            f" 3件目={r3.status_code} rows={n_rows2}"
        )
        sc.check(r2.status_code == 201, f"r{i}: 却下後の2件目が {r2.status_code}（期待 201）")
        sc.check(r3.status_code == 409, f"r{i}: 3件目が {r3.status_code}（期待 409・上限2回）")
        sc.check(n_rows2 == 2, f"r{i}: 減額申請の総数が {n_rows2} 件（期待 2）")


async def s4_cancel_double(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, user_token: str, sc: Scenario
) -> None:
    """(4) 取引キャンセルの同時2連投 → Cancellation は1行（uq_cancellations_transaction_id）。"""
    for i in range(ROUNDS):
        txn_id, _ = await new_transaction(c, admin_token, user_token, f"s4{i}")

        async def do_cancel(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(
                f"{V1}/transactions/{txn_id}/cancel",
                json={"reason": "同時実行検証のためキャンセルします。"},
                headers=auth(user_token),
            )

        rs = await volley(do_cancel, do_cancel)
        n_cxl = await pg.fetchval(
            "SELECT count(*) FROM cancellations WHERE transaction_id = $1", uuid.UUID(txn_id)
        )
        txn_status = await pg.fetchval(
            "SELECT status FROM transactions WHERE id = $1", uuid.UUID(txn_id)
        )
        sc.codes.append(f"r{i}: {codes(rs)}")
        sc.facts.append(f"r{i}: cancellations={n_cxl} txn.status={txn_status}")
        sc.check(codes(rs) == [200, 409], f"r{i}: 応答が [200,409] でない: {codes(rs)}")
        sc.check(n_cxl == 1, f"r{i}: Cancellation が {n_cxl} 行（期待 1）")
        sc.check(txn_status == "cancelled", f"r{i}: txn.status={txn_status}（期待 cancelled）")


async def s5_idempotent_case(
    c: httpx.AsyncClient, pg: asyncpg.Connection, user_id: str, user_token: str, sc: Scenario
) -> None:
    """(5) 同一 idempotency_key での POST /cases 同時2連投 → 案件は1件（201 と 200）。"""
    for i in range(ROUNDS):
        key = f"pgcheck-{RUN_ID}-{i}"
        payload = {
            "purpose": "断捨離",
            "prefecture": "東京都",
            "city": "世田谷区",
            "items": [],
            "photos": [],
            "idempotency_key": key,
        }

        async def do_create(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(f"{V1}/cases", json=payload, headers=auth(user_token))

        rs = await volley(do_create, do_create)
        n_case = await pg.fetchval(
            "SELECT count(*) FROM cases WHERE user_id = $1 AND idempotency_key = $2",
            uuid.UUID(user_id),
            key,
        )
        ids = {r.json().get("id") for r in rs if r.status_code in (200, 201)}
        sc.codes.append(f"r{i}: {codes(rs)}")
        sc.facts.append(f"r{i}: cases={n_case} distinct_ids={len(ids)}")
        sc.check(codes(rs) == [200, 201], f"r{i}: 応答が [200,201] でない: {codes(rs)}")
        sc.check(n_case == 1, f"r{i}: 案件が {n_case} 件（期待 1）")
        sc.check(len(ids) == 1, f"r{i}: 返却された案件 id が {len(ids)} 種（期待 1）")


async def s6_admin_cancel_vs_complete(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, user_token: str, sc: Scenario
) -> None:
    """(6) 運営の強制終了と依頼者の完了確定の同時実行 → 片方のみ成功・状態は矛盾しない。"""
    for i in range(ROUNDS):
        txn_id, _ = await new_transaction(c, admin_token, user_token, f"s6{i}")

        async def do_admin_cancel(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.patch(
                f"{V1}/admin/transactions/{txn_id}/cancel",
                json={"reason": "同時実行検証（運営の強制終了）"},
                headers=auth(admin_token),
            )

        async def do_complete(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(f"{V1}/transactions/{txn_id}/complete", headers=auth(user_token))

        rs = await volley(do_admin_cancel, do_complete)
        adm, cmp_ = rs[0].status_code, rs[1].status_code
        txn_status = await pg.fetchval(
            "SELECT status FROM transactions WHERE id = $1", uuid.UUID(txn_id)
        )
        n_cxl = await pg.fetchval(
            "SELECT count(*) FROM cancellations WHERE transaction_id = $1", uuid.UUID(txn_id)
        )
        sc.codes.append(f"r{i}: admin_cancel={adm} complete={cmp_}")
        sc.facts.append(f"r{i}: txn.status={txn_status} cancellations={n_cxl}")
        sc.check(
            sorted([adm, cmp_]) == [200, 409],
            f"r{i}: 片方のみ成功ではない: admin_cancel={adm} complete={cmp_}",
        )
        if adm == 200:
            sc.check(txn_status == "cancelled", f"r{i}: 運営成功だが status={txn_status}")
            sc.check(n_cxl == 1, f"r{i}: cancellations={n_cxl}（期待 1）")
        else:
            sc.check(txn_status == "completed", f"r{i}: 完了成功だが status={txn_status}")
            sc.check(n_cxl == 0, f"r{i}: 完了成功なのに cancellations={n_cxl}（期待 0）")


async def s7_last_admin_race(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, sc: Scenario
) -> None:
    """(7) 有効な管理者が2人だけのときの同時操作 → 管理者が0人にならない。

    users._is_last_active_admin（本人の退会）と admin._has_other_active_admin（降格）は、
    有効な admin の行を FOR NO KEY UPDATE（id 順）で確保してから「最後の1人か」を数える。
    ロックが効いていなければ双方が「相手が残る」と判定して 0 人になり得る3通りを撃つ:
      - withdraw_both: A と B が同時に自己退会
      - demote_each_other: A が B を、B が A を同時に降格
      - withdraw_vs_demote: A が自己退会しながら、同時に B を降格
    いずれも成功はちょうど1件で、A・B のうち有効な admin が1人以上残ること。
    「最後の2人」を作るため、A・B 以外の有効な admin はラウンド中だけ SQL で一般ユーザーへ
    外し、終了後に必ず戻す（本スクリプトの運営アカウントを含む）。
    """
    kinds = ("withdraw_both", "demote_each_other", "withdraw_vs_demote")
    for i in range(ROUNDS):
        for kind in kinds:
            a_token, a_user = await signup_user(c, f"pgadm-a-{RUN_ID}-{i}-{kind}@example.com", "管理 A")
            b_token, b_user = await signup_user(c, f"pgadm-b-{RUN_ID}-{i}-{kind}@example.com", "管理 B")
            a_id, b_id = a_user["id"], b_user["id"]
            for uid in (a_id, b_id):
                must(await c.post(f"{V1}/admin/users/{uid}/promote", headers=auth(admin_token)), 200)
            pair = [uuid.UUID(a_id), uuid.UUID(b_id)]
            # 外す対象を先に確定してから try の中で外す（UPDATE 中の中断でも finally で必ず戻す）。
            other_ids = [
                row["id"]
                for row in await pg.fetch(
                    "SELECT id FROM users WHERE role = 'admin' AND deleted_at IS NULL "
                    "AND id <> ALL($1::uuid[])",
                    pair,
                )
            ]
            try:
                await pg.execute(
                    "UPDATE users SET role = 'user' WHERE id = ANY($1::uuid[])", other_ids
                )

                def withdraw(token: str) -> Any:
                    async def _do(cc: httpx.AsyncClient) -> httpx.Response:
                        return await cc.request(
                            "DELETE",
                            f"{V1}/users/me",
                            json={"password": PASSWORD, "confirm": True},
                            headers=auth(token),
                        )

                    return _do

                def demote(token: str, target_id: str) -> Any:
                    async def _do(cc: httpx.AsyncClient) -> httpx.Response:
                        return await cc.post(
                            f"{V1}/admin/users/{target_id}/demote", headers=auth(token)
                        )

                    return _do

                if kind == "withdraw_both":
                    rs = await volley(withdraw(a_token), withdraw(b_token))
                elif kind == "demote_each_other":
                    rs = await volley(demote(a_token, b_id), demote(b_token, a_id))
                else:
                    rs = await volley(withdraw(a_token), demote(a_token, b_id))
                statuses = [r.status_code for r in rs]
                active = await pg.fetchval(
                    "SELECT count(*) FROM users WHERE role = 'admin' AND deleted_at IS NULL "
                    "AND id = ANY($1::uuid[])",
                    pair,
                )
                sc.codes.append(f"r{i} {kind}: {statuses}")
                sc.facts.append(f"r{i} {kind}: A・B のうち有効な admin={active}")
                # 成功がちょうど1件なら、残る管理者は必ず1人（0 人なら直列化の破綻、2 人なら
                # 成功したはずの退会・降格が反映されていない）。
                sc.check(active == 1, f"r{i} {kind}: 残った管理者が {active} 人（{statuses}）")
                sc.check(
                    statuses.count(200) == 1,
                    f"r{i} {kind}: 成功がちょうど1件ではない（{statuses}）",
                )
                sc.check(
                    all(s in (200, 401, 403, 409) for s in statuses),
                    f"r{i} {kind}: 想定外の応答（{statuses}）",
                )
            finally:
                # 先に外した admin を戻してから、生き残った A・B を一般ユーザーへ戻す（常に admin が
                # 1人以上いる順序。検証用の固定パスワードの admin を DB に残さない）。
                if other_ids:
                    await pg.execute(
                        "UPDATE users SET role = 'admin' WHERE id = ANY($1::uuid[])", other_ids
                    )
                await pg.execute(
                    "UPDATE users SET role = 'user' WHERE id = ANY($1::uuid[]) "
                    "AND deleted_at IS NULL",
                    pair,
                )


async def s8_review_hide_race(
    c: httpx.AsyncClient,
    pg: asyncpg.Connection,
    admin_token: str,
    admin_id: str,
    user_token: str,
    sc: Scenario,
) -> None:
    """(8) 運営の口コミ削除（PATCH /admin/reviews/{id}/hide）の同時実行 → 状態の変化は1回だけで
    中途半端な状態が残らず、業者の件数（good_count / improve_count / review_count）が数え直しと一致する。

    hide_review は reviews の行を FOR UPDATE で確保してから「既に同じ状態か」を判定し（冪等）、依頼者→
    業者の口コミなら recalc_operator_review_stats が operators の行を FOR UPDATE で確保してから数え直す。
    SQLite（pytest）ではどちらも no-op のため、同じ業者に「終始表示中の伸びしろ（基準）」と「削除対象の
    よかった」を置き、次の4通りを撃つ:
      - hide_both: 削除対象を運営 A・B が別の理由で同時に削除 → 両方 200・3列が片方の運営の組（理由と
        実施者）で揃い、両方の応答の hidden_at が DB と一致（後発が上書きしていない）・件数は1回だけ減る
      - restore_both: 削除済みの口コミの「元に戻す」を A・B が同時に → 両方 200・3列とも NULL・件数が戻る
      - hide_vs_restore: A の削除と B の元に戻すを同時に（奇数ラウンドは B が削除済みの状態から）→ 両方
        200・最終状態は「3列とも A の組」か「3列とも NULL」のどちらか・件数は最終状態の数え直しと一致
      - post_vs_hide: 同じ業者の別取引への口コミ投稿（POST /reviews）と削除対象の削除を同時に → 201 と
        200・件数は両方を反映した値（業者の行ロックが無いと、片方の数え直しが他方の結果を上書きする）
    件数は数え直し（services/review_stats.py と同じ母集団）と期待値の両方で確かめる。運営 B はこの
    シナリオの間だけ admin にし、終了時に一般ユーザーへ戻す（S7 と同じく検証用の固定パスワードの admin を
    DB に残さない）。
    """
    # 理由は NFKC 正規化（_sanitize_free_text）で変わらない文字だけにする（DB の値と文字列で比べるため）。
    reason_a = "同時実行検証による運営Aの削除"
    reason_b = "同時実行検証による運営Bの削除"
    # 期待する件数 (good_count, improve_count, review_count)。
    shown = (1, 1, 2)  # 基準の伸びしろ＋削除対象のよかった
    hidden_only = (0, 1, 1)  # 基準の伸びしろだけ（削除対象は削除済み）
    posted = (0, 2, 2)  # 基準の伸びしろ＋同時投稿の伸びしろ（削除対象は削除済み）
    admin_b_token, admin_b = await signup_user(c, f"pgrv-admin-b-{RUN_ID}@example.com", "運営 次郎")
    admin_b_id = admin_b["id"]

    def state(cols: tuple[datetime | None, str | None, str | None]) -> str:
        """hidden_at・hidden_reason・hidden_by_admin_id の状態。揃って NULL＝visible、揃って設定＝
        hidden(A|B)（理由と実施者がどちらの運営の組か。別々の要求から来ていれば 混在）、それ以外＝partial。
        """
        filled = [value is not None for value in cols]
        if not any(filled):
            return "visible"
        if not all(filled):
            return "partial"
        pairs = {(reason_a, admin_id): "A", (reason_b, admin_b_id): "B"}
        return f"hidden({pairs.get((cols[1], cols[2]), '混在')})"

    def hide(token: str, review_id: str, hidden: bool, reason: str | None = None) -> Any:
        async def _call(cc: httpx.AsyncClient) -> httpx.Response:
            body: dict[str, Any] = {"hidden": hidden}
            if reason is not None:
                body["reason"] = reason
            return await cc.patch(
                f"{V1}/admin/reviews/{review_id}/hide", json=body, headers=auth(token)
            )

        return _call

    try:
        must(await c.post(f"{V1}/admin/users/{admin_b_id}/promote", headers=auth(admin_token)), 200)
        for i in range(ROUNDS):
            op_token, op_id = await new_operator(c, admin_token, f"s8{i}")
            base_txn = await new_completed_transaction(c, user_token, op_token)
            target_txn = await new_completed_transaction(c, user_token, op_token)
            post_txn = await new_completed_transaction(c, user_token, op_token)
            await new_review(c, user_token, base_txn, "improve", "同時実行検証の基準の口コミです。")
            target = await new_review(
                c, user_token, target_txn, "good", "同時実行検証の削除対象の口コミです。"
            )
            stored, recount = await operator_review_counts(pg, op_id)
            sc.check(
                stored == recount == shown,
                f"r{i} 準備: 件数 {stored}・数え直し {recount}（期待 {shown}）",
            )

            # ── hide_both: 同じ口コミの削除を A・B が別の理由で同時に ──
            rs = await volley(
                hide(admin_token, target, True, reason_a),
                hide(admin_b_token, target, True, reason_b),
            )
            cols = await review_hidden_columns(pg, target)
            stored, recount = await operator_review_counts(pg, op_id)
            reported = {parse_ts(r.json().get("hidden_at")) for r in rs if r.status_code == 200}
            sc.codes.append(f"r{i} hide_both: {codes(rs)}")
            sc.facts.append(f"r{i} hide_both: 状態={state(cols)} 件数={stored} 数え直し={recount}")
            sc.check(codes(rs) == [200, 200], f"r{i} hide_both: 応答が [200,200] でない: {codes(rs)}")
            sc.check(
                state(cols) in ("hidden(A)", "hidden(B)"),
                f"r{i} hide_both: 3列が片方の運営の組で揃っていない: {state(cols)}",
            )
            # 後発は先発のコミットを待ってから「削除済み」を読み、何も書かずに先発の hidden_at を返す。
            # 両方が書いていれば（行ロックが効いていない）応答の hidden_at が食い違うか DB と一致しない。
            # hidden_at はサーバの時計の値のため、時計が粗い環境（ローカルの Windows で約 1ms を実測）では
            # 2回の書き込みが同じ値になり見逃しうる。検出力の前提はマイクロ秒単位の CI（Linux）。
            sc.check(
                reported == {cols[0]},
                f"r{i} hide_both: 応答の hidden_at {sorted(map(str, reported))} が DB の {cols[0]}"
                " と一致しない（状態の変化が2回）",
            )
            sc.check(
                stored == recount == hidden_only,
                f"r{i} hide_both: 件数 {stored}・数え直し {recount}（期待 {hidden_only}）",
            )

            # ── restore_both: 削除済みの口コミの「元に戻す」を A・B が同時に ──
            rs = await volley(hide(admin_token, target, False), hide(admin_b_token, target, False))
            cols = await review_hidden_columns(pg, target)
            stored, recount = await operator_review_counts(pg, op_id)
            sc.codes.append(f"r{i} restore_both: {codes(rs)}")
            sc.facts.append(f"r{i} restore_both: 状態={state(cols)} 件数={stored} 数え直し={recount}")
            sc.check(
                codes(rs) == [200, 200], f"r{i} restore_both: 応答が [200,200] でない: {codes(rs)}"
            )
            sc.check(state(cols) == "visible", f"r{i} restore_both: 3列とも NULL でない: {state(cols)}")
            sc.check(
                stored == recount == shown,
                f"r{i} restore_both: 件数 {stored}・数え直し {recount}（期待 {shown}）",
            )

            # ── hide_vs_restore: A の削除と B の元に戻すを同時に ──
            # 奇数ラウンドは B が削除済みの状態から始め、「元に戻す→削除」の順に変わる経路も通す。
            start = "visible"
            if i % 2:
                must(await hide(admin_b_token, target, True, reason_b)(c), 200)
                start = "hidden(B)"
            rs = await volley(
                hide(admin_token, target, True, reason_a), hide(admin_b_token, target, False)
            )
            hide_code, restore_code = rs[0].status_code, rs[1].status_code
            cols = await review_hidden_columns(pg, target)
            stored, recount = await operator_review_counts(pg, op_id)
            # 件数の母集団は hidden_at だけで決まる（数え直しと同じ基準）。
            expected = shown if cols[0] is None else hidden_only
            sc.codes.append(
                f"r{i} hide_vs_restore({start}から): hide={hide_code} restore={restore_code}"
            )
            sc.facts.append(
                f"r{i} hide_vs_restore({start}から): 状態={state(cols)} 件数={stored}"
                f" 数え直し={recount}"
            )
            sc.check(
                hide_code == 200 and restore_code == 200,
                f"r{i} hide_vs_restore: 応答が両方 200 でない: hide={hide_code} restore={restore_code}",
            )
            # 直列化されていれば後に処理された側の要求どおりに終わる: 削除が後なら3列とも A の組、元に戻す
            # が後なら3列とも NULL（B の削除済みから始めても B の元に戻すが必ず効くため、B の組は残らない）。
            sc.check(
                state(cols) in ("hidden(A)", "visible"),
                f"r{i} hide_vs_restore: 最終状態が「A の組で3列とも設定」「3列とも NULL」のどちらでも"
                f"ない: {state(cols)}",
            )
            sc.check(
                stored == recount == expected,
                f"r{i} hide_vs_restore: 件数 {stored}・数え直し {recount}（期待 {expected}）",
            )

            # ── post_vs_hide: 同じ業者の別取引への口コミ投稿と、削除対象の削除を同時に ──
            must(await hide(admin_token, target, False)(c), 200)  # 表示中に揃える（冪等）

            async def do_post(cc: httpx.AsyncClient) -> httpx.Response:
                return await cc.post(
                    f"{V1}/reviews",
                    json={
                        "transaction_id": post_txn,
                        "verdict": "improve",
                        "comment": "同時実行検証の同時投稿の口コミです。",
                    },
                    headers=auth(user_token),
                )

            rs = await volley(do_post, hide(admin_token, target, True, reason_a))
            post_code, hide_code = rs[0].status_code, rs[1].status_code
            cols = await review_hidden_columns(pg, target)
            stored, recount = await operator_review_counts(pg, op_id)
            sc.codes.append(f"r{i} post_vs_hide: post={post_code} hide={hide_code}")
            sc.facts.append(f"r{i} post_vs_hide: 状態={state(cols)} 件数={stored} 数え直し={recount}")
            sc.check(
                post_code == 201 and hide_code == 200,
                f"r{i} post_vs_hide: 応答が post=201・hide=200 でない: post={post_code} hide={hide_code}",
            )
            sc.check(
                state(cols) == "hidden(A)",
                f"r{i} post_vs_hide: 削除が A の組で3列揃っていない: {state(cols)}",
            )
            # 業者の行ロックが無いと、投稿側（削除前の状態で数える）と削除側（投稿前の状態で数える）の
            # どちらかの数え直しが後勝ちで残り、(1, 2, 3) か (0, 1, 1) になる。
            sc.check(
                stored == recount == posted,
                f"r{i} post_vs_hide: 件数 {stored}・数え直し {recount}（期待 {posted}）",
            )
    finally:
        # 運営 B を一般ユーザーへ戻す（S7 と同じく検証用の固定パスワードの admin を DB に残さない。
        # 昇格や途中の API が失敗しても必ず戻す）。
        await pg.execute("UPDATE users SET role = 'user' WHERE id = $1", uuid.UUID(admin_b_id))


# ──────────────────────────── エントリポイント ────────────────────────────
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


async def run() -> int:
    # S7 は接続先 DB の admin を一時的に一般ユーザーへ外すため、使い捨ての検証 DB（ローカル・
    # CI のサービスコンテナ）以外では動かさない（本番や共有 DB の運営者の権限を外さない）。
    api_host = urlsplit(API_BASE).hostname
    pg_host = urlsplit(PG_DSN).hostname
    if api_host not in _LOOPBACK_HOSTS or pg_host not in _LOOPBACK_HOSTS:
        print(
            f"[env] 接続先がローカルではありません（API={api_host} / PG={pg_host}）。"
            "本スクリプトは使い捨ての検証 DB 専用です。",
            file=sys.stderr,
        )
        return 2

    try:
        async with httpx.AsyncClient(timeout=10) as probe:
            health = await probe.get(f"{API_BASE}/health")
        if health.status_code != 200:
            print(f"[env] {API_BASE}/health が {health.status_code} を返しました。", file=sys.stderr)
            return 2
    except httpx.HTTPError as exc:
        print(f"[env] API へ接続できません（{API_BASE}）: {exc}", file=sys.stderr)
        return 2

    try:
        pg = await asyncpg.connect(PG_DSN)
    except Exception as exc:  # noqa: BLE001  接続失敗の例外型はドライバ依存で広い
        print(f"[env] PostgreSQL へ接続できません（{PG_DSN}）: {exc}", file=sys.stderr)
        return 2
    # 前回の実行が S7 の途中で強制終了され、運営アカウントが admin から外れたまま残っていても
    # 再実行できるよう戻しておく（未作成なら何もしない。初回は signup 時の自動付与で admin になる）。
    await pg.execute(
        "UPDATE users SET role = 'admin' WHERE lower(email) = lower($1) "
        "AND deleted_at IS NULL AND role <> 'admin'",
        ADMIN_EMAIL,
    )

    scenarios = [
        Scenario("S1", "同一案件への同時 select_bid（2業者）"),
        Scenario("S2", "業者退会と同時の select_bid"),
        Scenario("S3", "減額申請の同時3連投＋逐次上限"),
        Scenario("S4", "取引キャンセルの同時2連投"),
        Scenario("S5", "同一 idempotency_key の POST /cases 同時2連投"),
        Scenario("S6", "運営の強制終了と依頼者 complete の同時実行"),
        Scenario("S7", "最後の管理者2人の同時退会・相互降格・退会と降格の同時実行"),
        Scenario("S8", "運営の口コミ削除の同時2連投・元に戻すの同時2連投・削除と元に戻す・投稿と削除の同時実行"),
    ]
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            admin_token, admin_user = await signup_user(c, ADMIN_EMAIL, "運営 太郎")
            if admin_user.get("role") != "admin":
                print(
                    f"[env] {ADMIN_EMAIL} が admin ではありません（ADMIN_EMAILS を確認）。",
                    file=sys.stderr,
                )
                return 2
            user_token, seller = await signup_user(c, f"pgseller-{RUN_ID}@example.com", "出品 花子")
            user_id = seller["id"]

            await s1_select_bid_race(c, pg, admin_token, user_token, scenarios[0])
            await s2_delete_vs_select(c, pg, admin_token, user_token, scenarios[1])
            await s3_reduction_triple(c, pg, admin_token, user_token, scenarios[2])
            await s4_cancel_double(c, pg, admin_token, user_token, scenarios[3])
            await s5_idempotent_case(c, pg, user_id, user_token, scenarios[4])
            await s6_admin_cancel_vs_complete(c, pg, admin_token, user_token, scenarios[5])
            # S8 は運営アカウントの admin 権限を使う（2人目の運営は S8 の中で昇格・降格する）ため、
            # S7 より前に流す。
            await s8_review_hide_race(
                c, pg, admin_token, admin_user["id"], user_token, scenarios[7]
            )
            # S7 は運営アカウントを一時的に admin から外すため、必ず最後に流す。
            await s7_last_admin_race(c, pg, admin_token, scenarios[6])
    except ApiError as exc:
        print(f"[env] セットアップに失敗しました: {exc}", file=sys.stderr)
        return 2
    finally:
        await pg.close()

    print(f"\n=== PG 同時実行チェック結果（run_id={RUN_ID} / rounds={ROUNDS}） ===")
    failed = 0
    for sc in scenarios:
        print(f"\n[{sc.key}] {'PASS' if sc.passed else 'FAIL'} — {sc.title}")
        for line in sc.codes:
            print(f"    codes  {line}")
        for line in sc.facts:
            print(f"    db     {line}")
        for line in sc.failures:
            print(f"    !!     {line}")
        failed += 0 if sc.passed else 1
    print(f"\n合計: {len(scenarios) - failed}/{len(scenarios)} シナリオ PASS")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
