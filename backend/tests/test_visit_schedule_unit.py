"""services/visit_schedule（日程構造化 DESIGN §13.1）の単体テスト。

- 時刻の規則・time_label・format_visit_label（曜日・うるう日・年末年始・全角括弧・波ダッシュ）
- 日本時間の now / today（UTC 14:59 / 15:00 の境界）・期限切れの判定・日付範囲の上限
- parse_proposal_meta の v2 / v1 / unknown の読み分け
- 固定時間帯と web/src/lib/visit-slots.ts の VISIT_TIME_SLOTS の一致（DESIGN §13.2 の書式を
  正規表現で読む。波ダッシュ U+301C と全角チルダ U+FF5E のずれも検出する）
- 表示の正解データ web/src/lib/visit-slots.golden.json との照合（web のテストも同じ golden を読む）

不可視文字・全角文字の取り違えを避けるため、制御文字・紛らわしい記号はソースに生で
書かず chr() で組み立てる。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.reminders import JST as REMINDERS_JST
from app.services.visit_schedule import (
    FIXED_VISIT_TIME_SLOTS,
    JST,
    MAX_SCHEDULE_CANDIDATES,
    NO_TIME_PREFERENCE,
    VISIT_TIME_WINDOWS,
    VisitCandidate,
    candidate_label,
    fixed_visit_time_slot_candidate,
    format_visit_label,
    hhmm_to_minutes,
    is_candidate_expired,
    latest_visit_date,
    now_jst,
    parse_iso_date,
    parse_proposal_meta,
    time_label,
    today_jst,
    validate_time_window,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_VISIT_SLOTS = _REPO_ROOT / "web" / "src" / "lib" / "visit-slots.ts"
_GOLDEN = _REPO_ROOT / "web" / "src" / "lib" / "visit-slots.golden.json"

_WAVE_DASH = chr(0x301C)  # 波ダッシュ（正しい記号）
_FULLWIDTH_TILDE = chr(0xFF5E)  # 全角チルダ（取り違えやすい記号）
_FULLWIDTH_LEFT_PAREN = chr(0xFF08)
_FULLWIDTH_RIGHT_PAREN = chr(0xFF09)
_FULLWIDTH_ZERO = chr(0xFF10)
_NEWLINE = chr(10)
_UTC = timezone.utc


def _jst(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=JST)


# ──────────────── 時刻の規則 ────────────────


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (None, None),
        ("09:00", "12:00"),
        ("18:00", "21:00"),
        ("06:00", "07:00"),
        ("21:00", "22:00"),
        ("06:00", "22:00"),
        ("10:30", "12:00"),
        ("12:30", "13:30"),
    ],
)
def test_validate_time_window_accepts(start: str | None, end: str | None):
    validate_time_window(start, end)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("09:00", None),
        (None, "12:00"),
        ("9:00", "12:00"),
        ("09:15", "12:00"),
        ("09:00", "12:45"),
        ("05:30", "07:00"),
        ("21:30", "22:30"),
        ("10:00", "10:30"),
        ("10:00", "10:00"),
        ("12:00", "09:00"),
        ("24:00", "25:00"),
        ("09:00:00", "12:00"),
        (_FULLWIDTH_ZERO + "9:00", "12:00"),
        ("09:00" + _NEWLINE, "12:00"),
        (900, 1200),
        ("", ""),
    ],
    ids=[
        "end_missing", "start_missing", "no_zero_pad", "quarter_start", "quarter_end",
        "before_6", "after_22", "shorter_than_1h", "zero_length", "reversed",
        "out_of_day", "with_seconds", "fullwidth_digit", "trailing_newline", "not_string",
        "empty",
    ],
)
def test_validate_time_window_rejects(start: object, end: object):
    with pytest.raises(ValueError):
        validate_time_window(start, end)


def test_hhmm_to_minutes():
    assert hhmm_to_minutes("06:00") == 360
    assert hhmm_to_minutes("21:30") == 1290


@pytest.mark.parametrize(
    "value",
    ["2026/10/01", "20261001", "2026-W40-4", "2026-10-01T00:00:00", "2026-02-30", 1790000000, None],
)
def test_parse_iso_date_rejects_non_iso_or_invalid(value: object):
    with pytest.raises(ValueError):
        parse_iso_date(value)


def test_parse_iso_date_accepts_leap_day():
    assert parse_iso_date("2028-02-29") == date(2028, 2, 29)


# ──────────────── 表示（time_label / format_visit_label） ────────────────


def test_time_label_of_fixed_windows_equals_fixed_values():
    """固定4枠＋時間指定なしの表示は固定5種と1文字違わず一致する（visit_time_slot に保存する値）。"""
    labels = tuple(time_label(start, end) for start, end in VISIT_TIME_WINDOWS)
    assert labels + (time_label(None, None),) == FIXED_VISIT_TIME_SLOTS
    assert FIXED_VISIT_TIME_SLOTS[-1] == NO_TIME_PREFERENCE == "時間指定なし"


def test_time_label_uses_wave_dash_not_fullwidth_tilde():
    assert time_label("09:00", "12:00") == "9:00" + _WAVE_DASH + "12:00"
    assert time_label("10:30", "12:00") == "10:30" + _WAVE_DASH + "12:00"
    assert time_label("06:00", "07:00") == "6:00" + _WAVE_DASH + "7:00"
    for value in FIXED_VISIT_TIME_SLOTS:
        assert _FULLWIDTH_TILDE not in value


def test_time_label_rejects_invalid_window():
    with pytest.raises(ValueError):
        time_label("09:15", "12:00")


@pytest.mark.parametrize(
    ("visit_date", "expected_prefix"),
    [
        (date(2026, 10, 1), "2026年10月1日（木）"),
        (date(2026, 10, 2), "2026年10月2日（金）"),
        (date(2026, 10, 3), "2026年10月3日（土）"),
        (date(2026, 10, 4), "2026年10月4日（日）"),
        (date(2026, 10, 5), "2026年10月5日（月）"),
        (date(2026, 10, 6), "2026年10月6日（火）"),
        (date(2026, 10, 7), "2026年10月7日（水）"),
        (date(2028, 2, 29), "2028年2月29日（火）"),
        (date(2026, 12, 31), "2026年12月31日（木）"),
        (date(2027, 1, 1), "2027年1月1日（金）"),
    ],
)
def test_format_visit_label_weekday_leap_day_and_new_year(visit_date: date, expected_prefix: str):
    assert format_visit_label(visit_date, NO_TIME_PREFERENCE) == expected_prefix + NO_TIME_PREFERENCE


def test_format_visit_label_uses_fullwidth_parens_without_space():
    label = format_visit_label(date(2026, 10, 1), time_label("09:00", "12:00"))
    assert label == (
        "2026年10月1日" + _FULLWIDTH_LEFT_PAREN + "木" + _FULLWIDTH_RIGHT_PAREN
        + "9:00" + _WAVE_DASH + "12:00"
    )
    assert " " not in label


def test_golden_fixture_matches_server_labels():
    """web/src/lib/visit-slots.golden.json（web のテストも読む正解データ）と1文字違わず一致する。"""
    rows = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert rows, "golden が空です"
    for row in rows:
        candidate = VisitCandidate(
            date=parse_iso_date(row["date"]), start=row["start"], end=row["end"]
        )
        assert time_label(row["start"], row["end"]) == row["time_label"], row
        assert format_visit_label(candidate.date, row["time_label"]) == row["label"], row
        assert candidate_label(candidate) == row["label"], row


def test_fixed_visit_time_slot_candidate():
    visit_date = date(2026, 10, 1)
    assert fixed_visit_time_slot_candidate(visit_date, FIXED_VISIT_TIME_SLOTS[0]) == VisitCandidate(
        date=visit_date, start="09:00", end="12:00"
    )
    assert fixed_visit_time_slot_candidate(visit_date, NO_TIME_PREFERENCE) == VisitCandidate(
        date=visit_date, start=None, end=None
    )
    for value in ("午前", "10:00-12:00", "9:00" + _FULLWIDTH_TILDE + "12:00", "10:30" + _WAVE_DASH + "12:00"):
        assert fixed_visit_time_slot_candidate(visit_date, value) is None, value


# ──────────────── 日本時間（now / today）・範囲・期限 ────────────────


def test_jst_matches_reminders_jst():
    """reminders.JST と同じ定義（本モジュールは循環 import を避けるため reminders を import しない）。"""
    moment = datetime(2026, 9, 26, 12, 0, tzinfo=_UTC)
    assert JST.utcoffset(moment) == REMINDERS_JST.utcoffset(moment) == timedelta(hours=9)


def test_today_jst_rolls_over_at_utc_15():
    assert today_jst(datetime(2026, 9, 26, 14, 59, 59, tzinfo=_UTC)) == date(2026, 9, 26)
    assert today_jst(datetime(2026, 9, 26, 15, 0, 0, tzinfo=_UTC)) == date(2026, 9, 27)


def test_today_jst_new_year_boundary():
    assert today_jst(datetime(2026, 12, 31, 14, 59, 59, tzinfo=_UTC)) == date(2026, 12, 31)
    assert today_jst(datetime(2026, 12, 31, 15, 0, 0, tzinfo=_UTC)) == date(2027, 1, 1)


def test_now_jst_converts_and_treats_naive_as_utc():
    assert now_jst(datetime(2026, 9, 26, 15, 0, tzinfo=_UTC)) == _jst(2026, 9, 27, 0, 0)
    assert now_jst(datetime(2026, 9, 26, 15, 0)) == _jst(2026, 9, 27, 0, 0)
    assert now_jst().utcoffset() == timedelta(hours=9)


def test_latest_visit_date_is_365_days_ahead():
    assert latest_visit_date(date(2026, 10, 1)) == date(2027, 10, 1)
    # うるう日をまたぐと暦の「1年後」の前日になる（365日の固定幅）。
    assert latest_visit_date(date(2027, 3, 1)) == date(2028, 2, 29)


@pytest.mark.parametrize(
    ("candidate", "now", "expected"),
    [
        (VisitCandidate(date(2026, 9, 30), None, None), _jst(2026, 10, 1, 0, 0), True),
        (VisitCandidate(date(2026, 9, 30), "18:00", "21:00"), _jst(2026, 10, 1, 0, 0), True),
        (VisitCandidate(date(2026, 10, 1), None, None), _jst(2026, 10, 1, 23, 59, 59), False),
        (VisitCandidate(date(2026, 10, 1), "09:00", "12:00"), _jst(2026, 10, 1, 10, 0), False),
        (VisitCandidate(date(2026, 10, 1), "09:00", "12:00"), _jst(2026, 10, 1, 11, 59, 59), False),
        (VisitCandidate(date(2026, 10, 1), "09:00", "12:00"), _jst(2026, 10, 1, 12, 0), True),
        (VisitCandidate(date(2026, 10, 1), "10:30", "12:00"), _jst(2026, 10, 1, 12, 30), True),
        (VisitCandidate(date(2026, 10, 2), "06:00", "07:00"), _jst(2026, 10, 1, 23, 59), False),
    ],
    ids=[
        "yesterday_any_time", "yesterday_window", "today_no_time_late_night",
        "today_window_ongoing", "today_window_last_second", "today_window_end_exact",
        "today_custom_window_after_end", "tomorrow",
    ],
)
def test_is_candidate_expired(candidate: VisitCandidate, now: datetime, expected: bool):
    assert is_candidate_expired(candidate, now) is expected


def test_is_candidate_expired_uses_jst_for_utc_now():
    """UTC の 14:59 は日本時間の 23:59、15:00 は翌日 0:00 として判定する。"""
    candidate_no_time = VisitCandidate(date(2026, 9, 30), None, None)
    candidate_evening = VisitCandidate(date(2026, 9, 30), "18:00", "21:00")
    before_midnight = datetime(2026, 9, 30, 14, 59, tzinfo=_UTC)
    after_midnight = datetime(2026, 9, 30, 15, 0, tzinfo=_UTC)
    assert is_candidate_expired(candidate_no_time, before_midnight) is False
    assert is_candidate_expired(candidate_evening, before_midnight) is True
    assert is_candidate_expired(candidate_no_time, after_midnight) is True


# ──────────────── parse_proposal_meta（v2 / v1 / unknown） ────────────────


def _stored_candidate(visit_date: date, start: str | None, end: str | None) -> dict:
    candidate = VisitCandidate(date=visit_date, start=start, end=end)
    return {
        "date": visit_date.isoformat(),
        "start": start,
        "end": end,
        "label": candidate_label(candidate),
    }


def _v2_meta(**overrides: object) -> dict:
    meta: dict = {
        "v": 2,
        "seq": 3,
        "candidates": [
            _stored_candidate(date(2026, 10, 1), "09:00", "12:00"),
            _stored_candidate(date(2026, 10, 3), None, None),
        ],
    }
    meta.update(overrides)
    return meta


def test_parse_proposal_meta_v2():
    parsed = parse_proposal_meta(_v2_meta())
    assert parsed.version == "v2"
    assert parsed.seq == 3
    assert parsed.candidates == (
        VisitCandidate(date(2026, 10, 1), "09:00", "12:00"),
        VisitCandidate(date(2026, 10, 3), None, None),
    )


def test_parse_proposal_meta_v1_slots_only():
    parsed = parse_proposal_meta({"slots": ["9月7日（日）10:00" + _WAVE_DASH + "12:00"]})
    assert parsed.version == "v1"
    assert parsed.seq is None
    assert parsed.candidates == ()


def _unknown_meta_cases() -> list[tuple[str, object]]:
    good = _stored_candidate(date(2026, 10, 1), "09:00", "12:00")
    return [
        ("none", None),
        ("string", "slots"),
        ("list", [good]),
        ("empty_dict", {}),
        ("slots_not_list", {"slots": "9月7日"}),
        ("v3", _v2_meta(v=3)),
        ("v_string", _v2_meta(v="2")),
        ("v_null", _v2_meta(v=None)),
        ("seq_missing", {"v": 2, "candidates": [good]}),
        ("seq_zero", _v2_meta(seq=0)),
        ("seq_string", _v2_meta(seq="3")),
        ("seq_bool", _v2_meta(seq=True)),
        ("candidates_empty", _v2_meta(candidates=[])),
        ("candidates_too_many", _v2_meta(candidates=[good] * (MAX_SCHEDULE_CANDIDATES + 1))),
        ("candidates_not_list", _v2_meta(candidates=good)),
        ("label_missing", _v2_meta(candidates=[{k: v for k, v in good.items() if k != "label"}])),
        ("label_not_string", _v2_meta(candidates=[{**good, "label": 1}])),
        ("start_key_missing", _v2_meta(candidates=[{k: v for k, v in good.items() if k != "start"}])),
        ("invalid_date", _v2_meta(candidates=[{**good, "date": "2026-02-30"}])),
        ("compact_date", _v2_meta(candidates=[{**good, "date": "20261001"}])),
        ("invalid_time", _v2_meta(candidates=[{**good, "start": "09:15"}])),
        ("one_bad_among_good", _v2_meta(candidates=[good, {**good, "end": None}])),
    ]


@pytest.mark.parametrize(
    "meta", [case for _, case in _unknown_meta_cases()], ids=[name for name, _ in _unknown_meta_cases()]
)
def test_parse_proposal_meta_unknown(meta: object):
    parsed = parse_proposal_meta(meta)
    assert parsed.version == "unknown"
    assert parsed.seq is None
    assert parsed.candidates == ()


# ──────────────── 定数ガード: 固定時間帯と web の VISIT_TIME_SLOTS の一致 ────────────────

#: web/src/lib/visit-slots.ts の VISIT_TIME_SLOTS 配列（日程構造化 DESIGN §13.2 の書式）。
_WEB_SLOTS_BLOCK = re.compile(r"export const VISIT_TIME_SLOTS[^=]*=\s*\[(.*?)\n\];", re.DOTALL)
_WEB_SLOT_ENTRY = re.compile(
    r'\{\s*value:\s*"([^"]*)",\s*label:\s*"([^"]*)",'
    r'\s*start:\s*(null|"[^"]*"),\s*end:\s*(null|"[^"]*"),?\s*\}'
)


def _ts_nullable(token: str) -> str | None:
    return None if token == "null" else token[1:-1]


def _read_web_visit_time_slots() -> list[tuple[str, str | None, str | None]]:
    """VISIT_TIME_SLOTS の (value, start, end) を並び順どおりに読む。"""
    text = _WEB_VISIT_SLOTS.read_text(encoding="utf-8")
    block = _WEB_SLOTS_BLOCK.search(text)
    assert block is not None, (
        "VISIT_TIME_SLOTS 配列が見つかりません（web/src/lib/visit-slots.ts の形式が"
        "日程構造化 DESIGN §13.2 から変わった可能性があります）。"
    )
    body = block.group(1)
    entries = _WEB_SLOT_ENTRY.findall(body)
    assert entries and len(entries) == body.count("value:"), (
        "VISIT_TIME_SLOTS の要素が日程構造化 DESIGN §13.2 の書式"
        '（{ value: "...", label: "...", start: "HH:MM" または null, end: ... }）で読めません。'
    )
    return [(value, _ts_nullable(start), _ts_nullable(end)) for value, _label, start, end in entries]


def test_fixed_visit_time_slots_match_web_visit_time_slots():
    """backend の固定5種（値・開始・終了・並び）が web の VISIT_TIME_SLOTS と1文字違わず一致する。

    ずれると /schedule（固定5種）からの確定が confirm_schedule の許可リストで 422 になる。
    """
    web_slots = _read_web_visit_time_slots()
    assert not any(_FULLWIDTH_TILDE in value for value, _, _ in web_slots), (
        "web の VISIT_TIME_SLOTS に全角チルダ（U+FF5E）が混ざっています。波ダッシュ（U+301C）に直してください。"
    )
    server_slots = []
    for value in FIXED_VISIT_TIME_SLOTS:
        candidate = fixed_visit_time_slot_candidate(date(2026, 10, 1), value)
        assert candidate is not None
        server_slots.append((value, candidate.start, candidate.end))
    assert web_slots == server_slots
