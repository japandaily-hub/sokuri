"""全リクエスト共通防御（app.api.request_char_guard）の統合テスト。

- walker 単体: ``find_unsafe_char_path`` の反復実装が再帰なしで正しく動くこと
  （深さ10万・要素20万件でも RecursionError にならずスケールすること）を確認する。
- ``_is_json_content_type`` 単体: FastAPI 本体（fastapi.routing）と同じ判定基準か確認する。
- HTTP（素の ``create_test_app``）: 拒否・許可・content-type 判定・body_field 判定・
  クエリ・ログ・再パース無し・FastAPI 内部実装への依存箇所（scope["route"] 等）を検証する。
- HTTP（本番と同じハンドラ: ``create_app``）: ``app.main`` の独自例外ハンドラ経由でも
  同じ振る舞い（400/422 の形状）になることを確認する（tests/test_main.py と同形）。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.request_char_guard import (
    _disallowed_char_throttle,
    _is_json_content_type,
    _json_decode_failure_throttle,
    _route_missing_throttle,
    find_unsafe_char_path,
    reject_unsafe_request_chars,
)
from app.config import Settings
from app.db.models.contact_message import ContactMessage
from app.db.models.operator import Operator
from app.db.models.operator_application import OperatorApplication
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from tests.test_katadzuke_api import (
    _auth,
    _make_admin,
    _signup_operator,
    _signup_user,
    _upload_license,
    create_test_app,
)

# ダミーの成約 ID（実在しなくてよい。reject_unsafe_request_chars は認可・存在確認より
# 前に実行されるため、ボディの違反は成約の実在性に関わらず 422 になる）。
_DUMMY_TXN_ID = "00000000-0000-0000-0000-000000000000"


def _throttles_reset() -> None:
    """モジュールレベルの ThrottledLogger 群をテスト間で独立させる。"""
    _route_missing_throttle.reset()
    _json_decode_failure_throttle.reset()
    _disallowed_char_throttle.reset()


@pytest.fixture(autouse=True)
def _reset_throttles() -> None:
    _throttles_reset()


# ──────────────────────────── walker 単体: find_unsafe_char_path ────────────────────────────


def test_find_unsafe_char_path_no_violation_returns_none() -> None:
    assert find_unsafe_char_path({}) is None
    assert find_unsafe_char_path([]) is None
    assert find_unsafe_char_path(1) is None
    assert find_unsafe_char_path(1.5) is None
    assert find_unsafe_char_path(True) is None
    assert find_unsafe_char_path(False) is None
    assert find_unsafe_char_path(None) is None
    assert find_unsafe_char_path("ok") is None
    assert find_unsafe_char_path({"a": {"b": [1, "ok", None, True, 1.5]}}) is None


def test_find_unsafe_char_path_top_level_str_violation_returns_empty_tuple() -> None:
    assert find_unsafe_char_path("a" + chr(0x00)) == ()


def test_find_unsafe_char_path_detects_key_violation() -> None:
    assert find_unsafe_char_path({"a": 1, "k" + chr(0x00): 1}) == ("k" + chr(0x00),)


def test_find_unsafe_char_path_detects_value_violation_nested() -> None:
    payload = {"a": {"b": [1, "a" + chr(0xD800) + "b"]}}
    assert find_unsafe_char_path(payload) == ("a", "b", 1)


def test_find_unsafe_char_path_nested_array_path_has_mixed_key_types() -> None:
    """ネスト配列 ("a", 2, 1) — str のキーと int の添字が混在する path。"""
    payload = {"a": [0, 0, [0, chr(0x00)]]}
    assert find_unsafe_char_path(payload) == ("a", 2, 1)


def test_find_unsafe_char_path_document_order_returns_first_violation() -> None:
    """dict は挿入順（＝JSON の記載順）で辿るため、最初に見つかった違反を返す。"""
    d = {"x": "ok", "y": chr(0x00), "z": chr(0x00)}
    assert find_unsafe_char_path(d) == ("y",)


def test_find_unsafe_char_path_parent_key_violation_returned_before_descending_to_child() -> None:
    payload = {"k" + chr(0x00): {"ok": chr(0x00)}}
    assert find_unsafe_char_path(payload) == ("k" + chr(0x00),)


def test_find_unsafe_char_path_allows_correctly_paired_supplementary_char() -> None:
    """正しい補助面文字（単一コードポイントとして str に格納されている絵文字）は拒否しない。"""
    assert find_unsafe_char_path({"a": chr(0x1F600)}) is None


def test_find_unsafe_char_path_deep_nesting_100000_no_violation_returns_none() -> None:
    payload: object = "leaf"
    for _ in range(100_000):
        payload = {"n": payload}
    assert find_unsafe_char_path(payload) is None


def test_find_unsafe_char_path_deep_nesting_100000_with_violation_at_leaf() -> None:
    """深さ10万でも RecursionError にならず、長さ10万+1(先頭に "body" を足す前) の path を返す。"""
    depth = 100_000
    payload: object = chr(0x00)
    for _ in range(depth):
        payload = {"n": payload}
    result = find_unsafe_char_path(payload)
    assert result is not None
    assert len(result) == depth
    assert result == ("n",) * depth


def test_find_unsafe_char_path_large_list_violation_at_tail_element() -> None:
    size = 200_000
    big_list: list[object] = ["ok"] * size
    big_list[-1] = chr(0x00)
    assert find_unsafe_char_path(big_list) == (size - 1,)


# ──────────────────────────── _is_json_content_type 単体 ────────────────────────────


@pytest.mark.parametrize(
    "content_type, expected",
    [
        ("application/json", True),
        ("application/json; charset=utf-8", True),
        ("APPLICATION/JSON", True),
        ("application/merge-patch+json", True),
        ("text/plain", False),
        (None, False),
        ("", False),
        ("multipart/form-data; boundary=xyz", False),
    ],
)
def test_is_json_content_type_matches_fastapi_routing_semantics(
    content_type: str | None, expected: bool
) -> None:
    assert _is_json_content_type(content_type) is expected


# ──────────────────────────── HTTP（素の create_test_app） ────────────────────────────


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    test_app = create_test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


def _ascii_json_bytes(payload: object) -> bytes:
    """孤立サロゲートを含みうる payload を ``\\uXXXX`` 形式へエスケープした ASCII バイト列にする
    （httpx の ``json=`` は ``ensure_ascii=False`` で UTF-8 化するため孤立サロゲートを送れない。
    実測: ``UnicodeEncodeError: 'utf-8' codec can't encode character '\\ud800'...``）。
    """
    return json.dumps(payload, ensure_ascii=True).encode("ascii")


async def test_chat_message_nul_returns_422_with_only_type_loc_msg_keys(
    client: AsyncClient,
) -> None:
    token = await _signup_user(client, "guard-nul@example.com")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        json={"body": "ng" + chr(0x00)},
        headers=_auth(token),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert len(detail) == 1
    entry = detail[0]
    assert set(entry.keys()) == {"type", "loc", "msg"}
    assert entry["type"] == "disallowed_character"
    assert entry["loc"] == ["body", "body"]


async def test_chat_message_ascii_escaped_lone_surrogate_returns_422(
    client: AsyncClient,
) -> None:
    token = await _signup_user(client, "guard-surrogate-ascii@example.com")
    body = _ascii_json_bytes({"body": "ng" + chr(0xD800)})
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "disallowed_character"


async def test_chat_message_raw_utf8_surrogatepass_bytes_returns_422(
    client: AsyncClient,
) -> None:
    """生バイトの孤立サロゲート（surrogatepass でエンコードした不正な UTF-8）。"""
    token = await _signup_user(client, "guard-surrogate-raw@example.com")
    raw = b'{"body": "ng' + chr(0xD800).encode("utf-8", "surrogatepass") + b'"}'
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=raw,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "disallowed_character"


async def test_chat_message_utf16_encoded_json_nul_returns_422(client: AsyncClient) -> None:
    """UTF-16 で符号化された JSON も json.loads が自動検出してデコードし、NUL を検出する。"""
    token = await _signup_user(client, "guard-utf16@example.com")
    body = json.dumps({"body": "ng" + chr(0x00)}).encode("utf-16")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "disallowed_character"


async def test_chat_message_ascii_escaped_correct_surrogate_pair_emoji_not_rejected(
    client: AsyncClient,
) -> None:
    """正しいサロゲートペア（ASCII エスケープの絵文字）は disallowed_character にならない
    （json.loads が単一コードポイントへ復元するため）。成約が存在しないので 404 になるが、
    それは「422 disallowed_character にならない」ことの確認に十分な代理指標。"""
    token = await _signup_user(client, "guard-emoji@example.com")
    body = _ascii_json_bytes({"body": "ok" + chr(0x1F600)})
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "成約情報が見つかりません。"


async def test_chat_message_key_with_nul_loc_shows_replacement_char(
    client: AsyncClient,
) -> None:
    """キー自体の NUL も検出され、応答の loc は U+FFFD に置換されている（値は反射しない）。"""
    token = await _signup_user(client, "guard-key-nul@example.com")
    body = _ascii_json_bytes({"body": "ok", "k" + chr(0x00): 1})
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    loc = r.json()["detail"][0]["loc"]
    assert loc == ["body", "k" + chr(0xFFFD)]


async def test_notification_settings_lone_surrogate_key_returns_422_not_500(
    client: AsyncClient,
) -> None:
    """孤立サロゲート入りキーを extra="forbid" モデルへ送ると、修正前は
    Pydantic の extra_forbidden エラーの loc に生の孤立サロゲートが載り、
    JSON シリアライズ失敗で 500 になっていた（回帰確認）。"""
    token = await _signup_user(client, "guard-notif-key@example.com")
    body = _ascii_json_bytes({"email_notify_opt_in": True, "x" + chr(0xD800): 1})
    r = await client.patch(
        "/api/v1/users/me/notification-settings",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "disallowed_character"


async def test_case_create_address_detail_lone_surrogate_returns_422_not_500(
    client: AsyncClient,
) -> None:
    """address_detail は Field の制約を持たないため、修正前は SQLite でも 500 だった
    （DataError 相当）。全体防御により 422 で拒否される（回帰確認）。"""
    token = await _signup_user(client, "guard-case-address@example.com")
    payload = {
        "purpose": "その他",
        "prefecture": "東京都",
        "city": "渋谷区",
        "address_detail": "住所" + chr(0xD800),
        "photos": [],
        "items": [],
    }
    body = _ascii_json_bytes(payload)
    r = await client.post(
        "/api/v1/cases",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "disallowed_character"


async def test_case_create_nested_items_and_areas_nul_loc_is_precise(
    client: AsyncClient,
) -> None:
    """items[1].name・areas[2] のようなネストした NUL も loc が正しい位置を指す
    （従来は個々のバリデータが除去していた欄だが、全体防御が先に 422 にする。
    意図した挙動変化）。"""
    token = await _signup_user(client, "guard-case-nested@example.com")
    payload = {
        "purpose": "その他",
        "prefecture": "東京都",
        "city": "渋谷区",
        "photos": [],
        "items": [
            {"name": "ok1", "photos": [{"storage_key": "a.jpg"}]},
            {"name": "bad" + chr(0x00), "photos": [{"storage_key": "b.jpg"}]},
        ],
    }
    body = _ascii_json_bytes(payload)
    r = await client.post(
        "/api/v1/cases",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    loc = r.json()["detail"][0]["loc"]
    assert loc == ["body", "items", 1, "name"]


@pytest.mark.parametrize(
    "path, payload, target_key, model_cls, email_attr",
    [
        (
            "/api/v1/auth/signup",
            {"email": "sg1@example.com", "password": "password123", "name": "x"},
            "name",
            User,
            "email",
        ),
        (
            "/api/v1/auth/operator/signup",
            {
                "company_name": "x",
                "email": "op1@example.com",
                "password": "password123",
                "license_number": "第123456789012号",
                "agreed": True,
            },
            "company_name",
            Operator,
            # Operator モデルのカラム名は contact_email（OperatorOut.contact_email と同じ命名）。
            "contact_email",
        ),
        (
            "/api/v1/operator-applications",
            {
                "company_name": "x",
                "representative_name": "y",
                "registered_address": "z",
                "contact_name": "w",
                "email": "biz1@example.com",
                "phone": "03-1234-5678",
                "business_type": "corp",
                "service_area": "東京都",
                "message": "よろしくお願いします。",
                "license_number": "第123456789012号",
                "bank_account": {
                    "bank_name": "みずほ銀行",
                    "branch_name": "東京営業部",
                    "account_type": "ordinary",
                    "account_number": "1234567",
                    "account_holder": "テスト",
                },
                "agreed": True,
            },
            "message",
            OperatorApplication,
            # OperatorApplicationCreateRequest.email は保存時に contact_email
            # カラムへ入る（OperatorApplicationOut.contact_email と同じ命名）。
            "contact_email",
        ),
        (
            "/api/v1/contact",
            {"name": "x", "email": "ct1@example.com", "category": "service", "message": "y"},
            "message",
            ContactMessage,
            "email",
        ),
        (
            "/api/v1/auth/login",
            {"email": "nonexistent@example.com", "password": "password123"},
            "email",
            None,
            None,
        ),
    ],
)
async def test_unauthenticated_endpoints_reject_nul_in_free_text_field(
    client: AsyncClient,
    db_session: AsyncSession,
    path: str,
    payload: dict[str, object],
    target_key: str,
    model_cls: type | None,
    email_attr: str | None,
) -> None:
    """認証不要のエンドポイントでも NUL は422で拒否され、行が1件も作られない
    （対象欄に NUL を混ぜる。login は email 自体に NUL を混ぜて確認する。
    login は何も作成しない操作のため model_cls は None にして件数確認を省略する）。
    """
    poisoned = dict(payload)
    poisoned[target_key] = str(poisoned[target_key]) + chr(0x00)

    r = await client.post(path, json=poisoned)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["type"] == "disallowed_character"

    if model_cls is not None:
        count = await db_session.scalar(
            select(func.count())
            .select_from(model_cls)
            .where(getattr(model_cls, email_attr) == payload["email"])
        )
        assert count == 0


async def test_query_nul_on_admin_operators_returns_422_with_query_loc(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token = await _make_admin(client, db_session)
    r = await client.get(
        "/api/v1/admin/operators",
        params={"q": "x" + chr(0x00)},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert entry["type"] == "disallowed_character"
    assert entry["loc"] == ["query", "q"]


async def test_query_nul_rejected_even_when_unauthenticated(client: AsyncClient) -> None:
    """クエリ検査は認証依存より先に解決されるため、未認証でも422になる（処理順の明記）。"""
    r = await client.get("/api/v1/admin/operators", params={"q": "x" + chr(0x00)})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["query", "q"]


async def test_query_normal_value_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token = await _make_admin(client, db_session)
    r = await client.get(
        "/api/v1/admin/operators", params={"q": "テスト"}, headers=_auth(admin_token)
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/json; charset=utf-8",
        "APPLICATION/JSON",
        "application/merge-patch+json",
    ],
)
async def test_content_type_json_variants_all_trigger_disallowed_character(
    client: AsyncClient, content_type: str
) -> None:
    token = await _signup_user(client, f"guard-ct-{content_type[:4].lower()}@example.com")
    body = json.dumps({"body": "ng" + chr(0x00)}).encode("utf-8")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": content_type},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert len(detail) == 1
    assert detail[0]["type"] == "disallowed_character"


@pytest.mark.parametrize("send_content_type", [True, False])
async def test_content_type_non_json_or_missing_does_not_trigger_disallowed_character(
    client: AsyncClient, send_content_type: bool
) -> None:
    """text/plain・content-type 無しは FastAPI 本体が request.json() を呼ばないため、
    本ガードも JSON として読まない。この場合ボディは bytes のまま Pydantic の検証に渡り、
    disallowed_character とは異なる type（Pydantic 標準）の422になる。
    メッセージは1件のまま（何も保存されない）。"""
    token = await _signup_user(
        client, f"guard-ct-plain-{send_content_type}@example.com"
    )
    body = json.dumps({"body": "ng" + chr(0x00)}).encode("utf-8")
    headers = {**_auth(token)}
    if send_content_type:
        headers["content-type"] = "text/plain"
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages", content=body, headers=headers
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert len(detail) == 1
    assert detail[0]["type"] != "disallowed_character"


async def test_upload_put_without_auth_and_nul_body_returns_401_not_422(
    client: AsyncClient,
) -> None:
    """body_field の無いルート（PUT /upload/{storage_key}）は未認証でも本ガードで
    ボディを読まない（読むと multipart 同様にストリーム消費で壊れる経路がある）ため、
    認証依存がそのまま 401 を返す（422 disallowed_character にならない）。"""
    r = await client.put(
        "/api/v1/upload/anything.jpg",
        content=b'{"a":1}' + bytes([0]),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 401


async def test_auth_me_with_nul_json_body_returns_200(client: AsyncClient) -> None:
    """GET /auth/me はボディパラメータを持たない（body_field が None）ため、
    NUL 入り JSON ボディを送っても本ガードはボディを読まず、通常どおり200になる。"""
    token = await _signup_user(client, "guard-auth-me@example.com")
    r = await client.request(
        "GET",
        "/api/v1/auth/me",
        content=b'{"a": "x\x00"}',
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 200


async def test_multipart_license_upload_with_nul_bytes_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """multipart の許可証画像（NUL バイトを含む）は body_field が無いため本ガードの
    対象外で、通常どおり200になる。"""
    admin_token = await _make_admin(client, db_session)
    code_r = await client.post(
        "/api/v1/admin/invites", json={}, headers=_auth(admin_token)
    )
    assert code_r.status_code == 201
    invite_code = code_r.json()["code"]
    op_token, _ = await _signup_operator(
        client, invite_code, "guard-multipart-op@example.com"
    )
    await _upload_license(client, op_token)  # 内部で 200 を assert 済み


def _nested_json_bytes(depth: int, leaf_json_text: str) -> bytes:
    """``{"n":{"n":...leaf...}}`` を再帰なしの文字列結合で組み立てる。

    ``json.dumps`` 自身も再帰下降エンコーダのため、深いネストのオブジェクトを渡すと
    送信前（テストコード側）で ``RecursionError`` になってしまう（実測）。よって
    Python の str の ``*`` 演算子（内部はループ実装）で JSON テキストを直接組み立てる。
    """
    return (("{\"n\":" * depth) + leaf_json_text + ("}" * depth)).encode("ascii")


async def test_deep_nesting_500_returns_422_with_expected_loc_length(
    client: AsyncClient,
) -> None:
    """深さ500の入れ子に NUL を置くと、再帰上限に達さず422で拒否され、
    loc の長さは ("body",) + ("n",)*500 で501になる。"""
    token = await _signup_user(client, "guard-depth500@example.com")
    depth = 500
    body = _nested_json_bytes(depth, "\"\\u0000\"")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail[0]["type"] == "disallowed_character"
    assert len(detail[0]["loc"]) == depth + 1
    assert detail[0]["loc"] == ["body"] + ["n"] * depth


async def test_deep_nesting_10000_returns_fastapi_400_not_500(
    client: AsyncClient,
) -> None:
    """深さ10000は Python 標準 json（再帰下降パーサ）の再帰上限を超え、FastAPI 本体側
    （fastapi.routing の app() 関数、依存解決より前にボディを読む処理）で
    RecursionError が起き、既存の except Exception ハンドリングにより 400 になる
    （500 でないことが要点。本ガードに到達する前に本体側で終わる）。"""
    token = await _signup_user(client, "guard-depth10000@example.com")
    body = _nested_json_bytes(10_000, "\"leaf\"")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert r.status_code == 400
    assert r.status_code != 500


async def test_disallowed_char_warning_logged_once_and_throttled_without_leaking_value(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """拒否時の WARNING は ThrottledLogger（60秒間隔）により複数リクエストで1回だけ出て、
    ログに元の値（目印文字列）が含まれない。"""
    token = await _signup_user(client, "guard-log-throttle@example.com")
    secret_marker = "SECRET_MARKER_VALUE_UNIQUE_12345"
    caplog.set_level(logging.WARNING, logger="app.api.request_char_guard")
    for _ in range(3):
        r = await client.post(
            f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
            json={"body": secret_marker + chr(0x00)},
            headers=_auth(token),
        )
        assert r.status_code == 422
    warning_records = [
        rec for rec in caplog.records if rec.name == "app.api.request_char_guard"
    ]
    assert len(warning_records) == 1
    assert secret_marker not in warning_records[0].getMessage()


async def test_json_body_is_not_reparsed_by_the_guard(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本ガードが connection.json() を呼んでも、starlette.requests 内の json.loads は
    1リクエストにつき1回しか呼ばれない（FastAPI 本体が先にパースしキャッシュしたものを
    再利用するだけで、二重デコードのコスト・二重デコード起因のズレが無いことの確認）。

    ``starlette.requests`` モジュールの ``json`` 属性は標準ライブラリの ``json``
    モジュールそのもの（別名バインドではない）であるため、ここで ``loads`` を
    差し替えると httpx クライアント側の ``response.json()`` 呼び出しも数えてしまう
    （実測）。そのため、計測対象のリクエストより前に必要な準備（ここではユーザー
    登録。内部で ``r.json()`` を呼ぶ）を済ませてから monkeypatch を適用する。
    """
    token = await _signup_user(client, "guard-reparse@example.com")

    import starlette.requests as starlette_requests_module

    call_count = {"n": 0}
    original_loads = starlette_requests_module.json.loads

    def counting_loads(*args: object, **kwargs: object) -> object:
        call_count["n"] += 1
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(starlette_requests_module.json, "loads", counting_loads)

    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        json={"body": "reparse-check" + chr(0x00)},
        headers=_auth(token),
    )
    assert r.status_code == 422
    assert call_count["n"] == 1


