"""表示用自由記述欄の制御文字検証（app.services.text_sanitize 方針②）の統合テスト。

- 単体: ``has_disallowed_display_chars``・``has_unsafe_storage_chars`` が
  ``DISALLOWED_DISPLAY_CHAR_RANGES``・``UNSAFE_STORAGE_CHAR_RANGES`` と一致し、
  さらに前者が Python 標準の ``unicodedata`` が示す Bidi_Control・Cc(0x0A除く)・Cs
  の集合と BMP 全体で一致すること。
- モデル直接検証: schemas_katadzuke.py の表示用自由記述欄12件（field_validator の
  対象）を parametrize し、拒否文字での ValidationError・許可文字の素通し・
  Optional 欄の None/省略を確認する。
- HTTP 配線: tests.test_katadzuke_api のヘルパーを import して実エンドポイントに
  投げ、「拒否422で何も保存されない」「許可は成功する」ことを確認する
  （前例: tests/test_admin_reviews.py）。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。
"""

from __future__ import annotations

import json
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

import pydantic
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bid import Bid
from app.db.models.case import Case
from app.db.models.message import Message
from app.db.models.operator_profile import OperatorProfile
from app.db.models.transaction import ReductionRequest, Transaction
from app.schemas_katadzuke import (
    BidCreateRequest,
    BidUpdateRequest,
    CaseCancelRequest,
    CaseCreateRequest,
    MessageCreateRequest,
    OperatorProfileUpdateRequest,
    ReductionCreateRequest,
    TransactionCancelRequest,
)
from app.services.text_sanitize import (
    DISALLOWED_DISPLAY_CHAR_RANGES,
    UNSAFE_STORAGE_CHAR_RANGES,
    has_disallowed_display_chars,
    has_unsafe_storage_chars,
    reject_disallowed_display_chars,
)
from tests.test_katadzuke_api import (
    _auth,
    _create_case,
    _create_transaction,
    _make_admin,
    _signup_user,
    _verified_operator,
    create_test_app,
)


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    from httpx import ASGITransport

    test_app = create_test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


async def _post_json_allow_surrogates(
    client: AsyncClient, url: str, payload: dict[str, object], headers: dict[str, str]
) -> Response:
    """孤立サロゲートを含む JSON ボディを送信する。

    ``httpx`` の ``json=`` 引数は内部で ``json.dumps(..., ensure_ascii=False)`` してから
    UTF-8 へエンコードするため、孤立サロゲート（例: ``chr(0xD800)``）を含む値があると
    送信前に ``UnicodeEncodeError`` になる（実測）。``ensure_ascii=True`` で ``\\uXXXX``
    形式へエスケープしてから ASCII バイト列として ``content=`` で送ることで、サーバー側の
    ``json.loads`` が同じ孤立サロゲートへ復元した状態で受け取れるようにする。
    """
    body_bytes = json.dumps(payload, ensure_ascii=True).encode("ascii")
    return await client.post(
        url, content=body_bytes, headers={**headers, "content-type": "application/json"}
    )


# ──────────────────────────── 単体: DISALLOWED_DISPLAY_CHAR_RANGES ────────────────────────────
# 8範囲の両端・中間（コードポイントは整数から chr() で組み立てる。SPEC 3節）。
_REJECTED_BOUNDARY_AND_MID_POINTS: tuple[int, ...] = (
    0x0000, 0x0009, 0x0005,  # C0（NUL〜タブ）両端・中間
    0x000B, 0x001F, 0x0010,  # C0（改行除く）両端・中間
    0x007F, 0x009F, 0x0085,  # DEL・C1 両端・中間（0x0085=NEL）
    0x061C,  # ALM（単一点）
    0x200E, 0x200F,  # LRM・RLM 両端
    0x202A, 0x202E, 0x202C,  # LRE-RLO 両端・中間（0x202C=PDF）
    0x2066, 0x2069, 0x2068,  # LRI-PDI 両端・中間（0x2068=FSI）
    0xD800, 0xDFFF, 0xDC00,  # サロゲート 両端・中間
)
# 8範囲それぞれの直前・直後（拒否範囲に入らないはずの隣接点）。
_ALLOWED_ADJACENT_POINTS: tuple[int, ...] = (
    0x000A,  # LF（改行。C0範囲から明示的に除外）
    0x0020,  # 空白（0x001F の直後）
    0x00A0,  # NBSP（0x009F の直後）
    0x061B,  # ALM の直前
    0x061D,  # ALM の直後
    0x200D,  # ZWJ（LRM の直前）
    0x2029,  # PARAGRAPH SEPARATOR（LRE の直前）
    0x202F,  # NARROW NO-BREAK SPACE（RLO の直後）
    0x2065,  # 未割り当て（LRI の直前）
    0x206A,  # INHIBIT SYMMETRIC SWAPPING（PDI の直後）
)

