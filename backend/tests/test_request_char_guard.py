"""全リクエスト共通防御（app.api.request_char_guard）の統合テスト。

- walker 単体: ``find_unsafe_char_path`` の反復実装が再帰なしで正しく動くこと
  （深さ10万・要素20万件でも RecursionError にならずスケールすること）と、
  ``max_nodes``（security review B2）の fail-closed 挙動を確認する。
- ``_is_explicit_json_content_type``・``_should_attempt_json_decode`` 単体:
  前者は FastAPI 本体（fastapi.routing）と同じ判定基準、後者は Content-Type 無しも
  検査対象にする本ガード独自の判定（security review B1）であることを確認する。
- HTTP（素の ``create_test_app``）: 拒否・許可・content-type 判定・body_field 判定・
  パスパラメータ・クエリ・ログ・再パース無し・ノード数上限・
  FastAPI 内部実装への依存箇所（scope["route"] 等）を検証する。
- HTTP（本番と同じハンドラ: ``create_app``）: ``app.main`` の独自例外ハンドラ経由でも
  同じ振る舞い（400/422 の形状）になることを確認する（tests/test_main.py と同形）。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import AsyncIterator

import pydantic
import pytest
from fastapi import APIRouter, Depends, FastAPI, File, Form, UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.request_char_guard import (
    JsonTooLargeToInspectError,
    _disallowed_char_throttle,
    _is_explicit_json_content_type,
    _json_decode_failure_throttle,
    _route_missing_throttle,
    _should_attempt_json_decode,
    _too_large_throttle,
    find_unsafe_char_path,
    reject_unsafe_request_chars,
)
from app.config import Settings
from app.core.limits import MAX_ITEMS_PER_CASE, MAX_PHOTOS_PER_CASE, MAX_PHOTOS_PER_ITEM
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
    _too_large_throttle.reset()


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


# ──────────────────────────── walker 単体: max_nodes（security review B2） ────────────────────────────


def test_find_unsafe_char_path_max_nodes_exactly_at_limit_passes() -> None:
    """辿るノード数がちょうど max_nodes なら例外にならず走査を完了できる。"""
    payload = list(range(100))  # トップレベル list の 100 要素 = 100 ノード。
    assert find_unsafe_char_path(payload, max_nodes=100) is None


def test_find_unsafe_char_path_max_nodes_one_over_limit_raises() -> None:
    """辿るノード数が max_nodes を1つでも超えたら JsonTooLargeToInspectError になる。"""
    payload = list(range(101))  # 101 ノード。
    with pytest.raises(JsonTooLargeToInspectError):
        find_unsafe_char_path(payload, max_nodes=100)


def test_find_unsafe_char_path_max_nodes_none_is_backward_compatible_with_large_inputs() -> None:
    """max_nodes 省略（None＝無制限）なら、既存の深さ10万・要素20万件の挙動は変わらない。"""
    depth = 100_000
    payload: object = "leaf"
    for _ in range(depth):
        payload = {"n": payload}
    assert find_unsafe_char_path(payload) is None

    size = 200_000
    big_list: list[object] = ["ok"] * size
    big_list[-1] = chr(0x00)
    assert find_unsafe_char_path(big_list) == (size - 1,)


def _count_visited_nodes(payload: object) -> int:
    """max_nodes を検査せず素通しする以外は find_unsafe_char_path と同じ辿り方で、
    総ノード数だけを数える（テスト専用の単純な参照実装。走査ロジックの正しさは
    本体側のテストで別途確認済みのため、ここではカウントの一致だけを見る）。
    """
    if not isinstance(payload, (dict, list)):
        return 0
    stack = [iter(payload.items()) if isinstance(payload, dict) else iter(enumerate(payload))]
    count = 0
    while stack:
        try:
            _, value = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        count += 1
        if isinstance(value, dict):
            stack.append(iter(value.items()))
        elif isinstance(value, list):
            stack.append(iter(enumerate(value)))
    return count


def _case_create_top_level_kwargs() -> dict[str, object]:
    """CaseCreateRequest のトップレベル11キーを全て明示したベース値
    （オプション欄を省略するとノード数が減ってしまうため、根拠の実測と
    一致させるには全キーを埋める必要がある。security review C3(b)）。
    """
    return {
        "purpose": "引っ越し",
        "prefecture": "東京都",
        "city": "x",
        "address_detail": "x",
        "housing_type": "x",
        "floor_plan": "x",
        "floor_number": 1,
        "has_elevator": True,
        "photos": [],
        "items": [],
        "idempotency_key": "x",
    }


def test_case_create_upper_bound_payload_node_count_below_inspection_limit() -> None:
    """security review C3(b): 各上限値（MAX_ITEMS_PER_CASE・MAX_PHOTOS_PER_ITEM・
    MAX_PHOTOS_PER_CASE）を単純に掛け合わせた「上界」は1,661ノード。この構成は
    写真合計が 30×12+150=510 枚になり ``CaseCreateRequest._validate_total_photo_count``
    の合計上限（150枚）を超えるため、実際には ValidationError で受理されない
    （＝この数字は「絶対に届かない上限」であり、実際に受理される最大ではない。
    それでも ``_MAX_INSPECTED_JSON_NODES``（10,000）未満であることを固定化する）。
    """
    from app.api.request_char_guard import _MAX_INSPECTED_JSON_NODES
    from app.schemas_katadzuke import CaseCreateRequest

    payload = {
        **_case_create_top_level_kwargs(),
        "photos": [
            {"storage_key": "x", "sort_order": i} for i in range(MAX_PHOTOS_PER_CASE)
        ],
        "items": [
            {
                "name": "x",
                "sort_order": i,
                "photos": [
                    {"storage_key": "x", "sort_order": j} for j in range(MAX_PHOTOS_PER_ITEM)
                ],
            }
            for i in range(MAX_ITEMS_PER_CASE)
        ],
    }
    node_count = _count_visited_nodes(payload)
    assert node_count < _MAX_INSPECTED_JSON_NODES
    # 実測 1,661（2026-09-27 時点）から大きく変わっていないことを固定化する
    # （limits.py 側の上限値を変えた際に、根拠の docstring の更新漏れに気付くため）。
    assert node_count == 1_661

    with pytest.raises(pydantic.ValidationError, match="写真の合計枚数"):
        CaseCreateRequest(**payload)


def test_case_create_accepted_max_payload_node_count_below_inspection_limit() -> None:
    """security review C3(b): 合計写真数の上限（150枚）と、商品ごと最低1枚必須
    （``CaseItemIn.photos`` の ``min_length=1``）の両方を満たしたまま実際に
    ``CaseCreateRequest`` のバリデーションを通過する最大構成は581ノード
    （トップレベル11キー＋商品30×4＋写真150×3。写真1枚あたり3ノードは、
    直下 photos と各商品 photos のどちらに配分しても変わらないため、
    商品ごとに最低1枚を割り当てた上で残りを直下に集約する配分で実測する）。
    """
    from app.api.request_char_guard import _MAX_INSPECTED_JSON_NODES
    from app.schemas_katadzuke import CaseCreateRequest

    top_level_photo_count = MAX_PHOTOS_PER_CASE - MAX_ITEMS_PER_CASE  # 120
    payload = {
        **_case_create_top_level_kwargs(),
        "photos": [
            {"storage_key": "x", "sort_order": i} for i in range(top_level_photo_count)
        ],
        "items": [
            {
                "name": "x",
                "sort_order": i,
                "photos": [{"storage_key": "x", "sort_order": 0}],
            }
            for i in range(MAX_ITEMS_PER_CASE)
        ],
    }
    node_count = _count_visited_nodes(payload)
    assert node_count < _MAX_INSPECTED_JSON_NODES
    # 実測 581（2026-09-27 時点）から大きく変わっていないことを固定化する。
    assert node_count == 581

    request = CaseCreateRequest(**payload)
    total_photos = len(request.photos) + sum(len(item.photos) for item in request.items)
    assert total_photos == MAX_PHOTOS_PER_CASE


# ──────────────────────────── _is_explicit_json_content_type / _should_attempt_json_decode 単体 ────────────────────────────


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
def test_is_explicit_json_content_type_matches_fastapi_routing_semantics(
    content_type: str | None, expected: bool
) -> None:
    assert _is_explicit_json_content_type(content_type) is expected


@pytest.mark.parametrize(
    "content_type, expected",
    [
        ("application/json", True),
        ("application/json; charset=utf-8", True),
        ("APPLICATION/JSON", True),
        ("application/merge-patch+json", True),
        # security review B1: Content-Type 無しも検査対象にする（FastAPI 本体の
        # strict_content_type の設定やバージョンに依存しないため）。
        (None, True),
        ("", True),
        ("text/plain", False),
        ("multipart/form-data; boundary=xyz", False),
    ],
)
def test_should_attempt_json_decode_treats_missing_content_type_as_inspectable(
    content_type: str | None, expected: bool
) -> None:
    assert _should_attempt_json_decode(content_type) is expected


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


async def test_case_create_nested_items_nul_loc_is_precise(
    client: AsyncClient,
) -> None:
    """items[1].name のようなネストした NUL も loc が正しい位置を指す
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


