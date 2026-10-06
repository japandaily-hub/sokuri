"""日程調整 API（schedule/confirm）の入力検証の回帰テスト。

2026-09-25 セキュリティレビュー（Low）・2026-09-26 日程API入力検証レビュー対応のうち、
日程候補の構造化（日付＋時刻・propose は {candidates}・accept 新設）後も有効な部分:
- ScheduleConfirmRequest.visit_time_slot / note への制御文字・右から左に書く文字・
  行区切り・文字数超過の拒否（schemas_katadzuke.py）。
- confirm_schedule が固定5択（SCHEDULE_FIXED_TIME_SLOTS）以外を弾くこと。
- note（業者へのひとこと）を運営名義の schedule_confirmed から分離し、依頼者本人の
  発言として別メッセージにすること。
- SCHEDULE_FIXED_TIME_SLOTS と web/src/lib/visit-slots.ts の VISIT_TIME_SLOTS の一致。

構造化により次は不要になったため、このファイルから外した（理由: 業者の自由記述の候補
ラベルをサーバーが受け取らず、日付・時刻から作り直すため）:
- propose の slots（制御文字・文字数・複数日付・実在しない日付・年入りラベル）の検証と、
  confirm のラベル照合（_assert_offered_time_slot / _assert_slot_date_matches /
  _slot_dates 等）。propose の入力形・日付範囲・重複は tests/test_schedule_structured.py、
  日付・時刻・ラベルの純関数は tests/test_visit_schedule_unit.py が検証する。
- 業者の候補ラベルを運営名義の確定メッセージ本文に入れない（SEC-L1）ための
  _fixed_time_slot_of / operator_slot_label。確定メッセージの本文はサーバーが日付・時刻から
  作るため、業者の文言が入る経路そのものが無い（tests/test_schedule_structured.py）。
- 訪問日の JST 判定を ScheduleConfirmRequest の validator（_jst_today）で行う方式。
  confirm_schedule が now_jst() で判定する（tests/test_schedule_structured.py の
  test_confirm_date_range_in_jst / test_confirm_today_follows_jst_not_utc）。

in-memory SQLite + ASGITransport（conftest.py のフィクスチャを利用）。既存の
tests/test_txn_state_integrity.py・tests/test_r8_abnormal_guards.py と同様、
ヘルパーはこのファイル内に自己完結で複製する（既存スタイルの踏襲）。
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import SCHEDULE_FIXED_TIME_SLOTS
from app.services.visit_schedule import FIXED_VISIT_TIME_SLOTS

# 双方向制御・書式・ゼロ幅・私用領域等、拒否対象の制御文字
# （schemas_katadzuke._REJECTED_CONTROL_CATEGORIES = Cc/Cf/Co/Cs の代表例）。
# GitHub の hidden bidirectional Unicode 警告（Trojan Source, CVE-2021-42574）を
# 避けるため、不可視文字・右から左に書く文字はソースに生で書かず chr() で組み立てる。
_RLO = chr(0x202E)  # 右から左への上書き（RIGHT-TO-LEFT OVERRIDE）
_LRI = chr(0x2066)  # 左から右への隔離（LEFT-TO-RIGHT ISOLATE）
_ZWSP = chr(0x200B)  # ゼロ幅スペース（ZERO WIDTH SPACE）
_BOM = chr(0xFEFF)  # BOM / ゼロ幅無空白
_WORD_JOINER = chr(0x2060)  # WORD JOINER
_ALM = chr(0x061C)  # アラビア文字方向マーク（ARABIC LETTER MARK）
_SHY = chr(0x00AD)  # ソフトハイフン（SOFT HYPHEN）
_PUA = chr(0xE000)  # 私用領域（PRIVATE USE AREA）
CONTROL_CHAR_SAMPLES = [_RLO, _LRI, _ZWSP, _BOM, _WORD_JOINER, _ALM, _SHY, "\n", "\t", _PUA]
CONTROL_CHAR_IDS = [
    "rlo", "lri", "zwsp", "bom", "word_joiner", "alm", "shy", "newline", "tab", "pua",
]

# Zl（LINE SEPARATOR）/ Zp（PARAGRAPH SEPARATOR）。改行を許可しない項目でも
# 見た目上の改行を作れてしまっていた（日程検証レビュー SEC-L3）。
_LINE_SEPARATOR = chr(0x2028)
_PARAGRAPH_SEPARATOR = chr(0x2029)

# 双方向クラス R/AL/AN の代表文字（日程検証レビュー SEC-L2）。
_HEBREW_GERESH = chr(0x05F3)  # R（HEBREW PUNCTUATION GERESH）
_HEBREW_ALEF = chr(0x05D0)  # R（HEBREW LETTER ALEF）
_ARABIC_ALEF = chr(0x0627)  # AL（ARABIC LETTER ALEF）
_ARABIC_INDIC_DIGIT_ONE = chr(0x0661)  # AN（ARABIC-INDIC DIGIT ONE）
RTL_BIDI_CHAR_SAMPLES = [_HEBREW_GERESH, _HEBREW_ALEF, _ARABIC_ALEF, _ARABIC_INDIC_DIGIT_ONE]
RTL_BIDI_CHAR_IDS = ["hebrew_geresh_R", "hebrew_alef_R", "arabic_alef_AL", "arabic_indic_digit_AN"]

# 固定5択のうちテストで具体値が何でもよい箇所に使う代表値。
_ANY_FIXED_SLOT = "時間指定なし"
assert _ANY_FIXED_SLOT in SCHEDULE_FIXED_TIME_SLOTS


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


async def _make_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    admin = User(
        email="sch_val_admin@katadzuke.jp",
        password_hash=hash_password("adminpass123"),
        name="管理者",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "sch_val_admin@katadzuke.jp", "password": "adminpass123"},
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


async def _verified_operator(
    client: AsyncClient,
    admin_token: str,
    email: str,
    company: str = "テスト片付け株式会社",
) -> tuple[str, str]:
    r = await client.post("/api/v1/admin/invites", json={}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    r = await client.post(
        "/api/v1/auth/operator/signup",
        json={
            "invite_code": code,
            "company_name": company,
            "email": email,
            "password": "operatorpass1",
            "license_number": "第123456789012号",
            "agreed": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    op_id = data["operator"]["id"]
    # 招待コード経由でも signup 直後は pending（2026-09-25 ユーザー決定）。
    # 許可証画像の提出 → 運営承認を経て active にする。
    r = await client.post(
        "/api/v1/operator/license-image",
        files={"file": ("license.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 256, "image/png")},
        headers=_auth(data["access_token"]),
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"/api/v1/admin/operators/{op_id}/verify",
        json={"verified": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    return data["access_token"], op_id


def _case_payload() -> dict:
    return {
        "purpose": "遺品整理",
        "prefecture": "東京都",
        "city": "世田谷区",
        "address_detail": "桜丘1-2-3 メゾン桜 101号室",
        "housing_type": "マンション",
        "floor_plan": "2LDK",
        "floor_number": 1,
        "has_elevator": False,
        "photos": [{"storage_key": f"{uuid.uuid4().hex}.jpg", "sort_order": 0}],
    }


async def _create_transaction(
    client: AsyncClient, user_token: str, op_token: str, amount: int = 30000
) -> str:
    """案件作成 → 入札 → 落札まで進め、transaction_id を返す。"""
    r = await client.post("/api/v1/cases", json=_case_payload(), headers=_auth(user_token))
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids", json={"amount": amount}, headers=_auth(op_token)
    )
    assert r.status_code == 201, r.text
    bid_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/cases/{case_id}/bids/{bid_id}/select", headers=_auth(user_token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _future_date(days: int = 7) -> date:
    """時限失敗を避けるため、固定日ではなく本日起点の動的な未来日を使う。"""
    return date.today() + timedelta(days=days)


async def _setup_txn(
    client: AsyncClient, db_session: AsyncSession, user_email: str, op_email: str
) -> tuple[str, str, str]:
    """admin/user/operator を作り、成約直後（pending）の取引まで進める。

    戻り値: (user_token, op_token, txn_id)
    """
    admin_token = await _make_admin(client, db_session)
    user_token = await _signup_user(client, user_email)
    op_token, _ = await _verified_operator(client, admin_token, op_email)
    txn_id = await _create_transaction(client, user_token, op_token)
    return user_token, op_token, txn_id


# ──────────────── confirm: 許可リスト（固定5択のみ） ────────────────


@pytest.mark.parametrize("fixed_slot", sorted(SCHEDULE_FIXED_TIME_SLOTS))
async def test_confirm_allows_each_fixed_time_slot_without_proposal(
    client: AsyncClient, db_session: AsyncSession, fixed_slot: str
):
    """業者からの提示が無くても、日程調整ページの固定5択なら確定できる。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "fixed_slot_user@example.com", "fixed_slot_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": _future_date().isoformat(), "visit_time_slot": fixed_slot},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["visit_time_slot"] == fixed_slot