# D-3（web/src/lib/text-guard.test.mts）と同じ「変更されない」許可文字の一覧。
_ALLOWED_TEXT_SAMPLES: tuple[str, ...] = (
    # ZWJ で連結した家族絵文字（Cf を一括拒否すると壊れる合成の例）。
    chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467),
    # タグ文字による国旗（イングランド）。0xE0067 等は Cf。
    chr(0x1F3F4) + chr(0xE0067) + chr(0xE0062) + chr(0xE0065) + chr(0xE006E) + chr(0xE0067) + chr(0xE007F),
    # 地域指示子の組み合わせによる国旗（日本）。
    chr(0x1F1EF) + chr(0x1F1F5),
    chr(0x200C),  # ZWNJ
    chr(0x200B),  # ZWSP
    chr(0xFEFF),  # BOM
    chr(0x00AD),  # ソフトハイフン
    chr(0xE000),  # Co（私用領域）
    chr(0xF0000),  # Co（補助面の私用領域）
    chr(0x2028),  # LINE SEPARATOR（Zl）
    chr(0x2029),  # PARAGRAPH SEPARATOR（Zp）
    chr(0x0378),  # 未割り当て（Cn）
    chr(0x00A0),  # NBSP
    chr(0xFE0F),  # VS16（異体字セレクタ）
    chr(0x206A),  # 非推奨の書式文字（Cf だが拒否範囲外）
    "こんにちは",
)


def test_disallowed_display_chars_rejects_boundary_and_mid_points() -> None:
    for cp in _REJECTED_BOUNDARY_AND_MID_POINTS:
        assert has_disallowed_display_chars(chr(cp)), f"拒否されるべき: {hex(cp)}"


def test_disallowed_display_chars_allows_adjacent_points() -> None:
    for cp in _ALLOWED_ADJACENT_POINTS:
        assert not has_disallowed_display_chars(chr(cp)), f"許可されるべき: {hex(cp)}"


def test_disallowed_display_chars_allows_known_safe_samples() -> None:
    for sample in _ALLOWED_TEXT_SAMPLES:
        assert not has_disallowed_display_chars(sample), f"許可されるべき: {sample!r}"


def test_disallowed_display_chars_matches_unicodedata_over_full_bmp() -> None:
    """拒否対象＝(Cc から改行 U+000A を除いたもの) ∪ Cs ∪ Bidi_Control 12字、が
    BMP 全体（U+0000–U+FFFF）で一致することを確認する（DISALLOWED_DISPLAY_CHAR_RANGES
    が根拠 docstring に書いた対象と実際にズレていないことの回帰確認）。
    """
    bidi_control_singles = {0x061C, 0x200E, 0x200F}

    def expected(cp: int) -> bool:
        ch = chr(cp)
        category = unicodedata.category(ch)
        if category == "Cc" and cp != 0x0A:
            return True
        if category == "Cs":
            return True
        if cp in bidi_control_singles:
            return True
        if 0x202A <= cp <= 0x202E:
            return True
        if 0x2066 <= cp <= 0x2069:
            return True
        return False

    mismatches = [
        hex(cp)
        for cp in range(0x0000, 0x10000)
        if has_disallowed_display_chars(chr(cp)) != expected(cp)
    ]
    assert mismatches == []


