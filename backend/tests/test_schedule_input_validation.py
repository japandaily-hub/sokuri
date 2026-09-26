"""日程調整 API（schedule/propose・schedule/confirm）の入力検証の回帰テスト。

2026-09-25 セキュリティレビュー（Low）対応:
- ScheduleProposeRequest.slots / ScheduleConfirmRequest.visit_time_slot・note への
  制御文字混入・空白のみ・文字数超過の拒否（schemas_katadzuke.py）。
- confirm_schedule が「業者提示済みの候補」か「日程調整ページの固定5択」以外を
  弾く許可リスト照合、および候補ラベル内の日付と visit_date の一致照合
  （app/api/v1/endpoints/transactions.py の _assert_offered_time_slot /
  _assert_slot_date_matches）。
- note（業者へのひとこと）を運営名義の schedule_confirmed システムメッセージから
  分離し、依頼者本人の発言として別メッセージにすること。

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
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.transactions import (
    _assert_slot_date_matches,
    _slot_dates,
    _slot_month_days,
    _slot_years,
)
from app.api.v1.router import api_router
from app.core.security import hash_password
from app.db.models.user import User
from app.db.session import get_session
from app.schemas_katadzuke import SCHEDULE_FIXED_TIME_SLOTS

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

# タイ数字（NFKC 正規化でも ASCII 化されない non-ASCII の数字。日程検証レビュー SEC-I1/SEC-I4）。
_THAI_DIGIT_NINE = chr(0x0E50 + 9)
_THAI_DIGIT_ONE = chr(0x0E50 + 1)

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
        json={"email": email, "password": "password123", "name": "テスト太郎"},
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


_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


def _dated_slot_label(d: date, time_range: str = "10:00〜12:00") -> str:
    """業者提示の日付入り候補ラベルを動的日付で組み立てる（例「9月7日（日）10:00〜12:00」）。"""
    dow = "月火水木金土日"[d.weekday()]
    return f"{d.month}月{d.day}日（{dow}）{time_range}"


def _fullwidth_dated_slot_label(d: date, time_range: str = "10:00〜12:00") -> str:
    """全角数字の候補ラベル（NFKC 正規化前提の日付照合を検証するため）。"""
    dow = "月火水木金土日"[d.weekday()]
    fw_month = str(d.month).translate(_FULLWIDTH_DIGITS)
    fw_day = str(d.day).translate(_FULLWIDTH_DIGITS)
    return f"{fw_month}月{fw_day}日（{dow}）{time_range}"


def _spaced_dated_slot_label(d: date, time_range: str = "10:00〜12:00") -> str:
    """月と日の間に空白を挟んだ候補ラベル（例「10月 1日 10:00〜12:00」）。"""
    return f"{d.month}月 {d.day}日 {time_range}"


def _ligature_month(month: int) -> str:
    """1〜12月の電信記号合字（例 month=9 で「㋈」。NFKC正規化で「9月」に分解される）。"""
    return chr(0x32C0 + month - 1)


def _ligature_day(day: int) -> str:
    """1〜31日の電信記号合字（例 day=1 で「㏠」。NFKC正規化で「1日」に分解される）。"""
    return chr(0x33E0 + day - 1)


def _ligature_dated_slot_label(d: date, time_range: str = "10:00〜12:00") -> str:
    """電信記号合字の候補ラベル（例 d=9/1 で「㋈㏠10:00〜12:00」＝日程検証レビュー QA-L7）。"""
    return f"{_ligature_month(d.month)}{_ligature_day(d.day)}{time_range}"


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


# ──────────────── propose: 制御文字・空白のみ・文字数 ────────────────


@pytest.mark.parametrize("bad_char", CONTROL_CHAR_SAMPLES, ids=CONTROL_CHAR_IDS)
async def test_propose_rejects_control_chars_in_slot(
    client: AsyncClient, db_session: AsyncSession, bad_char: str
):
    """双方向制御文字・ゼロ幅文字等を候補ラベルに混ぜると422になる。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_ctrl_user@example.com", "propose_ctrl_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [f"2026-07-10 午前{bad_char}"]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text


async def test_propose_slot_max_length_32_is_accepted(
    client: AsyncClient, db_session: AsyncSession
):
    """VISIT_TIME_SLOT_MAX_LENGTH（32文字）ちょうどは受理される。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_len32_user@example.com", "propose_len32_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["a" * 32]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text


async def test_propose_slot_max_length_33_is_rejected(
    client: AsyncClient, db_session: AsyncSession
):
    """33文字は422になる（VISIT_TIME_SLOT_MAX_LENGTH＝32字。DB列 String(32) に合わせた上限）。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_len33_user@example.com", "propose_len33_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["a" * 33]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("blank", [" ", "　"], ids=["halfwidth_space", "fullwidth_space"])