async def test_reject_unsafe_request_chars_fails_open_when_scope_route_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """scope["route"] が無い場合（FastAPI 内部実装への依存が崩れた想定）は例外を投げず
    ボディ検査をスキップする（フェイルオープン）。実際の Starlette Request を
    scope を自作して構築し、依存本体を直接呼び出して確認する
    （HTTP 経由のテストは常に scope["route"] が設定済みのため、この分岐だけは
    直接呼び出しでないと再現できない）。
    """
    body = b'{"body": "ng\\u0000"}'

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/fake",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
        # "route" キー自体を持たせない（scope.get("route") が None になる）。
    }
    request = Request(scope, receive=receive)
    caplog.set_level(logging.WARNING, logger="app.api.request_char_guard")

    await reject_unsafe_request_chars(request)  # 例外を投げずに戻ることの確認が主目的。

    route_missing_records = [
        rec
        for rec in caplog.records
        if rec.name == "app.api.request_char_guard" and "scope['route']" in rec.getMessage()
    ]
    assert len(route_missing_records) == 1


# ──────────────────────────── HTTP（本番と同じ独自例外ハンドラ経由） ────────────────────────────


def _app_with_test_db(db_session: AsyncSession) -> FastAPI:
    """``create_app()`` の独自例外ハンドラ（app.main._validation_error_handler）を
    含む実アプリに、テスト用 DB を注入する（tests/test_main.py の同形）。"""
    settings = Settings(_env_file=None)
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    return app


async def test_production_handler_nul_body_returns_422_with_loc_msg_type(
    db_session: AsyncSession,
) -> None:
    app = _app_with_test_db(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/signup",
            json={"email": "prod-nul@example.com", "password": "password123", "name": "x" + chr(0x00)},
        )
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert set(entry.keys()) == {"type", "loc", "msg"}
    assert entry["type"] == "disallowed_character"
    assert entry["loc"] == ["body", "name"]


async def test_production_handler_lone_surrogate_key_returns_422(
    db_session: AsyncSession,
) -> None:
    app = _app_with_test_db(db_session)
    body = _ascii_json_bytes(
        {"email": "prod-surrogate@example.com", "password": "password123", "x" + chr(0xD800): 1}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/signup",
            content=body,
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert set(entry.keys()) == {"type", "loc", "msg"}
    assert entry["type"] == "disallowed_character"


async def test_production_handler_query_nul_returns_422(db_session: AsyncSession) -> None:
    app = _app_with_test_db(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/v1/admin/operators", params={"q": "x" + chr(0x00)})
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert set(entry.keys()) == {"type", "loc", "msg"}
    assert entry["loc"] == ["query", "q"]
