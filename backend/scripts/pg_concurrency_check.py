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
from typing import Any

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
    """招待コード付き（＝ vendor_status="active"）の業者を新規作成して (token, id) を返す。"""
    body = {
        "company_name": f"同時実行検証業者 {label}",
        "email": f"pgop-{RUN_ID}-{label}@example.com",
        "password": PASSWORD,
        "license_number": "第301234567890号",
        "agreed": True,
        "invite_code": await new_invite(c, admin_token),
    }
    d = must(await c.post(f"{V1}/auth/operator/signup", json=body), 201)
    return d["access_token"], d["operator"]["id"]


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


# ──────────────────────────── エントリポイント ────────────────────────────
async def run() -> int:
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

    scenarios = [
        Scenario("S1", "同一案件への同時 select_bid（2業者）"),
        Scenario("S2", "業者退会と同時の select_bid"),
        Scenario("S3", "減額申請の同時3連投＋逐次上限"),
        Scenario("S4", "取引キャンセルの同時2連投"),
        Scenario("S5", "同一 idempotency_key の POST /cases 同時2連投"),
        Scenario("S6", "運営の強制終了と依頼者 complete の同時実行"),
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