async def test_propose_rejects_whitespace_only_slot(
    client: AsyncClient, db_session: AsyncSession, blank: str
):
    """空白のみ（半角・全角）の候補は422になる。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_blank_user@example.com", "propose_blank_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [blank]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text


# ──────────────── propose: 1候補に複数日付を混在させる細工 ────────────────


async def test_propose_rejects_slot_with_multiple_different_dates(
    client: AsyncClient, db_session: AsyncSession
):
    """1つの候補ラベルに異なる日付が2つ含まれる場合は422（確定時の日付突合が破綻するため）。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_multidate_user@example.com", "propose_multidate_op@example.com"
    )
    d1 = _future_date(5)
    d2 = _future_date(6)
    slot = f"{d1.month}月{d1.day}日 {d2.month}月{d2.day}日"
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [slot]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "1つの候補日に複数の日付は入れられません。候補を分けて入力してください。"


async def test_propose_allows_duplicate_same_date_mentions_in_one_slot(
    client: AsyncClient, db_session: AsyncSession
):
    """同じ日付の重複表記（開始〜終了で同日を2回書く等）は1種類として許可される。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_samedate_user@example.com", "propose_samedate_op@example.com"
    )
    d = _future_date(5)
    slot = f"{d.month}月{d.day}日 10:00〜{d.month}月{d.day}日 12:00"
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [slot]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text


# ──────────────── confirm: 許可リスト（固定5択 or 業者提示済み候補） ────────────────


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
    """固定5択でも業者提示済みでもない任意文字列は422になる。"""
    user_token, _, txn_id = await _setup_txn(
        client, db_session, "arbitrary_slot_user@example.com", "arbitrary_slot_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": _future_date().isoformat(), "visit_time_slot": "深夜2:00〜3:00"},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == (
        "候補にない時間帯は指定できません。業者が提示した候補日か、日程調整ページの時間帯から選んでください。"
    )


async def test_confirm_accepts_offered_dated_slot_matching_visit_date(
    client: AsyncClient, db_session: AsyncSession
):
    """業者提示済みの日付入り候補で visit_date が一致すれば確定でき、確定メッセージに
    ISO日付を重ねない（候補ラベル自体に日付が含まれるため）。
    """
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "dated_slot_user@example.com", "dated_slot_op@example.com"
    )
    visit_date = _future_date(10)
    label = _dated_slot_label(visit_date)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": visit_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["visit_time_slot"] == label

    r = await client.get(f"/api/v1/transactions/{txn_id}/messages", headers=_auth(user_token))
    assert r.status_code == 200, r.text
    confirmed = next(m for m in r.json() if m["kind"] == "schedule_confirmed")
    assert confirmed["body"] == f"訪問日程が {label} に確定しました。"


async def test_confirm_accepts_older_of_two_proposals(
    client: AsyncClient, db_session: AsyncSession
):
    """ChatPanel は直近だけでなく過去の提示カードからも確定できるため、2件目の提示後でも
    1件目（古い方）の候補で確定できる。
    """
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "two_proposals_user@example.com", "two_proposals_op@example.com"
    )
    old_date = _future_date(5)
    old_label = _dated_slot_label(old_date)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [old_label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    new_date = _future_date(12)
    new_label = _dated_slot_label(new_date)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [new_label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": old_date.isoformat(), "visit_time_slot": old_label},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text


async def test_confirm_rejects_slot_offered_in_a_different_transaction(
    client: AsyncClient, db_session: AsyncSession
):
    """別の取引に提示された候補ラベルを流用して確定しようとすると422になる。"""
    user_token, op_token, txn1_id = await _setup_txn(
        client, db_session, "cross_txn_user@example.com", "cross_txn_op@example.com"
    )
    txn2_id = await _create_transaction(client, user_token, op_token)

    visit_date = _future_date(6)
    label = _dated_slot_label(visit_date)
    r = await client.post(
        f"/api/v1/transactions/{txn1_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/transactions/{txn2_id}/schedule/confirm",
        json={"visit_date": visit_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == (
        "候補にない時間帯は指定できません。業者が提示した候補日か、日程調整ページの時間帯から選んでください。"
    )


# ──────────────── confirm: 候補日ラベルの日付と visit_date の突合 ────────────────


async def test_confirm_rejects_offered_slot_when_visit_date_mismatches(
    client: AsyncClient, db_session: AsyncSession
):
    """業者提示済みの候補でも、ラベル内の日付と visit_date が違えば422になる。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "date_mismatch_user@example.com", "date_mismatch_op@example.com"
    )
    proposed_date = _future_date(9)
    label = _dated_slot_label(proposed_date)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    wrong_date = proposed_date + timedelta(days=3)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": wrong_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "候補日の日付と訪問日が一致しません。候補日をもう一度選び直してください。"