async def test_confirm_rejects_arbitrary_time_slot_without_proposal(
    client: AsyncClient, db_session: AsyncSession
):
    """固定5択以外の任意文字列は422（schedule_client_outdated）になり、何も書き込まれない。
    業者の候補からの確定は accept 経由になったため、confirm は固定5択だけを受け付ける。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "arbitrary_slot_user@example.com", "arbitrary_slot_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": _future_date().isoformat(), "visit_time_slot": "深夜2:00〜3:00"},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "schedule_client_outdated"


# ──────────────── confirm: 制御文字（visit_time_slot / note） ────────────────


@pytest.mark.parametrize("bad_char", [_RLO, "\n", _ZWSP], ids=["rlo", "newline", "zwsp"])
async def test_confirm_rejects_control_chars_in_visit_time_slot(
    client: AsyncClient, db_session: AsyncSession, bad_char: str
):
    """visit_time_slot に双方向制御文字・改行・ゼロ幅文字を混ぜると422になる。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "confirm_ctrl_slot_user@example.com", "confirm_ctrl_slot_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={
            "visit_date": _future_date().isoformat(),
            "visit_time_slot": f"9:00〜12:00{bad_char}",
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text


async def test_confirm_rejects_visit_time_slot_too_long(
    client: AsyncClient, db_session: AsyncSession
):
    """visit_time_slot が33文字だと422になる
    （VISIT_TIME_SLOT_MAX_LENGTH＝32字。DB列 String(32) に合わせた上限を超過）。
    """
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "confirm_toolong_user@example.com", "confirm_toolong_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": _future_date().isoformat(), "visit_time_slot": "a" * 33},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text