async def test_path_param_nul_on_files_route_returns_422_with_path_loc(
    client: AsyncClient,
) -> None:
    """security review B3: str のパスパラメータ（GET /files/{storage_key}）に NUL が
    あれば認証・storage_key の妥当性検査より前に422で拒否される（loc は
    ("path", "storage_key")）。現状は storage_key の完全一致検査（storage.is_valid_key）
    で守られているが、将来 str のパスパラメータを追加したときの穴を事前に塞ぐ。"""
    r = await client.get("/api/v1/files/abc%00def.jpg")
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert entry["type"] == "disallowed_character"
    assert entry["loc"] == ["path", "storage_key"]


async def test_path_param_nul_on_uuid_typed_route_also_returns_422(
    client: AsyncClient,
) -> None:
    """Starlette は既定で全パスパラメータを str のまま scope["path_params"] に
    格納し、UUID への変換はこの依存より後（solve_dependencies 内）で行われる
    （starlette/routing.py の Route.matches・api_router.routes の
    param_convertors を実読して確認済み）。したがって、エンドポイント関数の
    型ヒントが ``uuid.UUID`` の case_id であっても NUL は本ガードで検出され、
    Pydantic の uuid_parsing エラーより先に disallowed_character で422になる
    （未認証でも拒否される。認可・存在確認に一切到達しない）。"""
    r = await client.get("/api/v1/cases/abc%00def")
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert entry["type"] == "disallowed_character"
    assert entry["loc"] == ["path", "case_id"]


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