async def test_confirm_fullwidth_digit_slot_date_match(
    client: AsyncClient, db_session: AsyncSession
):
    """全角数字の候補ラベル（NFKC正規化）でも visit_date が一致すれば確定できる。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "fullwidth_match_user@example.com", "fullwidth_match_op@example.com"
    )
    visit_date = _future_date(11)
    label = _fullwidth_dated_slot_label(visit_date)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": visit_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text


async def test_confirm_fullwidth_digit_slot_date_mismatch(
    client: AsyncClient, db_session: AsyncSession
):
    """全角数字の候補ラベルでも、日付が違えば422になる（NFKC正規化後の照合が効いている確認）。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "fullwidth_mismatch_user@example.com", "fullwidth_mismatch_op@example.com"
    )
    proposed_date = _future_date(13)
    label = _fullwidth_dated_slot_label(proposed_date)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    wrong_date = proposed_date + timedelta(days=2)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": wrong_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "候補日の日付と訪問日が一致しません。候補日をもう一度選び直してください。"


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


# ──────────────── propose/confirm: 右から左に書く文字（R/AL/AN）の拒否 ────────────────


@pytest.mark.parametrize("bad_char", RTL_BIDI_CHAR_SAMPLES, ids=RTL_BIDI_CHAR_IDS)
async def test_propose_rejects_rtl_bidi_chars_in_slot(
    client: AsyncClient, db_session: AsyncSession, bad_char: str
):
    """双方向クラス R/AL/AN の文字を候補ラベルに混ぜると422になる（日程検証レビュー SEC-L2）。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_rtl_user@example.com", "propose_rtl_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [f"2026-07-10 午前{bad_char}"]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text


# ──────────────── propose/confirm: 行区切り・段落区切り（Zl/Zp）の拒否 ────────────────


@pytest.mark.parametrize(
    "bad_char", [_LINE_SEPARATOR, _PARAGRAPH_SEPARATOR], ids=["line_separator", "paragraph_separator"]
)
async def test_propose_rejects_unicode_line_and_paragraph_separators(
    client: AsyncClient, db_session: AsyncSession, bad_char: str
):
    """Zl/Zp（U+2028・U+2029）は改行を許可しない候補日でも拒否される（日程検証レビュー SEC-L3）。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_zlzp_user@example.com", "propose_zlzp_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [f"2026-07-10 午前{bad_char}"]},
        headers=_auth(op_token),
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


# ──────────────── propose: 実在しない日付の拒否 ────────────────


@pytest.mark.parametrize("invalid_label", ["2月30日", "13月1日"], ids=["feb_30", "month_13"])
async def test_propose_rejects_nonexistent_calendar_date(
    client: AsyncClient, db_session: AsyncSession, invalid_label: str
):
    """実在しない (月, 日) の候補は422になる（日程検証レビュー SEC-I5）。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_baddate_user@example.com", "propose_baddate_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [invalid_label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "存在しない日付が含まれています。日付を確認してください。"


async def test_propose_accepts_leap_day_february_29(
    client: AsyncClient, db_session: AsyncSession
):
    """「2月29日」は実在日付として提示できる（201）。

    実在チェック（transactions.propose_schedule）は年を持たない候補ラベルの
    (月, 日) を date(2000, 月, 日) で検証しており、2000年はうるう年のため
    2月29日を弾かない。基準年をうるう年でない年に変えるとこの回帰が起きる
    （日程検証レビュー QA-R-L1）。
    """
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_feb29_user@example.com", "propose_feb29_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["2月29日（木）10:00〜12:00"]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text


async def test_propose_rejects_huge_month_number_without_500(
    client: AsyncClient, db_session: AsyncSession
):
    """月の数字が巨大な候補は 500 にならず、実在しない日付と同じ422・detailで弾かれる。

    date(2000, 月, 日) は月が C long に収まらないほど巨大だと ValueError ではなく
    OverflowError を送出する。propose_schedule がこれを捕捉し損ねると生の
    OverflowError が伝播して500になる（日程検証レビュー QA-R-I1）。
    """
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "propose_hugemonth_user@example.com", "propose_hugemonth_op@example.com"
    )
    label = "9" * 25 + "月1日"
    assert len(label) <= 32
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "存在しない日付が含まれています。日付を確認してください。"


# ──────────────── confirm: 月日間の空白・電信記号合字の日付照合 ────────────────


async def test_confirm_accepts_offered_slot_with_whitespace_between_month_and_day(
    client: AsyncClient, db_session: AsyncSession
):
    """「10月 1日」のような月日間の空白を許容し、visit_date と一致すれば確定できる。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "spacer_match_user@example.com", "spacer_match_op@example.com"
    )
    d = _future_date(8)
    label = _spaced_dated_slot_label(d)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": d.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text