async def test_confirm_rejects_control_chars_in_note(
    client: AsyncClient, db_session: AsyncSession
):
    """note に双方向制御文字を混ぜると422になる。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "confirm_note_ctrl_user@example.com", "confirm_note_ctrl_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={
            "visit_date": _future_date().isoformat(),
            "visit_time_slot": _ANY_FIXED_SLOT,
            "note": f"在宅{_RLO}confirmed",
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text


async def test_confirm_note_with_newline_is_kept_in_separated_message(
    client: AsyncClient, db_session: AsyncSession
):
    """note の改行は許可され、分離メッセージの本文に改行がそのまま残る。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "confirm_note_newline_user@example.com", "confirm_note_newline_op@example.com"
    )
    note = "玄関前に置きます。\nお電話ください。"
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={
            "visit_date": _future_date().isoformat(),
            "visit_time_slot": _ANY_FIXED_SLOT,
            "note": note,
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    messages = r.json()
    confirmed_index = next(i for i, m in enumerate(messages) if m["kind"] == "schedule_confirmed")
    note_message = messages[confirmed_index + 1]
    assert note_message["kind"] == "text"
    assert note_message["body"] == note
    assert "\n" in note_message["body"]


async def test_confirm_note_whitespace_only_creates_no_separate_message(
    client: AsyncClient, db_session: AsyncSession
):
    """note が空白のみ（strip後に空）の場合、分離メッセージは作られない。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "confirm_note_blank_user@example.com", "confirm_note_blank_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={
            "visit_date": _future_date().isoformat(),
            "visit_time_slot": _ANY_FIXED_SLOT,
            "note": "  　\n ",
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    kinds = [m["kind"] for m in r.json()]
    assert kinds == ["schedule_confirmed"]


# ──────────────── confirm: note 分離メッセージの可視性・未読 ────────────────


async def test_confirm_note_message_visible_to_operator_and_counts_as_unread(
    client: AsyncClient, db_session: AsyncSession
):
    """note の分離メッセージは業者から見て mine=False で schedule_confirmed の直後に並び、
    業者の未読数が1件増える（運営名義のシステムメッセージに連結しなくなった副作用の確認）。
    """
    user_token, op_token, txn_id = await _setup_txn(
        client,
        db_session,
        "confirm_note_visibility_user@example.com",
        "confirm_note_visibility_op@example.com",
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={
            "visit_date": _future_date().isoformat(),
            "visit_time_slot": _ANY_FIXED_SLOT,
            "note": "在宅確認済み",
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    messages = r.json()
    confirmed_index = next(i for i, m in enumerate(messages) if m["kind"] == "schedule_confirmed")
    note_message = messages[confirmed_index + 1]
    assert note_message["sender_type"] == "user"
    assert note_message["mine"] is False

    r = await client.get(f"/api/v1/transactions/{txn_id}", headers=_auth(op_token))
    assert r.status_code == 200, r.text
    assert r.json()["unread_count"] == 1


@pytest.mark.parametrize("bad_char", RTL_BIDI_CHAR_SAMPLES, ids=RTL_BIDI_CHAR_IDS)
async def test_confirm_rejects_rtl_bidi_chars_in_visit_time_slot(
    client: AsyncClient, db_session: AsyncSession, bad_char: str
):
    """双方向クラス R/AL/AN の文字を visit_time_slot に混ぜると422になる（日程検証レビュー SEC-L2）。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "confirm_rtl_user@example.com", "confirm_rtl_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={
            "visit_date": _future_date().isoformat(),
            "visit_time_slot": f"9:00〜12:00{bad_char}",
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text


async def test_confirm_rejects_unicode_line_separator_in_visit_time_slot(
    client: AsyncClient, db_session: AsyncSession
):
    """visit_time_slot に U+2028（Zl）を混ぜると422になる（日程検証レビュー SEC-L3）。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "confirm_zlzp_user@example.com", "confirm_zlzp_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={
            "visit_date": _future_date().isoformat(),
            "visit_time_slot": f"9:00〜12:00{_LINE_SEPARATOR}",
        },
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text


# ──────────────── 定数ガード: SCHEDULE_FIXED_TIME_SLOTS とフロントエンドの一致 ────────────────


def _read_frontend_time_slot_values() -> set[str]:
    """web/src/lib/visit-slots.ts の VISIT_TIME_SLOTS 配列から value を抜き出す。

    日程調整ページ（web/src/app/schedule/page.tsx）と業者の候補日提示フォームは、
    どちらもこの配列を import して時間帯の選択肢にしている（ボタン化 8dfda41 で
    schedule/page.tsx の TIME_SLOTS から移された）。
    """
    visit_slots = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "visit-slots.ts"
    text = visit_slots.read_text(encoding="utf-8")
    match = re.search(r"export const VISIT_TIME_SLOTS[^=]*=\s*\[(.*?)\n\];", text, re.DOTALL)
    assert match is not None, (
        "VISIT_TIME_SLOTS 配列が見つかりません（web/src/lib/visit-slots.ts の形式が変わった"
        "可能性があります。SCHEDULE_FIXED_TIME_SLOTS との一致テストを更新してください）。"
    )
    return set(re.findall(r'value:\s*"([^"]*)"', match.group(1)))


def test_schedule_fixed_time_slots_matches_frontend_time_slots():
    """SCHEDULE_FIXED_TIME_SLOTS は web/src/lib/visit-slots.ts の VISIT_TIME_SLOTS の
    value 集合と1文字違わず一致すること。ここがずれると、日程調整ページ（固定5択）
    からの確定が confirm_schedule（transactions.py）で422になる
    （2026-09-25 セキュリティレビュー Low 対応）。
    """
    assert SCHEDULE_FIXED_TIME_SLOTS == _read_frontend_time_slot_values()


def test_schedule_fixed_time_slots_is_the_server_fixed_slot_definition():
    """schemas の SCHEDULE_FIXED_TIME_SLOTS はサーバー側の単一の出所
    （services/visit_schedule.FIXED_VISIT_TIME_SLOTS）と同じ集合であること。"""
    assert SCHEDULE_FIXED_TIME_SLOTS == frozenset(FIXED_VISIT_TIME_SLOTS)