def test_disallowed_display_char_ranges_match_unicodedata_bidirectional_explicit() -> None:
    """unicodedata.bidirectional が明示的双方向書式文字
    （LRE/RLE/PDF/LRO/RLO/LRI/RLI/FSI/PDI）と判定するコードポイントの集合が、
    0x202A–0x202E ∪ 0x2066–0x2069 の合併と BMP 全体で完全一致することを確認する
    （この2範囲の外に Bidi 明示的書式文字が存在しない、という前提の検証）。
    """
    bidi_explicit_categories = {"LRE", "RLE", "PDF", "LRO", "RLO", "LRI", "RLI", "FSI", "PDI"}
    actual = {
        cp
        for cp in range(0x0000, 0x10000)
        if unicodedata.bidirectional(chr(cp)) in bidi_explicit_categories
    }
    expected = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
    assert actual == expected


def test_unsafe_storage_chars_match_nul_and_lone_surrogates_over_full_bmp() -> None:
    """has_unsafe_storage_chars が「NUL または孤立サロゲート」と BMP 全体で一致する。"""
    mismatches = [
        hex(cp)
        for cp in range(0x0000, 0x10000)
        if has_unsafe_storage_chars(chr(cp)) != (cp == 0x0000 or 0xD800 <= cp <= 0xDFFF)
    ]
    assert mismatches == []


def test_disallowed_display_char_ranges_constant_matches_defined_boundaries() -> None:
    """DISALLOWED_DISPLAY_CHAR_RANGES 定数自体が期待する8範囲と一致すること
    （関数の実装ではなく定数定義そのものの回帰確認）。"""
    assert DISALLOWED_DISPLAY_CHAR_RANGES == (
        (0x0000, 0x0009),
        (0x000B, 0x001F),
        (0x007F, 0x009F),
        (0x061C, 0x061C),
        (0x200E, 0x200F),
        (0x202A, 0x202E),
        (0x2066, 0x2069),
        (0xD800, 0xDFFF),
    )
    assert UNSAFE_STORAGE_CHAR_RANGES == ((0x0000, 0x0000), (0xD800, 0xDFFF))


# ──────────────────────────── モデル直接検証 ────────────────────────────
# B節の表12欄。拒否文字での ValidationError・許可文字の素通し・Optional 欄の
# None/省略を parametrize で確認する。


@dataclass(frozen=True)
class _DisplayTextFieldCase:
    model_cls: type[pydantic.BaseModel]
    field_name: str
    field_label: str
    # 対象フィールド以外に必要な最小限のキーワード引数（対象フィールドの値は
    # 各テストが動的に差し込むため含めない）。
    base_kwargs: dict[str, object] = field(default_factory=dict)
    optional: bool = True


# CaseCreateRequest 用の共通ベース（purpose/prefecture/city/items/photos は必須）。
_CASE_BASE_KWARGS: dict[str, object] = {
    "purpose": "その他",
    "prefecture": "東京都",
    "city": "渋谷区",
    "items": [],
    "photos": [],
}
_CASE_BASE_KWARGS_WITHOUT_CITY: dict[str, object] = {
    k: v for k, v in _CASE_BASE_KWARGS.items() if k != "city"
}

_DISPLAY_TEXT_FIELD_CASES: tuple[_DisplayTextFieldCase, ...] = (
    _DisplayTextFieldCase(MessageCreateRequest, "body", "メッセージ", {}, optional=False),
    _DisplayTextFieldCase(BidCreateRequest, "message", "入札メッセージ", {"amount": 1000}),
    _DisplayTextFieldCase(BidUpdateRequest, "message", "入札メッセージ", {"amount": 1000}),
    _DisplayTextFieldCase(
        ReductionCreateRequest, "reason", "減額理由", {"requested_amount": 1000}, optional=False
    ),
    _DisplayTextFieldCase(TransactionCancelRequest, "reason", "キャンセル理由", {}),
    _DisplayTextFieldCase(CaseCancelRequest, "reason", "取り下げ理由", {}),
    _DisplayTextFieldCase(OperatorProfileUpdateRequest, "intro_message", "業者からのメッセージ", {}),
    _DisplayTextFieldCase(OperatorProfileUpdateRequest, "business_hours", "対応時間", {}),
    _DisplayTextFieldCase(
        CaseCreateRequest, "city", "市区町村", _CASE_BASE_KWARGS_WITHOUT_CITY, optional=False
    ),
    _DisplayTextFieldCase(
        CaseCreateRequest, "address_detail", "番地・建物名・部屋番号", _CASE_BASE_KWARGS
    ),
    _DisplayTextFieldCase(CaseCreateRequest, "housing_type", "住居タイプ", _CASE_BASE_KWARGS),
    _DisplayTextFieldCase(CaseCreateRequest, "floor_plan", "間取り", _CASE_BASE_KWARGS),
)