async def test_confirm_rejects_offered_slot_with_whitespace_when_visit_date_mismatches(
    client: AsyncClient, db_session: AsyncSession
):
    """月日間に空白を含む候補でも、visit_date が違えば422になる。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "spacer_mismatch_user@example.com", "spacer_mismatch_op@example.com"
    )
    d = _future_date(9)
    label = _spaced_dated_slot_label(d)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    wrong_date = d + timedelta(days=3)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": wrong_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "候補日の日付と訪問日が一致しません。候補日をもう一度選び直してください。"


async def test_confirm_accepts_offered_ligature_slot_matching_visit_date(
    client: AsyncClient, db_session: AsyncSession
):
    """電信記号合字（例 ㋈㏠＝9月1日）の候補も NFKC 正規化後に日付一致すれば確定できる（日程検証レビュー QA-L7）。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "ligature_match_user@example.com", "ligature_match_op@example.com"
    )
    d = _future_date(14)
    label = _ligature_dated_slot_label(d)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": d.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text


async def test_confirm_rejects_offered_ligature_slot_when_visit_date_mismatches(
    client: AsyncClient, db_session: AsyncSession
):
    """電信記号合字の候補でも、visit_date が違えば422になる（日程検証レビュー QA-L7）。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "ligature_mismatch_user@example.com", "ligature_mismatch_op@example.com"
    )
    d = _future_date(15)
    label = _ligature_dated_slot_label(d)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text

    wrong_date = d + timedelta(days=2)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": wrong_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "候補日の日付と訪問日が一致しません。候補日をもう一度選び直してください。"


# ──────────────── 純関数テスト: _slot_month_days / _assert_slot_date_matches ────────────────


def test_slot_month_days_ascii_digits():
    assert _slot_month_days("9月7日（日）10:00〜12:00") == {(9, 7)}


def test_slot_month_days_fullwidth_digits():
    assert _slot_month_days("１０月１日") == {(10, 1)}


def test_slot_month_days_ligature():
    """電信記号合字は NFKC 正規化で「9月」「1日」に分解されて拾える（日程検証レビュー QA-L7）。"""
    label = _ligature_month(9) + _ligature_day(1)
    assert _slot_month_days(label) == {(9, 1)}


def test_slot_month_days_whitespace_between_digits_and_kanji():
    assert _slot_month_days("10月 1日") == {(10, 1)}


def test_slot_month_days_thai_digits_yield_empty_set():
    """タイ数字は ASCII の [0-9] に一致せず、NFKC でも ASCII化されないため拾わない
    （日程検証レビュー SEC-I1/SEC-I4）。"""
    label = f"{_THAI_DIGIT_NINE}月{_THAI_DIGIT_ONE}日"
    assert _slot_month_days(label) == set()


def test_slot_month_days_multiple_dates():
    assert _slot_month_days("10月1日 10月2日") == {(10, 1), (10, 2)}


def test_assert_slot_date_matches_allows_year_crossing_when_month_day_match():
    """候補ラベルに年は含まれないため、年をまたいでも月日が一致すれば通る（日程検証レビュー QA-L8）。"""
    _assert_slot_date_matches("1月5日（火）10:00〜12:00", date(2027, 1, 5))


def test_assert_slot_date_matches_rejects_when_day_differs():
    with pytest.raises(HTTPException) as exc_info:
        _assert_slot_date_matches("1月5日（火）10:00〜12:00", date(2027, 1, 6))
    assert exc_info.value.status_code == 422


# ──────────────── 年入りの候補ラベル（日付＋時間帯の選択式・ボタン化 8dfda41 との統合） ────────────────


def _year_dated_slot_label(d: date, time_value: str = _ANY_FIXED_SLOT) -> str:
    """業者の候補日提示フォーム（web/src/lib/visit-slots.ts の formatSlotLabel）と同じ形の
    年入りラベルを組み立てる（例「2026年10月1日（木）時間指定なし」）。"""
    dow = "月火水木金土日"[d.weekday()]
    return f"{d.year}年{d.month}月{d.day}日（{dow}）{time_value}"


def _future_date_not_feb29(days: int = 10) -> date:
    """翌年の同じ月日が必ず実在する未来日（2月29日なら1日ずらす）。"""
    d = _future_date(days)
    return d + timedelta(days=1) if (d.month, d.day) == (2, 29) else d


def test_slot_dates_with_and_without_year():
    assert _slot_dates("2026年10月1日（木）9:00") == {(2026, 10, 1)}
    assert _slot_dates("10月1日（木）9:00") == {(None, 10, 1)}
    # 全角の年・空白入りも NFKC 正規化と空白の許容で拾う（web の parseSlotDate と同じ形）。
    assert _slot_dates("２０２６年 １０月１日") == {(2026, 10, 1)}


def test_slot_years_and_month_days_of_year_dated_label():
    label = "2026年10月1日（木）時間指定なし"
    assert _slot_years(label) == {2026}
    assert _slot_month_days(label) == {(10, 1)}
    assert _slot_years("10月1日（木）時間指定なし") == set()


def test_assert_slot_date_matches_accepts_year_dated_label_matching_visit_date():
    _assert_slot_date_matches("2026年10月1日（木）時間指定なし", date(2026, 10, 1))


def test_assert_slot_date_matches_rejects_year_dated_label_when_year_differs():
    """年入りラベルは年も照合する。月日だけ一致させて翌年の visit_date で確定すると、
    業者に見える日付（2026年）と通知・リマインドの基準日（2027年）がずれるため422。"""
    with pytest.raises(HTTPException) as exc_info:
        _assert_slot_date_matches("2026年10月1日（木）時間指定なし", date(2027, 10, 1))
    assert exc_info.value.status_code == 422


async def test_confirm_year_dated_offered_slot_matching_visit_date(
    client: AsyncClient, db_session: AsyncSession
):
    """業者の選択式フォームと同じ形の年入り候補は、年まで一致する visit_date で確定できる。"""
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "year_slot_ok_user@example.com", "year_slot_ok_op@example.com"
    )
    visit_date = _future_date_not_feb29()
    label = _year_dated_slot_label(visit_date)
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": visit_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 200, r.text


async def test_confirm_rejects_year_dated_offered_slot_when_year_differs(
    client: AsyncClient, db_session: AsyncSession
):
    """年入り候補を、月日だけ合わせて年の違う visit_date で確定しようとすると422（API を直接呼ぶ細工）。

    visit_date は確定 API の上限（本日から365日）に収まる日にし、候補ラベルの側を翌年にする
    （visit_date を翌年にすると上限の検証で先に弾かれ、年の照合を確かめられないため）。
    """
    user_token, op_token, txn_id = await _setup_txn(
        client, db_session, "year_slot_ng_user@example.com", "year_slot_ng_op@example.com"
    )
    visit_date = _future_date_not_feb29()
    label = _year_dated_slot_label(visit_date.replace(year=visit_date.year + 1))
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/confirm",
        json={"visit_date": visit_date.isoformat(), "visit_time_slot": label},
        headers=_auth(user_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "候補日の日付と訪問日が一致しません。候補日をもう一度選び直してください。"


async def test_propose_rejects_slot_with_two_different_years(
    client: AsyncClient, db_session: AsyncSession
):
    """月日が同じでも明記された年が2種類ある候補は、確定時の年の照合が必ず不一致になるため422。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "two_years_user@example.com", "two_years_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": ["2026年10月1日〜2027年10月1日"]},
        headers=_auth(op_token),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "1つの候補日に複数の日付は入れられません。候補を分けて入力してください。"


@pytest.mark.parametrize(
    ("label", "expected_status"),
    [
        ("2027年2月29日（月）時間指定なし", 422),  # 2027年は平年
        ("2028年2月29日（火）時間指定なし", 201),  # 2028年はうるう年
    ],
    ids=["non_leap_year_feb29", "leap_year_feb29"],
)
async def test_propose_checks_feb29_against_the_stated_year(
    client: AsyncClient, db_session: AsyncSession, label: str, expected_status: int
):
    """年が明記された候補はその年の暦で実在を確かめる（年なしは従来どおり2000年基準）。"""
    _, op_token, txn_id = await _setup_txn(
        client, db_session, "feb29_year_user@example.com", "feb29_year_op@example.com"
    )
    r = await client.post(
        f"/api/v1/transactions/{txn_id}/schedule/propose",
        json={"slots": [label]},
        headers=_auth(op_token),
    )
    assert r.status_code == expected_status, r.text


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
    からの確定が _assert_offered_time_slot（transactions.py）で422になる
    （2026-09-25 セキュリティレビュー Low 対応）。
    """
    assert SCHEDULE_FIXED_TIME_SLOTS == _read_frontend_time_slot_values()