async def test_query_key_nul_returns_422_with_replacement_char_in_loc(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """クエリの「キー」自体に NUL があっても検出される（値だけでなくキーも検査する）。
    loc のキーは replace_unsafe_storage_chars で U+FFFD に置換される。"""
    admin_token = await _make_admin(client, db_session)
    r = await client.get(
        "/api/v1/admin/operators",
        params={"k" + chr(0x00): "v"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert entry["type"] == "disallowed_character"
    assert entry["loc"] == ["query", "k" + chr(0xFFFD)]


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


async def test_content_type_text_plain_does_not_trigger_disallowed_character(
    client: AsyncClient,
) -> None:
    """text/plain は FastAPI 本体が request.json() を呼ばないため、本ガードも
    JSON として読まない（``_should_attempt_json_decode`` が明示的に JSON 系以外の
    Content-Type を対象外にする）。この場合ボディは bytes のまま Pydantic の検証に
    渡り、disallowed_character とは異なる type（Pydantic 標準）の422になる。
    メッセージは1件のまま（何も保存されない）。"""
    token = await _signup_user(client, "guard-ct-plain@example.com")
    body = json.dumps({"body": "ng" + chr(0x00)}).encode("utf-8")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers={**_auth(token), "content-type": "text/plain"},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert len(detail) == 1
    assert detail[0]["type"] != "disallowed_character"


async def test_content_type_missing_now_triggers_disallowed_character(
    client: AsyncClient,
) -> None:
    """security review B1: Content-Type 無しは以前は検査対象外だったが、
    ``_should_attempt_json_decode`` が Content-Type 無しも対象にするよう改めたため、
    NUL 入り JSON は disallowed_character で 422 になる（FastAPI 本体の
    strict_content_type の設定やバージョンに依存しない安全側の判定）。"""
    token = await _signup_user(client, "guard-ct-missing@example.com")
    body = json.dumps({"body": "ng" + chr(0x00)}).encode("utf-8")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=body,
        headers=_auth(token),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert len(detail) == 1
    assert detail[0]["type"] == "disallowed_character"


async def test_content_type_missing_nul_in_signup_name_rejected_and_no_user_created(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """security review B1: 表示用バリデータの無い欄（/auth/signup の name）でも、
    Content-Type 無しで NUL を送ると disallowed_character で 422 になり、
    users 行が1件も作られない。

    security review C3(a): 現行の FastAPI 0.136.3（``strict_content_type`` 既定
    True・プロジェクト内で False 指定なし）では、旧実装（本ガードが Content-Type
    無しを検査対象外にしていた場合）でも Content-Type 無しの本文は bytes のまま
    Pydantic に渡り、``name`` フィールドの型不一致で 422 になる（500 にはならない）。
    500 になりうるのは、``strict_content_type=False`` を明示指定した設定、または
    それを持たない古い FastAPI（pyproject.toml は ``fastapi>=0.115`` で上限固定
    していないため、将来のダウングレードや別環境のインストールで再現しうる）を
    使った場合に、本体が Content-Type 無しでも JSON として読んでしまう経路。
    本ガードが Content-Type 無しも検査対象にするのは、こうした設定・バージョン
    依存を作らないための安全側の判定であり、現行構成での必達の回帰確認ではない。
    """
    email = "guard-ct-missing-signup@example.com"
    body = json.dumps(
        {"email": email, "password": "password123", "name": "x" + chr(0x00)}
    ).encode("utf-8")
    r = await client.post("/api/v1/auth/signup", content=body)
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "disallowed_character"
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == email)
    )
    assert count == 0


async def test_content_type_missing_non_json_body_returns_422_not_500(
    client: AsyncClient,
) -> None:
    """security review B1: Content-Type 無しで JSON としてデコードできない本文
    （プレーンテキスト）を送っても、本ガードは例外もログも出さず素通し、
    FastAPI/Pydantic 側の既存の 422（bytes が dict でない旨のエラー）に任せる。
    500 にならないことが要点（認証依存の 401 と混同しないよう認証済みで叩く）。"""
    token = await _signup_user(client, "guard-ct-missing-nonjson@example.com")
    r = await client.post(
        f"/api/v1/transactions/{_DUMMY_TXN_ID}/messages",
        content=b"this is not json at all",
        headers=_auth(token),
    )
    assert r.status_code == 422
    assert r.status_code != 500


async def test_content_type_missing_memory_error_during_decode_returns_413_not_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """security review C2: Content-Type 無しの経路では本体側が request.json() を
    呼ばないため、本ガードの connection.json() 呼び出しが最初で唯一の JSON
    パーサになる。json.loads が（巨大な本文などで）MemoryError を出すと、
    それを捕まえなければ Starlette の既定例外ハンドラが 500 にしてしまう
    （ServerErrorAlertMiddleware の Critical アラート誤発報につながる）。
    B2 と同じ fail-closed 方針で 413 に倒し、500 にならないことを確認する。

    ``starlette.requests`` の ``json`` 属性は標準ライブラリの ``json`` モジュール
    そのものであり、httpx の ``Response.json()``（``jsonlib.loads`` という別名で
    同じモジュールを参照）にも影響してしまう（実測で確認済み）。そのため、
    レスポンス受信直後に ``monkeypatch.undo()`` で明示的に元へ戻してから
    ``r.json()`` で応答本文を検証する。
    """
    import starlette.requests as starlette_requests_module

    def failing_loads(*args: object, **kwargs: object) -> object:
        raise MemoryError("simulated out-of-memory during json.loads")

    monkeypatch.setattr(starlette_requests_module.json, "loads", failing_loads)
    try:
        body = json.dumps(
            {
                "email": "guard-memoryerror@example.com",
                "password": "password123",
                "name": "ok",
            }
        ).encode("utf-8")
        r = await client.post("/api/v1/auth/signup", content=body)
    finally:
        monkeypatch.undo()

    assert r.status_code == 413
    assert r.status_code != 500
    assert r.json()["detail"] == "送信内容が大きすぎます。"


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


def _build_form_test_app() -> FastAPI:
    """テスト専用の小さな Form ルーターを持つ FastAPI アプリ（security review C1）。

    2026-09-27 時点で endpoints 配下に ``Form``/``File``/``Body`` 定義は0件で
    実害は無いが、将来 ``x: str = Form(...)`` のルートが追加された場合に
    本ガードが正しく動くことを検証するため、テスト内だけで完結する専用の
    小さなルーター（``api_router`` 本体には一切手を加えない）を組み立てる。
    """
    app = FastAPI()
    router = APIRouter(dependencies=[Depends(reject_unsafe_request_chars)])

    @router.post("/form-only")
    async def form_only(x: str = Form(...)) -> dict[str, str]:
        return {"x": x}

    @router.post("/form-with-file")
    async def form_with_file(
        x: str = Form(...), file: UploadFile = File(...)
    ) -> dict[str, object]:
        content = await file.read()
        return {"x": x, "file_len": len(content)}

    app.include_router(router)
    return app


async def test_form_route_url_encoded_nul_in_value_returns_422_with_body_loc() -> None:
    """security review C1: x-www-form-urlencoded の値に NUL があれば422・
    loc ["body","x"] になる。本体側（fastapi.routing）は依存解決より前に
    ``await request.form()`` を呼んでおり、Starlette がその結果を
    ``self._form`` にキャッシュする（``_get_form`` は ``self._form is None``
    のときだけ実際にパースする）ため、本ガードが再度 ``connection.form()`` を
    呼んでも再パース・RuntimeError にはならない（実測でも確認済み）。"""
    app = _build_form_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/form-only",
            content=b"x=a%00b",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert r.status_code == 422
    entry = r.json()["detail"][0]
    assert entry["type"] == "disallowed_character"
    assert entry["loc"] == ["body", "x"]


async def test_form_route_url_encoded_normal_value_returns_200() -> None:
    """x-www-form-urlencoded の通常値（NUL なし）は素通りして200になる。"""
    app = _build_form_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/form-only",
            content=b"x=hello",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert r.status_code == 200
    assert r.json()["x"] == "hello"


async def test_form_route_multipart_normal_value_and_file_with_nul_bytes_returns_200() -> None:
    """multipart の通常値（str）と ``UploadFile`` を両方持つルートで、ファイルの
    中身に NUL バイトを含んでいても200になる（``FormData`` の値は
    ``UploadFile | str`` で、str 値のみ検査し ``UploadFile`` の中身は見ないため。
    security review C1）。"""
    app = _build_form_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/form-with-file",
            data={"x": "ok"},
            files={"file": ("test.bin", b"\x00" * 10, "application/octet-stream")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["x"] == "ok"
    assert body["file_len"] == 10


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


async def test_extra_key_with_over_limit_elements_and_trailing_nul_returns_413(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """security review B2: 認証不要の /auth/signup に、余分なキーへ
    ``_MAX_INSPECTED_JSON_NODES``（10,000）+1 要素の配列を積み、その末尾に NUL を
    置いても 413 で打ち切られる（走査を打ち切って素通しにすると、上限を埋めた
    後ろの NUL を検出できないまま通す迂回が成立してしまうため、必ず拒否する）。
    users 行は1件も作られない。"""
    email = "guard-too-large@example.com"
    big_list = ["ok"] * 10_000 + ["x" + chr(0x00)]
    body = json.dumps(
        {"email": email, "password": "password123", "name": "ok", "extra": big_list},
        ensure_ascii=True,
    ).encode("ascii")
    r = await client.post(
        "/api/v1/auth/signup", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "送信内容が大きすぎます。"
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == email)
    )
    assert count == 0


async def test_too_large_warning_logged_with_process_wide_count(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """security review B4: 413 の拒否ログにもプロセス内累計件数を添える。"""
    big_list = ["ok"] * 10_001
    body = json.dumps(
        {"email": "guard-too-large-log@example.com", "password": "password123", "name": "ok", "extra": big_list}
    ).encode("utf-8")
    caplog.set_level(logging.WARNING, logger="app.api.request_char_guard")
    r = await client.post(
        "/api/v1/auth/signup", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    warning_records = [
        rec
        for rec in caplog.records
        if rec.name == "app.api.request_char_guard" and "413" in rec.getMessage()
    ]
    assert len(warning_records) == 1
    assert re.search(r"プロセス内累計 \d+ 件", warning_records[0].getMessage()) is not None


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
    message = warning_records[0].getMessage()
    assert secret_marker not in message
    # security review B4: 拒否ログにプロセス内累計件数を添える
    # （case_photos.py の _note_upload_strip_failure と同じ流儀）。
    # 累計値そのものは他テストの実行順序に依存するため、形式のみ確認する。
    assert re.search(r"プロセス内累計 \d+ 件", message) is not None


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
    # security review B4: 生の connection.url.path（%0A での行分割・storage_key 等の
    # 露出手段になりうる）をログに出さない。method のみにする。
    assert "/fake" not in route_missing_records[0].getMessage()


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
            json={"agreed_terms": True, "email": "prod-nul@example.com", "password": "password123", "name": "x" + chr(0x00)},
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
