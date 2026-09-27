"""訪問日程（日程候補の提示・確定）の時刻・ラベル・期限の規則（日程構造化 DESIGN §13.1）。

DB にも Web フレームワークにも依存しない純関数と定数だけを置く（標準ライブラリだけを
import する）。schemas_katadzuke（入力の検証）と transactions（propose / accept /
confirm）の両方から使うため、DB に触れるモジュール（app.services.reminders 等）を
import すると循環 import の入口になる。

web/src/lib/visit-slots.ts と1文字違わず一致させる規則（正解データは
web/src/lib/visit-slots.golden.json。tests/test_visit_schedule_unit.py が golden と
web の VISIT_TIME_SLOTS を読んで照合する）:
- 時刻は「両方 None（時間指定なし）」か「両方 "HH:MM"（ゼロ詰め・分は 00 か 30）」。
- 6:00 ≤ 開始 < 終了 ≤ 22:00、終了 − 開始 ≥ 60 分。固定4枠もこの規則を満たすため、
  固定の枠と任意の時刻を区別しない。
- 時間帯の表示（time_label）は "9:00〜12:00"（時はゼロ詰めなし・波ダッシュは U+301C）か
  "時間指定なし"。日付を含む表示（format_visit_label）は "2026年10月1日（木）9:00〜12:00"
  （括弧は全角・日付と時間帯の間に空白なし）。
- 期限切れ（日本時間）: 日付が今日より前、または今日で終了時刻を過ぎた（現在時刻 ≥ 終了）。
  時間指定なしの当日は期限切れにしない。

表示は保存と画面のためだけに作り、解析しない（日程検証レビュー SEC-I1 / QA-L5 の解消）。
確定の値（visit_date・visit_time_slot・確定メッセージの本文）は、必ず構造化データ
（日付・開始・終了）から作り直す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

#: 日本時間（app.services.reminders.JST と同じ定義）。本モジュールは標準ライブラリだけに
#: 依存させるため reminders を import しない（両者の一致は tests/test_visit_schedule_unit.py
#: で確かめる）。
JST = timezone(timedelta(hours=9), name="Asia/Tokyo")

#: 1回の提示に含められる候補の上限（ScheduleProposeRequest.candidates の件数と
#: ScheduleAcceptRequest.candidate_index の上限の単一の出所）。
MAX_SCHEDULE_CANDIDATES = 10

#: 訪問日として選べる範囲（日本時間の今日から何日後まで）。propose と confirm で共通。
MAX_VISIT_DAYS_AHEAD = 365

#: 時間指定なしの時間帯の表示（固定5種の1つ）。
NO_TIME_PREFERENCE = "時間指定なし"

#: 固定4枠の開始・終了（"HH:MM"）。
VISIT_TIME_WINDOWS: tuple[tuple[str, str], ...] = (
    ("09:00", "12:00"),
    ("12:00", "15:00"),
    ("15:00", "18:00"),
    ("18:00", "21:00"),
)

#: 固定5種（/schedule の確定で受け付ける visit_time_slot の値）。web の VISIT_TIME_SLOTS の
#: value と1文字違わず一致させる（波ダッシュは U+301C。並びは VISIT_TIME_WINDOWS と同じで、
#: 末尾が時間指定なし）。
FIXED_VISIT_TIME_SLOTS: tuple[str, ...] = (
    "9:00〜12:00",
    "12:00〜15:00",
    "15:00〜18:00",
    "18:00〜21:00",
    NO_TIME_PREFERENCE,
)

#: 固定5種の値 → 開始・終了（時間指定なしは両方 None）。件数がずれたら import 時に失敗させる。
_FIXED_VISIT_TIME_SLOT_WINDOWS: dict[str, tuple[str | None, str | None]] = dict(
    zip(FIXED_VISIT_TIME_SLOTS, (*VISIT_TIME_WINDOWS, (None, None)), strict=True)
)

#: 時刻を指定できる範囲（0:00 からの分）と、開始から終了までの最短の長さ（分）。
EARLIEST_VISIT_MINUTES = 6 * 60
LATEST_VISIT_MINUTES = 22 * 60
MIN_VISIT_WINDOW_MINUTES = 60

#: "HH:MM"（ゼロ詰め・分は 00 か 30）。\d は全角数字等にも一致するため [0-9] で書き、
#: 末尾の改行を通さないよう fullmatch で照合する。
_HHMM_PATTERN = re.compile(r"([01][0-9]|2[0-3]):(00|30)")

#: "YYYY-MM-DD"。date.fromisoformat は Python 3.11 以降 "20261001" や週番号の形式も
#: 受け付けるため、先に形を固定する。
_ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

#: 波ダッシュ（U+301C）。全角チルダ（U+FF5E）と取り違えないよう符号位置で持つ。
_WAVE_DASH = chr(0x301C)

#: date.weekday()（月曜=0）の順の曜日。
_WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")

ProposalMetaVersion = Literal["v2", "v1", "unknown"]


@dataclass(frozen=True, slots=True)
class VisitCandidate:
    """訪問日程の候補1件（日付・開始・終了）。

    生成する側（ScheduleCandidateIn の検証・parse_proposal_meta・固定5種の変換）が
    時刻の規則を満たすことを保証する。表示は candidate_label で都度作る。
    """

    date: date
    start: str | None
    end: str | None


@dataclass(frozen=True, slots=True)
class ParsedProposalMeta:
    """保存済みの提示（kind="schedule_proposal" の meta）の読み取り結果。

    version が "v2" のときだけ seq と candidates に値が入る。
    """

    version: ProposalMetaVersion
    seq: int | None = None
    candidates: tuple[VisitCandidate, ...] = ()


def hhmm_to_minutes(value: Any) -> int:
    """"HH:MM"（ゼロ詰め・分は 00 か 30）を 0:00 からの分にする。形式に合わなければ ValueError。"""
    match = _HHMM_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("時刻は「09:00」の形式（分は00か30）で指定してください。")
    return int(match.group(1)) * 60 + int(match.group(2))


def validate_time_window(start: Any, end: Any) -> None:
    """開始・終了が時刻の規則（日程構造化 DESIGN §13.1）を満たすか検査する。違反は ValueError。

    入力の検証（ScheduleCandidateIn）と保存済みの提示の読み取り（parse_proposal_meta）の
    単一の出所。
    """
    if start is None and end is None:
        return
    if start is None or end is None:
        raise ValueError("開始時刻と終了時刻は、両方を指定するか両方を空にしてください。")
    start_minutes = hhmm_to_minutes(start)
    end_minutes = hhmm_to_minutes(end)
    if start_minutes < EARLIEST_VISIT_MINUTES or end_minutes > LATEST_VISIT_MINUTES:
        raise ValueError("時刻は6:00〜22:00の範囲で指定してください。")
    if end_minutes - start_minutes < MIN_VISIT_WINDOW_MINUTES:
        raise ValueError("終了時刻は開始時刻の1時間後以降にしてください。")


def parse_iso_date(value: Any) -> date:
    """"YYYY-MM-DD" の文字列だけを date にする（それ以外・実在しない日付は ValueError）。

    入力の検証（ScheduleCandidateIn.date）と保存済みの提示の読み取りの単一の出所。
    """
    if not isinstance(value, str) or _ISO_DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("日付は「2026-10-01」の形式で指定してください。")
    return date.fromisoformat(value)


def _format_hhmm(value: str) -> str:
    """"09:00" → "9:00"（時はゼロ詰めなし・分は2桁）。"""
    minutes = hhmm_to_minutes(value)
    return f"{minutes // 60}:{minutes % 60:02d}"


def time_label(start: str | None, end: str | None) -> str:
    """時間帯の表示（例 "9:00〜12:00"・"時間指定なし"）。規則に合わない組は ValueError。

    固定4枠の表示は FIXED_VISIT_TIME_SLOTS と1文字違わず一致する
    （transactions.visit_time_slot にそのまま保存する値）。
    """
    validate_time_window(start, end)
    if start is None or end is None:
        return NO_TIME_PREFERENCE
    return f"{_format_hhmm(start)}{_WAVE_DASH}{_format_hhmm(end)}"


def format_visit_label(visit_date: date, time_label_text: str) -> str:
    """日付を含む表示（例 "2026年10月1日（木）9:00〜12:00"）。

    括弧は全角（U+FF08 / U+FF09）、日付と時間帯の間に空白を入れない。年は常に入れる
    （年をまたぐ候補で日付を取り違えないため。日程検証レビュー SEC-I2）。
    """
    weekday = _WEEKDAY_LABELS[visit_date.weekday()]
    return (
        f"{visit_date.year}年{visit_date.month}月{visit_date.day}日（{weekday}）{time_label_text}"
    )


def candidate_label(candidate: VisitCandidate) -> str:
    """候補1件の表示（format_visit_label と time_label の合成）。"""
    return format_visit_label(candidate.date, time_label(candidate.start, candidate.end))


def fixed_visit_time_slot_candidate(visit_date: date, value: str) -> VisitCandidate | None:
    """固定5種の値を候補に直す（固定5種でなければ None）。/schedule からの確定で使う。"""
    window = _FIXED_VISIT_TIME_SLOT_WINDOWS.get(value)
    if window is None:
        return None
    return VisitCandidate(date=visit_date, start=window[0], end=window[1])


def now_jst(now_utc: datetime | None = None) -> datetime:
    """日本時間の現在時刻（aware）。

    now_utc を渡すとその時刻を日本時間に直す（テストから固定時刻を注入するため）。
    tz なしの now_utc は UTC とみなす（SQLite が返す tz なしの値と同じ規約）。
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(JST)


