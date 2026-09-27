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
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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

#: 日本時間（API は訪問日の範囲・期限を日本時間で判定する。app.services.visit_schedule.JST と同じ定義。
#: 本スクリプトは app を import しない独立ツールのため自前で持つ）。
JST = timezone(timedelta(hours=9), name="Asia/Tokyo")


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


def ascii_json(obj: Any) -> bytes:
    """孤立サロゲートを含みうる payload を安全に送るための ASCII エスケープ JSON バイト列。

    httpx の ``json=`` 引数は内部で ``json.dumps(..., ensure_ascii=False)`` してから
    UTF-8 へエンコードするため、孤立サロゲート（例: ``chr(0xD800)``）を含む値は送信前に
    ``UnicodeEncodeError`` になる（実測。backend/tests/test_display_text_guard.py の
    ``_post_json_allow_surrogates`` と同じ理由）。``ensure_ascii=True`` で ``\\uXXXX``
    形式へエスケープした ASCII バイト列として送れば、サーバー側の ``json.loads`` が
    同じ孤立サロゲートへ復元した状態で受け取れる。呼び出し側で
    ``headers={**auth(token), "content-type": "application/json"}`` を明示すること
    （``content=`` は httpx が Content-Type を自動付与しないため）。
    """
    return json.dumps(obj, ensure_ascii=True).encode("ascii")


def probe(
    sc: Scenario,
    label: str,
    r: httpx.Response,
    *,
    expected_type: str,
    expected_loc: list[Any] | None = None,
    msg_contains: str | None = None,
) -> None:
    """拒否レスポンスの形状（422・detail[0].type・loc・msg）を検査して sc に記録する。

    ``!= 500`` を個別に check することで、422 になったこと自体の検証と「500 に
    ならなかった」ことの検証を取り違えない（422 を期待して 500 が返っても
    ``r.status_code == 422`` の check だけでは「500 でない」ことの明示的な失格に
    ならず、他の failures に埋もれて読み落とされうるため）。
    """
    sc.codes.append(f"{label}: {r.status_code}")
    sc.check(r.status_code != 500, f"{label}: 500 になった - {r.text[:200]}")
    sc.check(r.status_code == 422, f"{label}: 422 でない: {r.status_code} - {r.text[:200]}")
    if r.status_code != 422:
        return
    detail = r.json().get("detail") or []
    sc.check(bool(detail), f"{label}: detail が空")
    if not detail:
        return
    entry = detail[0]
    sc.check(
        entry.get("type") == expected_type,
        f"{label}: type が {entry.get('type')!r}（期待 {expected_type!r}）",
    )
    if expected_loc is not None:
        sc.check(
            entry.get("loc") == expected_loc,
            f"{label}: loc が {entry.get('loc')!r}（期待 {expected_loc!r}）",
        )
    if msg_contains is not None:
        sc.check(
            msg_contains in entry.get("msg", ""),
            f"{label}: msg に {msg_contains!r} を含まない: {entry.get('msg')!r}",
        )


def detail_of(r: httpx.Response) -> Any:
    """応答の detail（文字列・dict のどちらも。JSON でない・detail が無ければ None）。"""
    try:
        body = r.json()
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None


def detail_code(r: httpx.Response) -> str | None:
    """dict 形式の detail の code（文字列の detail・detail 無しは None）。"""
    detail = detail_of(r)
    return detail.get("code") if isinstance(detail, dict) else None


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