# min_length=10（ReductionCreateRequest.reason）を満たす共通の接頭辞（12文字）。
# 他のフィールドは min_length が無いか1のため、この接頭辞でも問題なく満たす。
_TEXT_PREFIX = "減額理由のテスト文章です"

# 代表的な拒否文字（NUL・タブ・CR・ESC・DEL・NEL・ALM・LRM・RLO・LRI・PDI）。どれも ValidationError になる。
_BAD_DISPLAY_CHARS: dict[str, str] = {
    "NUL": chr(0x00),
    "タブ": chr(0x09),
    "CR": chr(0x0D),
    "ESC": chr(0x1B),
    "DEL": chr(0x7F),
    "NEL": chr(0x85),
    "ALM": chr(0x061C),
    "LRM": chr(0x200E),
    "RLO": chr(0x202E),
    "LRI": chr(0x2066),
    "PDI": chr(0x2069),
}


def _case_id(case: _DisplayTextFieldCase) -> str:
    return f"{case.model_cls.__name__}.{case.field_name}"


@pytest.mark.parametrize("case", _DISPLAY_TEXT_FIELD_CASES, ids=_case_id)
@pytest.mark.parametrize("bad_char_name, bad_char", list(_BAD_DISPLAY_CHARS.items()))
def test_display_text_field_rejects_bad_chars(
    case: _DisplayTextFieldCase, bad_char_name: str, bad_char: str
) -> None:
    value = _TEXT_PREFIX + bad_char
    kwargs = {**case.base_kwargs, case.field_name: value}
    with pytest.raises(pydantic.ValidationError) as exc_info:
        case.model_cls(**kwargs)
    messages = [e["msg"] for e in exc_info.value.errors()]
    expected_msg_fragment = f"{case.field_label}に制御文字を含めることはできません。"
    assert any(expected_msg_fragment in m for m in messages), messages


@pytest.mark.parametrize("case", _DISPLAY_TEXT_FIELD_CASES, ids=_case_id)
def test_display_text_field_allows_safe_text_unchanged(case: _DisplayTextFieldCase) -> None:
    """許可文字（絵文字・改行等を含む）は一切変更されずそのまま値になる。"""
    value = _TEXT_PREFIX + "こんにちは" + chr(0x1F600) + chr(0x0A) + "続き"
    kwargs = {**case.base_kwargs, case.field_name: value}
    instance = case.model_cls(**kwargs)
    assert getattr(instance, case.field_name) == value


@pytest.mark.parametrize(
    "case", [c for c in _DISPLAY_TEXT_FIELD_CASES if c.optional], ids=_case_id
)
def test_display_text_field_allows_none_and_omission(case: _DisplayTextFieldCase) -> None:
    """Optional 欄は None 明示送信・キー省略のどちらも通り、値は None になる。"""
    instance_with_none = case.model_cls(**{**case.base_kwargs, case.field_name: None})
    assert getattr(instance_with_none, case.field_name) is None

    instance_omitted = case.model_cls(**case.base_kwargs)
    assert getattr(instance_omitted, case.field_name) is None


def test_bid_update_request_message_omitted_not_in_fields_set() -> None:
    """BidUpdateRequest.message を省略すると model_fields_set に入らない
    （bids.py の PATCH /cases/{case_id}/bids/me が「省略＝現状維持」と判定する前提）。
    """
    instance = BidUpdateRequest(amount=1000)
    assert "message" not in instance.model_fields_set