def today_jst(now_utc: datetime | None = None) -> date:
    """日本時間での「今日」の日付。訪問日（visit_date）は日本の暦で判定する
    （reminders.py の訪問日超過リマインドと同じ理由・同じ JST 定義）。
    """
    return now_jst(now_utc).date()


def latest_visit_date(today: date) -> date:
    """訪問日として選べる最後の日（today + MAX_VISIT_DAYS_AHEAD 日）。"""
    return today + timedelta(days=MAX_VISIT_DAYS_AHEAD)


def is_candidate_expired(candidate: VisitCandidate, now: datetime) -> bool:
    """候補が過ぎているか（日本時間。日程構造化 DESIGN §13.1）。

    日付が今日より前なら期限切れ。今日で終了時刻があり、現在時刻 ≥ 終了なら期限切れ。
    時間指定なし（end が None）の当日は期限切れにしない。now は aware な datetime
    （now_jst() の戻り値）を渡す。終了時刻は分単位のため、現在時刻の秒以下を切り捨てて
    比べても「現在時刻 ≥ 終了」と同値になる。
    """
    local_now = now.astimezone(JST)
    today = local_now.date()
    if candidate.date < today:
        return True
    if candidate.date > today or candidate.end is None:
        return False
    return local_now.hour * 60 + local_now.minute >= hhmm_to_minutes(candidate.end)