async def s10_signup_duplicate_email_race(pg: asyncpg.Connection, sc: Scenario) -> None:
    """(10) 同じメールアドレスでの signup 同時2連投（依頼者・業者）→ [201, 409]・アカウントは1件。

    事前確認（SELECT）は2本ともすり抜けうるため、後発は一意制約（uq_users_email・
    uq_operators_contact_email）に当たる。2026-09-27 まではここが未処理例外（500）で、例外の DETAIL に
    メールアドレスが載ってログ・運営アラートへ残った。事前確認と同じ 409・同じ文言になること。
    """
    taken = "このメールアドレスは既に登録されています。"
    for i in range(ROUNDS):
        user_email = f"pgsignup-{RUN_ID}-{i}@example.com"

        async def do_user_signup(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(
                f"{V1}/auth/signup", json={"email": user_email, "password": PASSWORD, "name": "同時 登録"}
            )

        rs = await volley(do_user_signup, do_user_signup)
        n_user = await pg.fetchval("SELECT count(*) FROM users WHERE email = $1", user_email)
        details = [r.json().get("detail") for r in rs if r.status_code == 409]
        sc.codes.append(f"user r{i}: {codes(rs)}")
        sc.facts.append(f"user r{i}: users={n_user}")
        sc.check(codes(rs) == [201, 409], f"user r{i}: 応答が [201,409] でない: {codes(rs)}")
        sc.check(n_user == 1, f"user r{i}: 依頼者が {n_user} 件（期待 1）")
        sc.check(details == [taken], f"user r{i}: 409 の文言が事前確認と違う: {details}")

        operator_email = f"pgsignup-op-{RUN_ID}-{i}@example.com"
        operator_body = {
            "company_name": f"同時登録検証業者 {i}",
            "email": operator_email,
            "password": PASSWORD,
            "license_number": "第301234567890号",
            "agreed": True,
        }

        async def do_operator_signup(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(f"{V1}/auth/operator/signup", json=operator_body)

        rs = await volley(do_operator_signup, do_operator_signup)
        n_operator = await pg.fetchval(
            "SELECT count(*) FROM operators WHERE contact_email = $1", operator_email
        )
        details = [r.json().get("detail") for r in rs if r.status_code == 409]
        sc.codes.append(f"operator r{i}: {codes(rs)}")
        sc.facts.append(f"operator r{i}: operators={n_operator}")
        sc.check(codes(rs) == [201, 409], f"operator r{i}: 応答が [201,409] でない: {codes(rs)}")
        sc.check(n_operator == 1, f"operator r{i}: 業者が {n_operator} 件（期待 1）")
        sc.check(details == [taken], f"operator r{i}: 409 の文言が事前確認と違う: {details}")


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


async def s9_unsafe_input_rejected(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, user_token: str, sc: Scenario
) -> None:
    """(9) NUL・制御文字・孤立サロゲートの入力（実 PG）: 500 にならず 422・何も保存されない。

    S9 は入力検証の実 PG 回帰。他シナリオと異なり同時実行の検証ではないため、
    KDZ_ROUNDS に関係なく1周だけ流す（volley は使わない）。日程 API
    （``/schedule/propose``・``/schedule/confirm``）は使わない（別ブランチの 0046 で
    修正予定の ``messages.kind`` VARCHAR(16) 超過により、実 PG では内容に関係なく
    500 になる既知の別不具合があるため）。
    """
    txn_id, op_token = await new_transaction(c, admin_token, user_token, "s9")
    case_id = await new_case(c, user_token)
    invite_code = await new_invite(c, admin_token)
    profile = must(await c.get(f"{V1}/operator/profile", headers=auth(op_token)), 200)
    op_id = profile["operator_id"]

    # ── 陽性対照（先に）: PG 自体が本当に NUL・孤立サロゲートを拒否することを確認する。
    # 成り立たなければ「実 PG では 500 になる」という S9 の前提が崩れているため、
    # 以降の 422 確認そのものが無意味になる（前提崩れは明示的に failures へ積む）。
    try:
        await pg.fetchval("SELECT $1::text", "x" + chr(0x00))
        sc.check(False, "PC1: PG が NUL 入り text を例外なく受理した（S9 の前提崩れ）")
    except Exception as exc:  # noqa: BLE001 -- 例外型そのものが確認対象
        sc.facts.append(f"PC1: NUL は PG で {type(exc).__name__}")
    try:
        await pg.fetchval("SELECT $1::text", "x" + chr(0xD800))
        sc.check(False, "PC1: PG が孤立サロゲート入り text を例外なく受理した（S9 の前提崩れ）")
    except Exception as exc:  # noqa: BLE001
        sc.facts.append(f"PC1: 孤立サロゲートは PG で {type(exc).__name__}")

    # PC2: 改行・ZWJ 家族絵文字・国旗・タグ旗・ZWNJ・ZWSP・BOM・ソフトハイフン・0xE000・
    # U+2028 を含むメッセージ → 201 で DB の body が完全一致する（除去も拒否もされない）。
    allowed_body = (
        "よろしくお願いします" + chr(0x0A)
        + chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467)  # ZWJ家族
        + chr(0x1F1EF) + chr(0x1F1F5)  # 国旗（日本）
        + chr(0x1F3F4) + chr(0xE0067) + chr(0xE0062) + chr(0xE0065) + chr(0xE006E) + chr(0xE0067) + chr(0xE007F)  # タグ旗
        + chr(0x200C) + chr(0x200B) + chr(0xFEFF) + chr(0x00AD)  # ZWNJ・ZWSP・BOM・ソフトハイフン
        + chr(0xE000) + chr(0x2028)  # 私用領域・LINE SEPARATOR
    )
    r_pc2 = must(
        await c.post(
            f"{V1}/transactions/{txn_id}/messages",
            json={"body": allowed_body},
            headers=auth(user_token),
        ),
        201,
    )
    db_body_pc2 = await pg.fetchval(
        "SELECT body FROM messages WHERE id = $1", uuid.UUID(r_pc2["id"])
    )
    sc.check(db_body_pc2 == allowed_body, "PC2: 許可文字入りメッセージの body が DB と完全一致しない")

    # PC3: ASCII エスケープの正しいペア絵文字 → 201（孤立サロゲートに分解されない）。
    r_pc3 = must(
        await c.post(
            f"{V1}/transactions/{txn_id}/messages",
            content=ascii_json({"body": "ok" + chr(0x1F600)}),
            headers={**auth(user_token), "content-type": "application/json"},
        ),
        201,
    )
    sc.check(
        r_pc3["body"] == "ok" + chr(0x1F600), "PC3: 正しいペア絵文字の body が一致しない"
    )

    # PC4: 通常の文字での検索クエリ → 200（クエリ検査が正常系を妨げない）。
    r_pc4 = await c.get(
        f"{V1}/admin/operators", params={"q": "通常の文字"}, headers=auth(admin_token)
    )
    sc.check(r_pc4.status_code == 200, f"PC4: 通常のクエリが {r_pc4.status_code}（期待 200）")

    messages_baseline = await pg.fetchval(
        "SELECT count(*) FROM messages WHERE transaction_id = $1", uuid.UUID(txn_id)
    )
    sc.facts.append(f"陽性対照後のメッセージ件数: {messages_baseline}（期待 2）")
    sc.check(messages_baseline == 2, f"PC2・PC3 後のメッセージ件数が {messages_baseline}（期待 2）")

    # ── 拒否（すべて 422。!= 500 も個別に check） ──
    # P1-P3: body に NUL / ASCII エスケープ孤立サロゲート / 生バイト孤立サロゲート。
    r_p1 = await c.post(
        f"{V1}/transactions/{txn_id}/messages",
        json={"body": "ng" + chr(0x00)},
        headers=auth(user_token),
    )
    probe(sc, "P1", r_p1, expected_type="disallowed_character", expected_loc=["body", "body"])

    r_p2 = await c.post(
        f"{V1}/transactions/{txn_id}/messages",
        content=ascii_json({"body": "ng" + chr(0xD800)}),
        headers={**auth(user_token), "content-type": "application/json"},
    )
    probe(sc, "P2", r_p2, expected_type="disallowed_character", expected_loc=["body", "body"])

    raw_body = b'{"body": "ng' + chr(0xD800).encode("utf-8", "surrogatepass") + b'"}'
    r_p3 = await c.post(
        f"{V1}/transactions/{txn_id}/messages",
        content=raw_body,
        headers={**auth(user_token), "content-type": "application/json"},
    )
    probe(sc, "P3", r_p3, expected_type="disallowed_character", expected_loc=["body", "body"])

    # P4: キーに NUL（応答の loc は U+FFFD に置換される。値は反射しない）。
    r_p4 = await c.post(
        f"{V1}/transactions/{txn_id}/messages",
        content=ascii_json({"body": "ok", "k" + chr(0x00): 1}),
        headers={**auth(user_token), "content-type": "application/json"},
    )
    probe(
        sc,
        "P4",
        r_p4,
        expected_type="disallowed_character",
        expected_loc=["body", "k" + chr(0xFFFD)],
    )

    # P5-P7: RLO / タブ / CR は全体防御（NUL・孤立サロゲートだけが対象）を素通りし、
    # 表示用バリデータ（field_validator）が日本語文言の value_error で拒否する経路。
    for label, ch in (("P5", chr(0x202E)), ("P6", chr(0x09)), ("P7", chr(0x0D))):
        r = await c.post(
            f"{V1}/transactions/{txn_id}/messages",
            json={"body": "ng" + ch},
            headers=auth(user_token),
        )
        probe(
            sc,
            label,
            r,
            expected_type="value_error",
            msg_contains="メッセージに制御文字を含めることはできません。",
        )

    messages_after_rejections = await pg.fetchval(
        "SELECT count(*) FROM messages WHERE transaction_id = $1", uuid.UUID(txn_id)
    )
    sc.check(
        messages_after_rejections == messages_baseline,
        f"P1-P7 拒否後もメッセージ件数が {messages_after_rejections}（期待 {messages_baseline}）",
    )

    # P8・P9: POST /auth/signup（認証なし）name に NUL / 孤立サロゲート。
    email_p8 = f"s9-p8-{RUN_ID}@example.com"
    r_p8 = await c.post(
        f"{V1}/auth/signup",
        json={"email": email_p8, "password": PASSWORD, "name": "x" + chr(0x00)},
    )
    probe(sc, "P8", r_p8, expected_type="disallowed_character", expected_loc=["body", "name"])
    n_users_p8 = await pg.fetchval(
        "SELECT count(*) FROM users WHERE lower(email) = lower($1)", email_p8
    )
    sc.check(n_users_p8 == 0, f"P8: users に {n_users_p8} 件作成された（期待 0）")

    email_p9 = f"s9-p9-{RUN_ID}@example.com"
    r_p9 = await c.post(
        f"{V1}/auth/signup",
        content=ascii_json({"email": email_p9, "password": PASSWORD, "name": "x" + chr(0xD800)}),
        headers={"content-type": "application/json"},
    )
    probe(sc, "P9", r_p9, expected_type="disallowed_character", expected_loc=["body", "name"])
    n_users_p9 = await pg.fetchval(
        "SELECT count(*) FROM users WHERE lower(email) = lower($1)", email_p9
    )
    sc.check(n_users_p9 == 0, f"P9: users に {n_users_p9} 件作成された（期待 0）")

    # P10: POST /auth/operator/signup（認証なし）company_name に NUL（未使用の招待コード付き）。
    email_p10 = f"s9-p10-{RUN_ID}@example.com"
    r_p10 = await c.post(
        f"{V1}/auth/operator/signup",
        json={
            "invite_code": invite_code,
            "company_name": "x" + chr(0x00),
            "email": email_p10,
            "password": PASSWORD,
            "license_number": "第301234567890号",
            "agreed": True,
        },
    )
    probe(sc, "P10", r_p10, expected_type="disallowed_character")
    n_operators_p10 = await pg.fetchval(
        "SELECT count(*) FROM operators WHERE lower(contact_email) = lower($1)", email_p10
    )
    sc.check(n_operators_p10 == 0, f"P10: operators に {n_operators_p10} 件作成された（期待 0）")
    invite_used_at = await pg.fetchval("SELECT used_at FROM invites WHERE code = $1", invite_code)
    sc.check(invite_used_at is None, "P10: 招待コードの used_at が NULL でない（拒否後も未使用のはず）")

    # P11: POST /operator-applications（認証なし）message に NUL（他は有効）。
    email_p11 = f"s9-p11-{RUN_ID}@example.com"
    application_payload = {
        "company_name": "同時実行検証株式会社",
        "representative_name": "代表 太郎",
        "registered_address": "東京都千代田区丸の内1-1-1",
        "contact_name": "担当 花子",
        "email": email_p11,
        "phone": "03-1234-5678",
        "business_type": "corp",
        "service_area": "東京都",
        "message": "よろしくお願いします" + chr(0x00),
        "license_number": "第301234567890号",
        "bank_account": {
            "bank_name": "みずほ銀行",
            "branch_name": "東京営業部",
            "account_type": "ordinary",
            "account_number": "1234567",
            "account_holder": "ドウジジッコウケンショウ",
        },
        "agreed": True,
    }
    r_p11 = await c.post(f"{V1}/operator-applications", json=application_payload)
    probe(sc, "P11", r_p11, expected_type="disallowed_character")
    n_apps_p11 = await pg.fetchval(
        "SELECT count(*) FROM operator_applications WHERE lower(contact_email) = lower($1)",
        email_p11,
    )
    sc.check(n_apps_p11 == 0, f"P11: operator_applications に {n_apps_p11} 件作成された（期待 0）")

    # P12: POST /cases（依頼者）address_detail に ASCII エスケープ孤立サロゲート（冪等キー付き）。
    idem_key_p12 = f"s9-p12-{RUN_ID}"
    case_payload_p12 = {
        "purpose": "引っ越し",
        "prefecture": "東京都",
        "city": "世田谷区",
        "address_detail": "住所" + chr(0xD800),
        "housing_type": "マンション",
        "items": [],
        "photos": [],
        "idempotency_key": idem_key_p12,
    }
    r_p12 = await c.post(
        f"{V1}/cases",
        content=ascii_json(case_payload_p12),
        headers={**auth(user_token), "content-type": "application/json"},
    )
    probe(sc, "P12", r_p12, expected_type="disallowed_character")
    n_cases_p12 = await pg.fetchval(
        "SELECT count(*) FROM cases WHERE idempotency_key = $1", idem_key_p12
    )
    sc.check(n_cases_p12 == 0, f"P12: 冪等キー {idem_key_p12} の cases が {n_cases_p12} 件（期待 0）")

    # P13: POST /cases/{case}/bids（業者）message に NUL。
    r_p13 = await c.post(
        f"{V1}/cases/{case_id}/bids",
        json={"amount": 12_345, "message": "ng" + chr(0x00)},
        headers=auth(op_token),
    )
    probe(sc, "P13", r_p13, expected_type="disallowed_character")
    n_bids_p13 = await pg.fetchval(
        "SELECT count(*) FROM bids WHERE case_id = $1", uuid.UUID(case_id)
    )
    sc.check(n_bids_p13 == 0, f"P13: 案件 {case_id} の bids が {n_bids_p13} 件（期待 0）")

    # P14: PUT /operator/profile（業者）intro_message に NUL（事前に PUT で基準値）。
    baseline_intro = "よろしくお願いします（S9基準値）"
    profile_payload_base = {
        "areas": [],
        "categories": [],
        "strong_categories": [],
        "business_hours": "平日9時から18時",
        "intro_message": baseline_intro,
        "show_message": True,
        "accept_unsellable": False,
    }
    must(
        await c.put(f"{V1}/operator/profile", json=profile_payload_base, headers=auth(op_token)),
        200,
    )
    r_p14 = await c.put(
        f"{V1}/operator/profile",
        json={**profile_payload_base, "intro_message": "変更後" + chr(0x00)},
        headers=auth(op_token),
    )
    probe(sc, "P14", r_p14, expected_type="disallowed_character")
    intro_after = await pg.fetchval(
        "SELECT intro_message FROM operator_profiles WHERE operator_id = $1", uuid.UUID(op_id)
    )
    sc.check(
        intro_after == baseline_intro,
        f"P14: intro_message が {intro_after!r}（期待 {baseline_intro!r}）",
    )

    # P15: PATCH /admin/transactions/{txn}/cancel（運営）reason に NUL。
    r_p15 = await c.patch(
        f"{V1}/admin/transactions/{txn_id}/cancel",
        json={"reason": "強制終了" + chr(0x00)},
        headers=auth(admin_token),
    )
    probe(sc, "P15", r_p15, expected_type="disallowed_character", expected_loc=["body", "reason"])
    txn_status = await pg.fetchval(
        "SELECT status FROM transactions WHERE id = $1", uuid.UUID(txn_id)
    )
    sc.check(txn_status == "pending", f"P15: 成約の status が {txn_status!r}（期待 'pending'）")
    n_cancellations = await pg.fetchval(
        "SELECT count(*) FROM cancellations WHERE transaction_id = $1", uuid.UUID(txn_id)
    )
    sc.check(n_cancellations == 0, f"P15: cancellations が {n_cancellations} 件（期待 0）")

    # P16: GET /admin/operators?q=NUL（運営）クエリ NUL。
    r_p16 = await c.get(
        f"{V1}/admin/operators", params={"q": "x" + chr(0x00)}, headers=auth(admin_token)
    )
    probe(sc, "P16", r_p16, expected_type="disallowed_character", expected_loc=["query", "q"])


async def s11_schedule_propose_vs_accept(
    c: httpx.AsyncClient, pg: asyncpg.Connection, admin_token: str, user_token: str, sc: Scenario
) -> None:
    """(11) 日程の提示（propose）と候補からの確定（accept）の同時実行 → 結果は必ず一方に決まる
    （日程構造化 DESIGN §4・§10）。

    propose と accept は同じ行ロック（lock_transaction_rows）で直列化し、accept は「その提示の seq が
    COALESCE(MAX(CAST(meta ->> 'seq' AS INTEGER)), 0) と等しいか」で最新の提示だけを確定する。
    SQLite（pytest）ではロックが no-op で、JSON の集計も SQLite の方言になるため、実 PG で次の3通りを撃つ:
      - propose_vs_accept: 提示1の候補の accept と、提示2の propose を同時に →
        (a) accept が先: accept 200・propose 409（schedule_already_confirmed）・提示の seq は [1]・
            visiting・確定メッセージ1件
        (b) propose が先: propose 201・accept 409（schedule_proposal_superseded）・seq は [1, 2]・
            pending・確定メッセージ0件
        のどちらか（両方成功・両方失敗・それ以外の組み合わせは、ロックか seq の判定が効いていない）
      - accept_double: 最新の提示の accept を同時に2回 → [200, 409]・確定メッセージは1件・visiting・
        visit_date / visit_time_slot がサーバーの作った値（候補の日付・固定枠の表示）
      - admin_cancel_vs_accept: 運営の強制終了と accept を同時に → 強制終了は常に 200・最終状態は
        cancelled・Cancellation は1行。accept は 200（先に確定し、その後に終了）か 409（終了済みで拒否）で、
        確定メッセージの件数と一致する（ロックが無いと「cancelled を visiting へ上書き」が起きうる）
    候補日は日本時間の今日から7日後にする（当日の終わった枠・日付範囲の判定に掛からない）。
    """
    visit_day = (datetime.now(JST) + timedelta(days=7)).date().isoformat()
    # 固定枠の表示（波ダッシュは U+301C。全角チルダと取り違えないよう符号位置で組み立てる）。
    morning_slot = "9:00" + chr(0x301C) + "12:00"
    not_pending = "日程確定できる状態ではありません。"

    def propose(txn_id: str, op_token: str, start: str, end: str) -> Any:
        async def _call(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(
                f"{V1}/transactions/{txn_id}/schedule/propose",
                json={"candidates": [{"date": visit_day, "start": start, "end": end}]},
                headers=auth(op_token),
            )

        return _call

    def accept(txn_id: str, proposal_id: str) -> Any:
        async def _call(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.post(
                f"{V1}/transactions/{txn_id}/schedule/proposals/{proposal_id}/accept",
                json={"candidate_index": 0},
                headers=auth(user_token),
            )

        return _call

    async def schedule_facts(txn_id: str) -> tuple[str, list[int], int]:
        """(txn.status, 提示の seq の昇順, 確定メッセージの件数)。seq は API の集計と同じ CAST で読む。"""
        key = uuid.UUID(txn_id)
        txn_status = await pg.fetchval("SELECT status FROM transactions WHERE id = $1", key)
        seqs = [
            row["seq"]
            for row in await pg.fetch(
                "SELECT CAST(meta ->> 'seq' AS INTEGER) AS seq FROM messages"
                " WHERE transaction_id = $1 AND kind = 'schedule_proposal' ORDER BY 1",
                key,
            )
        ]
        n_confirmed = await pg.fetchval(
            "SELECT count(*) FROM messages"
            " WHERE transaction_id = $1 AND kind = 'schedule_confirmed'",
            key,
        )
        return txn_status, seqs, n_confirmed

    for i in range(ROUNDS):
        # ── propose_vs_accept: 提示1の accept と提示2の propose を同時に ──
        txn_id, op_token = await new_transaction(c, admin_token, user_token, f"s11a{i}")
        first = must(await propose(txn_id, op_token, "09:00", "12:00")(c), 201)
        rs = await volley(
            accept(txn_id, first["id"]), propose(txn_id, op_token, "12:00", "15:00")
        )
        acc, prop = rs[0].status_code, rs[1].status_code
        facts = await schedule_facts(txn_id)
        sc.codes.append(
            f"r{i} propose_vs_accept: accept={acc}({detail_code(rs[0])})"
            f" propose={prop}({detail_code(rs[1])})"
        )
        sc.facts.append(
            f"r{i} propose_vs_accept: txn.status={facts[0]} seqs={facts[1]} confirmed={facts[2]}"
        )
        accept_won = (
            acc == 200 and prop == 409 and detail_code(rs[1]) == "schedule_already_confirmed"
        )
        propose_won = (
            acc == 409 and detail_code(rs[0]) == "schedule_proposal_superseded" and prop == 201
        )
        sc.check(
            accept_won or propose_won,
            f"r{i} propose_vs_accept: 結果が一方に決まっていない: accept={acc} propose={prop}",
        )
        if accept_won:
            sc.check(
                facts == ("visiting", [1], 1),
                f"r{i} propose_vs_accept: 確定が先なのに {facts}（期待 visiting・[1]・1）",
            )
        elif propose_won:
            sc.check(
                facts == ("pending", [1, 2], 0),
                f"r{i} propose_vs_accept: 提示が先なのに {facts}（期待 pending・[1, 2]・0）",
            )

        # ── accept_double: 最新の提示の accept を同時に2回 ──
        txn_id, op_token = await new_transaction(c, admin_token, user_token, f"s11b{i}")
        proposal = must(await propose(txn_id, op_token, "09:00", "12:00")(c), 201)
        rs = await volley(accept(txn_id, proposal["id"]), accept(txn_id, proposal["id"]))
        facts = await schedule_facts(txn_id)
        visit = await pg.fetchrow(
            "SELECT visit_date, visit_time_slot FROM transactions WHERE id = $1",
            uuid.UUID(txn_id),
        )
        visit_values = (
            visit["visit_date"].isoformat() if visit["visit_date"] else None,
            visit["visit_time_slot"],
        )
        losers = [detail_of(r) for r in rs if r.status_code == 409]
        sc.codes.append(f"r{i} accept_double: {codes(rs)}")
        sc.facts.append(
            f"r{i} accept_double: txn.status={facts[0]} confirmed={facts[2]} visit={visit_values}"
        )
        sc.check(codes(rs) == [200, 409], f"r{i} accept_double: 応答が [200,409] でない: {codes(rs)}")
        sc.check(
            losers == [not_pending],
            f"r{i} accept_double: 後発の 409 の detail が {losers}（期待 {not_pending}）",
        )
        sc.check(
            facts[0] == "visiting" and facts[2] == 1,
            f"r{i} accept_double: status={facts[0]} 確定メッセージ={facts[2]}（期待 visiting・1）",
        )
        sc.check(
            visit_values == (visit_day, morning_slot),
            f"r{i} accept_double: 訪問日・時間帯が {visit_values}（期待 {(visit_day, morning_slot)}）",
        )

        # ── admin_cancel_vs_accept: 運営の強制終了と accept を同時に ──
        txn_id, op_token = await new_transaction(c, admin_token, user_token, f"s11c{i}")
        proposal = must(await propose(txn_id, op_token, "09:00", "12:00")(c), 201)

        async def do_admin_cancel(cc: httpx.AsyncClient) -> httpx.Response:
            return await cc.patch(
                f"{V1}/admin/transactions/{txn_id}/cancel",
                json={"reason": "同時実行検証（運営の強制終了と日程確定）"},
                headers=auth(admin_token),
            )

        rs = await volley(do_admin_cancel, accept(txn_id, proposal["id"]))
        adm, acc = rs[0].status_code, rs[1].status_code
        facts = await schedule_facts(txn_id)
        n_cxl = await pg.fetchval(
            "SELECT count(*) FROM cancellations WHERE transaction_id = $1", uuid.UUID(txn_id)
        )
        sc.codes.append(f"r{i} admin_cancel_vs_accept: admin_cancel={adm} accept={acc}")
        sc.facts.append(
            f"r{i} admin_cancel_vs_accept: txn.status={facts[0]} cancellations={n_cxl}"
            f" confirmed={facts[2]}"
        )
        sc.check(adm == 200, f"r{i} admin_cancel_vs_accept: 強制終了が {adm}（期待 200）")
        sc.check(acc in (200, 409), f"r{i} admin_cancel_vs_accept: accept が {acc}（期待 200 か 409）")
        sc.check(
            facts[0] == "cancelled" and n_cxl == 1,
            f"r{i} admin_cancel_vs_accept: status={facts[0]} cancellations={n_cxl}（期待 cancelled・1）",
        )
        sc.check(
            facts[2] == (1 if acc == 200 else 0),
            f"r{i} admin_cancel_vs_accept: accept={acc} なのに確定メッセージが {facts[2]} 件",
        )


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
        Scenario("S9", "NUL・制御文字・孤立サロゲートの入力（実 PG）: 500 にならず 422・何も保存されない"),
    ]
    # S10 は新規アカウントだけを使う独立のシナリオ（添字ではなく変数で渡す）。
    signup_race = Scenario("S10", "同じメールアドレスでの signup 同時2連投（依頼者・業者）")
    scenarios.append(signup_race)
    # S11（日程の提示と確定の同時実行）も添字ではなく変数で渡す。
    schedule_race = Scenario(
        "S11", "日程の提示と候補からの確定の同時実行・確定の二重押し・運営の強制終了と確定の同時実行"
    )
    scenarios.append(schedule_race)
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
            await s10_signup_duplicate_email_race(pg, signup_race)
            # S8 は運営アカウントの admin 権限を使う（2人目の運営は S8 の中で昇格・降格する）ため、
            # S7 より前に流す。
            await s8_review_hide_race(
                c, pg, admin_token, admin_user["id"], user_token, scenarios[7]
            )
            # S9 は同時実行ではなく入力検証の実 PG 回帰（1周だけ）。S8 の後・S7 の前に置く
            # （S7 が運営アカウントの admin 権限を一時的に外すため、それより前なら S9 は
            # 通常の admin 権限で PATCH /admin/transactions/{id}/cancel 等を叩ける）。
            await s9_unsafe_input_rejected(c, pg, admin_token, user_token, scenarios[8])
            # S11 は業者の作成と運営の強制終了に admin 権限を使うため、S7 より前に流す。
            await s11_schedule_propose_vs_accept(c, pg, admin_token, user_token, schedule_race)
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