def test_case_create_address_detail_lone_surrogate_rejected_in_japanese() -> None:
    """address_detail は Field の長さ制約を持たないが、孤立サロゲートも同じ日本語文言で
    拒否される（従来は制約なしのため asyncpg の DataError で 500 になっていた欄）。"""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        CaseCreateRequest(**{**_CASE_BASE_KWARGS, "address_detail": "住所" + chr(0xD800)})
    messages = [e["msg"] for e in exc_info.value.errors()]
    assert any("番地・建物名・部屋番号に制御文字を含めることはできません。" in m for m in messages)


def test_reject_disallowed_display_chars_none_passthrough() -> None:
    assert reject_disallowed_display_chars(None, field_label="テスト") is None


def test_reject_disallowed_display_chars_returns_value_unchanged_when_allowed() -> None:
    value = "そのまま" + chr(0x1F600)
    assert reject_disallowed_display_chars(value, field_label="テスト") == value


# ──────────────────────────── HTTP 配線 ────────────────────────────


async def test_message_body_rlo_rejected_and_no_message_persisted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """チャット本文の RLO は 422 で拒否され、メッセージは1件も保存されない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "user-msg-rlo@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op-msg-rlo@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": "こんにちは" + chr(0x202E)},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    count = await db_session.scalar(
        select(func.count()).select_from(Message).where(Message.transaction_id == uuid.UUID(txn_id))
    )
    assert count == 0


async def test_message_body_allowed_chars_saved_as_is(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ZWJ 連結絵文字・国旗・改行を含む本文は201で保存され、本文が完全一致する。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "user-msg-ok@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op-msg-ok@example.com")
    _, txn_id = await _create_transaction(client, user_token, op_token)

    body = (
        "よろしくお願いします"
        + chr(0x1F468) + chr(0x200D) + chr(0x1F469)  # ZWJ 連結
        + chr(0x0A)
        + chr(0x1F1EF) + chr(0x1F1F5)  # 国旗（日本）
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/messages",
        json={"body": body},
        headers=_auth(user_token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["body"] == body


async def test_bid_create_message_tab_rejected_and_no_bid_persisted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """入札作成時の message のタブは422で拒否され、入札は1件も保存されない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "user-bid-tab@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op-bid-tab@example.com")
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/bids",
        json={"amount": 10_000, "message": "タブ" + chr(0x09) + "入り"},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text
    count = await db_session.scalar(
        select(func.count()).select_from(Bid).where(Bid.case_id == uuid.UUID(case["id"]))
    )
    assert count == 0


async def test_bid_update_message_rlo_rejected_amount_and_revision_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """入札引き上げの message の RLO は422で拒否され、金額・引き上げ回数が変わらない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "user-bid-rlo@example.com")
    op_token, _ = await _verified_operator(client, db_session, admin_token, "op-bid-rlo@example.com")
    case = await _create_case(client, user_token)
    r0 = await client.post(
        f"/api/v1/cases/{case['id']}/bids", json={"amount": 10_000}, headers=_auth(op_token)
    )
    assert r0.status_code == 201, r0.text
    bid_id = r0.json()["id"]

    r1 = await client.patch(
        f"/api/v1/cases/{case['id']}/bids/me",
        json={"amount": 20_000, "message": "引き上げ理由" + chr(0x202E)},
        headers=_auth(op_token),
    )
    assert r1.status_code == 422, r1.text

    refreshed = await db_session.scalar(select(Bid).where(Bid.id == uuid.UUID(bid_id)))
    assert refreshed is not None
    assert refreshed.amount == 10_000
    assert refreshed.revision_count == 0


async def test_reduction_reason_nul_rejected_and_no_reduction_persisted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """減額申請の reason の NUL は422で拒否され、申請は1件も保存されない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "user-reduction-nul@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "op-reduction-nul@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/reduction",
        json={"requested_amount": 1_000, "reason": _TEXT_PREFIX + chr(0x00)},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text
    count = await db_session.scalar(
        select(func.count())
        .select_from(ReductionRequest)
        .where(ReductionRequest.transaction_id == uuid.UUID(txn_id))
    )
    assert count == 0