def _parse_stored_candidate(raw: Any) -> VisitCandidate | None:
    """保存済みの v2 の候補1件を読む（規則に合わなければ None）。"""
    if not isinstance(raw, dict) or "start" not in raw or "end" not in raw:
        return None
    if not isinstance(raw.get("label"), str):
        return None
    start, end = raw["start"], raw["end"]
    try:
        visit_date = parse_iso_date(raw.get("date"))
        validate_time_window(start, end)
    except ValueError:
        return None
    return VisitCandidate(date=visit_date, start=start, end=end)


def parse_proposal_meta(meta: Any) -> ParsedProposalMeta:
    """schedule_proposal の meta を版ごとに読み分ける（日程構造化 DESIGN §3・§4）。

    - "v2": {"v": 2, "seq": 1以上の整数, "candidates": [{"date", "start", "end", "label"}]}
      （1〜MAX_SCHEDULE_CANDIDATES 件。各候補が時刻の規則を満たし、label が文字列）。
    - "v1": 旧形式 {"slots": [...]}（業者の自由記述。解析せず、確定にも使わない）。
    - "unknown": それ以外（将来の版・壊れた値）。規則に合わない候補を1件でも含む v2 も
      unknown に落とす（一部の候補だけ確定できる状態を作らない）。

    DB の JSON 列の値をそのまま渡してよい（型を信用せず、ここで検査する）。
    """
    if not isinstance(meta, dict):
        return ParsedProposalMeta(version="unknown")
    if "v" not in meta:
        if isinstance(meta.get("slots"), list):
            return ParsedProposalMeta(version="v1")
        return ParsedProposalMeta(version="unknown")
    version, seq, raw_candidates = meta.get("v"), meta.get("seq"), meta.get("candidates")
    # bool は int の派生型のため type() で比べる（True を版 1・seq 1 として通さない）。
    if type(version) is not int or version != 2 or type(seq) is not int or seq < 1:
        return ParsedProposalMeta(version="unknown")
    if not isinstance(raw_candidates, list) or not (
        1 <= len(raw_candidates) <= MAX_SCHEDULE_CANDIDATES
    ):
        return ParsedProposalMeta(version="unknown")
    candidates: list[VisitCandidate] = []
    for raw in raw_candidates:
        candidate = _parse_stored_candidate(raw)
        if candidate is None:
            return ParsedProposalMeta(version="unknown")
        candidates.append(candidate)
    return ParsedProposalMeta(version="v2", seq=seq, candidates=tuple(candidates))