async def test_transaction_cancel_reason_cr_rejected_status_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """成約キャンセル理由の CR は422で拒否され、成約の状態が変わらない。"""
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, "user-txn-cancel-cr@example.com")
    op_token, _ = await _verified_operator(
        client, db_session, admin_token, "op-txn-cancel-cr@example.com"
    )
    _, txn_id = await _create_transaction(client, user_token, op_token)

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/cancel",
        json={"reason": "都合により" + chr(0x0D)},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    txn = await db_session.scalar(select(Transaction).where(Transaction.id == uuid.UUID(txn_id)))
    assert txn is not None
    assert txn.status == "pending"


async def test_case_cancel_reason_lri_rejected_status_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """出品取り下げ理由の LRI は422で拒否され、案件の状態が変わらない。"""
    user_token = await _signup_user(client, "user-case-cancel-lri@example.com")
    case = await _create_case(client, user_token)

    r = await client.post(
        f"/api/v1/cases/{case['id']}/cancel",
        json={"reason": "都合により" + chr(0x2066)},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    updated = await db_session.scalar(select(Case).where(Case.id == uuid.UUID(case["id"])))
    assert updated is not None
    assert updated.status == "open"


async def test_operator_profile_update_display_text_rejected_and_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """業者プロフィールの intro_message・business_hours の拒否文字は422で、
    直前に PUT した基準値のまま変わらない。"""
    admin_token = await _make_admin(client, db_session)
    op_token, op_id = await _verified_operator(
        client, db_session, admin_token, "op-profile-guard@example.com"
    )
    baseline = {
        "areas": [],
        "categories": [],
        "strong_categories": [],
        "business_hours": "平日9時から18時",
        "intro_message": "よろしくお願いします。",
        "show_message": True,
        "accept_unsellable": False,
    }
    r0 = await client.put("/api/v1/operator/profile", json=baseline, headers=_auth(op_token))
    assert r0.status_code == 200, r0.text

    bad = {
        **baseline,
        "intro_message": "自己紹介" + chr(0x202E),
        "business_hours": "対応時間" + chr(0x09),
    }
    r1 = await client.put("/api/v1/operator/profile", json=bad, headers=_auth(op_token))
    assert r1.status_code == 422, r1.text

    profile = await db_session.scalar(
        select(OperatorProfile).where(OperatorProfile.operator_id == uuid.UUID(op_id))
    )
    assert profile is not None
    assert profile.intro_message == "よろしくお願いします。"
    assert profile.business_hours == "平日9時から18時"


@pytest.mark.parametrize(
    "field_name, bad_value",
    [
        ("city", chr(0x09)),
        ("address_detail", chr(0x202E)),
        ("housing_type", chr(0x0D)),
        ("floor_plan", chr(0xD800)),
    ],
)
async def test_case_create_display_text_rejected_no_case_persisted(
    client: AsyncClient, db_session: AsyncSession, field_name: str, bad_value: str
) -> None:
    """案件作成の city/address_detail/housing_type/floor_plan の拒否文字は422で、
    案件が1件も作られない。"""
    user_token = await _signup_user(client, f"user-case-create-{field_name}@example.com")
    payload: dict[str, object] = {
        "purpose": "その他",
        "prefecture": "東京都",
        "city": "渋谷区",
        "photos": [],
        "items": [],
    }
    base_value = str(payload.get(field_name, "テスト値"))
    payload[field_name] = base_value + bad_value

    count_before = await db_session.scalar(select(func.count()).select_from(Case))
    # floor_plan の孤立サロゲートケースは httpx の json= が送信前に UnicodeEncodeError
    # になるため、全ケースを ASCII エスケープ経由の送信で統一する。
    r = await _post_json_allow_surrogates(
        client, "/api/v1/cases", payload, _auth(user_token)
    )
    assert r.status_code == 422, r.text
    count_after = await db_session.scalar(select(func.count()).select_from(Case))
    assert count_after == count_before == 0
