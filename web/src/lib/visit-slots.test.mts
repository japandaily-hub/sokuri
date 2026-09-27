/**
 * visit-slots.ts の純関数の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/visit-slots.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由・import に拡張子を付ける理由は
 * safe-path.test.mts / review-verdict.test.mts と同じ（tsconfig の include に一致させず、
 * 型検査・ビルドの対象から外したまま実行できるようにするため）。
 *
 * ラベルの正解データ visit-slots.golden.json は backend のテストとも共有する（日程構造化 DESIGN §13.1）。
 * import 属性（with { type: "json" }）に頼らず fs で読む。
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  CUSTOM_END_TIME_OPTIONS,
  CUSTOM_START_TIME_OPTIONS,
  DEFAULT_CUSTOM_END_TIME,
  DEFAULT_CUSTOM_START_TIME,
  MAX_SCHEDULE_CANDIDATES,
  VISIT_TIME_SLOTS,
  addDaysIso,
  findVisitTimeSlot,
  formatSlotLabel,
  formatVisitTime,
  isCandidateExpired,
  isValidIsoDate,
  isValidVisitTimeRange,
  isVisitTimeSlotValue,
  jstNow,
  jstTodayIso,
  latestProposalId,
  parseScheduleConfirmedMeta,
  parseScheduleProposalMeta,
  timeLabel,
  toIsoDateString,
  visitTimeToMinutes,
} from "./visit-slots.ts";

type GoldenEntry = { date: string; start: string | null; end: string | null; time_label: string; label: string };
const GOLDEN: GoldenEntry[] = JSON.parse(readFileSync(new URL("./visit-slots.golden.json", import.meta.url), "utf8"));

/** 全角チルダ（U+FF5E）。波ダッシュ（U+301C）との取り違えを検出するために使う。 */
const FULLWIDTH_TILDE = String.fromCharCode(0xff5e);
/** 波ダッシュ（U+301C）。 */
const WAVE_DASH = String.fromCharCode(0x301c);

/** process.env.TZ を一時的に差し替えて fn を実行する（Node は代入時にタイムゾーンを読み直す）。 */
function withTimeZone<T>(timeZone: string, fn: () => T): T {
  const original = process.env.TZ;
  process.env.TZ = timeZone;
  try {
    return fn();
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
}

describe("VISIT_TIME_SLOTS", () => {
  it("5件の時間帯（値・表示名・開始・終了）を持つ（日程構造化 DESIGN §13.2）", () => {
    assert.deepEqual(VISIT_TIME_SLOTS, [
      { value: "9:00〜12:00", label: "午前", start: "09:00", end: "12:00" },
      { value: "12:00〜15:00", label: "昼", start: "12:00", end: "15:00" },
      { value: "15:00〜18:00", label: "午後", start: "15:00", end: "18:00" },
      { value: "18:00〜21:00", label: "夜", start: "18:00", end: "21:00" },
      { value: "時間指定なし", label: "業者に一任", start: null, end: null },
    ]);
  });

  it("各時間帯の value は timeLabel(start, end) と1文字違わず一致し、時刻の規則を満たす", () => {
    for (const slot of VISIT_TIME_SLOTS) {
      assert.equal(isValidVisitTimeRange(slot.start, slot.end), true, slot.value);
      assert.equal(timeLabel(slot.start, slot.end), slot.value);
    }
  });

  it("時刻の範囲を表す value の波ダッシュは U+301C（U+FF5E ではない）", () => {
    for (const slot of VISIT_TIME_SLOTS.filter((s) => s.start !== null)) {
      assert.ok(slot.value.includes(WAVE_DASH), slot.value);
      assert.equal(slot.value.includes(FULLWIDTH_TILDE), false, slot.value);
    }
  });
});

describe("isVisitTimeSlotValue / findVisitTimeSlot", () => {
  it("固定5種だけを受け付ける", () => {
    for (const slot of VISIT_TIME_SLOTS) assert.equal(isVisitTimeSlotValue(slot.value), true);
    for (const value of ["10:00-12:00", `9:00${FULLWIDTH_TILDE}12:00`, "09:00〜12:00", "10:00〜12:00", "", "業者に一任"]) {
      assert.equal(isVisitTimeSlotValue(value), false, value);
    }
  });
  it("start/end が固定の時間帯に一致すればそれを返す", () => {
    assert.equal(findVisitTimeSlot("09:00", "12:00")?.value, "9:00〜12:00");
    assert.equal(findVisitTimeSlot(null, null)?.value, "時間指定なし");
    assert.equal(findVisitTimeSlot("10:00", "12:00"), undefined);
  });
});

describe("visitTimeToMinutes / formatVisitTime", () => {
  it("ゼロ詰め・分が 00 か 30 の \"HH:MM\" を分に変換する", () => {
    assert.equal(visitTimeToMinutes("00:00"), 0);
    assert.equal(visitTimeToMinutes("09:00"), 540);
    assert.equal(visitTimeToMinutes("21:30"), 1290);
    assert.equal(visitTimeToMinutes("23:30"), 1410);
  });
  it("書式違いは null（ゼロ詰めなし・15分・24時・前後の空白・全角数字）", () => {
    for (const value of ["9:00", "09:15", "24:00", "", " 09:00", "09:00 ", "0９:00", "09-00"]) {
      assert.equal(visitTimeToMinutes(value), null, value);
    }
  });
  it("表示は時のゼロ詰めを外す", () => {
    assert.equal(formatVisitTime("09:00"), "9:00");
    assert.equal(formatVisitTime("10:30"), "10:30");
    assert.equal(formatVisitTime("9:00"), "");
  });
});

describe("isValidVisitTimeRange（日程構造化 DESIGN §13.1）", () => {
  it("両方 null（時間指定なし）は有効、片方だけ null は無効", () => {
    assert.equal(isValidVisitTimeRange(null, null), true);
    assert.equal(isValidVisitTimeRange("09:00", null), false);
    assert.equal(isValidVisitTimeRange(null, "12:00"), false);
  });
  it("06:00 ≤ start < end ≤ 22:00 かつ 60分以上", () => {
    assert.equal(isValidVisitTimeRange("06:00", "07:00"), true);
    assert.equal(isValidVisitTimeRange("21:00", "22:00"), true);
    assert.equal(isValidVisitTimeRange("10:30", "12:00"), true);
    assert.equal(isValidVisitTimeRange("05:30", "07:00"), false);
    assert.equal(isValidVisitTimeRange("21:00", "22:30"), false);
    assert.equal(isValidVisitTimeRange("10:00", "10:30"), false);
    assert.equal(isValidVisitTimeRange("12:00", "10:00"), false);
    assert.equal(isValidVisitTimeRange("10:00", "10:00"), false);
    assert.equal(isValidVisitTimeRange("09:15", "12:00"), false);
  });
});

describe("timeLabel / formatSlotLabel と正解データ（visit-slots.golden.json）", () => {
  it("正解データが1件以上ある", () => {
    assert.ok(GOLDEN.length > 0);
  });
  for (const entry of GOLDEN) {
    it(`${entry.date} ${entry.start ?? "null"}-${entry.end ?? "null"} → ${entry.label}`, () => {
      assert.equal(timeLabel(entry.start, entry.end), entry.time_label);
      assert.equal(formatSlotLabel(entry.date, entry.start, entry.end), entry.label);
    });
  }
  it("ブラウザのタイムゾーンが違っても同じラベルになる（UTC-10・UTC+14・UTC）", () => {
    for (const timeZone of ["Pacific/Honolulu", "Pacific/Kiritimati", "UTC"]) {
      withTimeZone(timeZone, () => {
        for (const entry of GOLDEN) {
          assert.equal(formatSlotLabel(entry.date, entry.start, entry.end), entry.label, `${timeZone}: ${entry.date}`);
        }
      });
    }
  });
  it("規則違反の時刻・実在しない日付・ISO形式でない日付は空文字", () => {
    assert.equal(timeLabel("10:00", "10:30"), "");
    assert.equal(formatSlotLabel("2026-10-01", "10:00", "10:30"), "");
    assert.equal(formatSlotLabel("2026-10-01", "09:00", null), "");
    assert.equal(formatSlotLabel("2026-02-30", "09:00", "12:00"), "");
    assert.equal(formatSlotLabel("2026-02-29", null, null), "");
    assert.equal(formatSlotLabel("2026/10/01", "09:00", "12:00"), "");
    assert.equal(formatSlotLabel("", null, null), "");
  });
});

describe("日付の補助（isValidIsoDate / addDaysIso / toIsoDateString）", () => {
  it("isValidIsoDate は実在する \"YYYY-MM-DD\" だけを通す", () => {
    assert.equal(isValidIsoDate("2028-02-29"), true);
    assert.equal(isValidIsoDate("2026-02-29"), false);
    assert.equal(isValidIsoDate("2026-13-01"), false);
    assert.equal(isValidIsoDate("2026-1-01"), false);
  });
  it("addDaysIso は月末・年末・うるう日をまたぐ", () => {
    assert.equal(addDaysIso("2026-12-31", 1), "2027-01-01");
    assert.equal(addDaysIso("2028-02-28", 1), "2028-02-29");
    assert.equal(addDaysIso("2026-09-27", 365), "2027-09-27");
    assert.equal(addDaysIso("2026-02-30", 1), "");
    assert.equal(addDaysIso("2026-10-01", 1.5), "");
  });
  it("toIsoDateString は年月日を2桁ゼロ埋めで整形する", () => {
    assert.equal(toIsoDateString(new Date(2026, 0, 5)), "2026-01-05");
    assert.equal(toIsoDateString(new Date(2026, 9, 15)), "2026-10-15");
  });
});

describe("jstNow / jstTodayIso（日本時間・ブラウザのタイムゾーンに依存しない）", () => {
  it("（前提）withTimeZone でローカルのタイムゾーンが実際に切り替わる（TZ の検証が空振りしない）", () => {
    const instant = new Date("2026-01-01T00:00:00Z");
    assert.equal(withTimeZone("Pacific/Honolulu", () => instant.getDate()), 31);
    assert.equal(withTimeZone("Pacific/Kiritimati", () => instant.getDate()), 1);
  });
  it("UTC 14:59 は日本時間の同日 23:59、UTC 15:00 は翌日 0:00", () => {
    assert.deepEqual(jstNow(new Date("2026-09-30T14:59:00Z")), { date: "2026-09-30", minutes: 23 * 60 + 59 });
    assert.deepEqual(jstNow(new Date("2026-09-30T15:00:00Z")), { date: "2026-10-01", minutes: 0 });
  });
  it("年末年始をまたぐ（UTC 12/31 15:00 は日本時間の 1/1）", () => {
    assert.equal(jstTodayIso(new Date("2026-12-31T15:00:00Z")), "2027-01-01");
  });
  it("process.env.TZ を変えても同じ結果になる", () => {
    const instant = new Date("2026-09-30T15:30:00Z");
    for (const timeZone of ["Pacific/Honolulu", "Pacific/Kiritimati", "America/New_York"]) {
      withTimeZone(timeZone, () => {
        assert.deepEqual(jstNow(instant), { date: "2026-10-01", minutes: 30 }, timeZone);
      });
    }
  });
  it("不正な Date は RangeError", () => {
    assert.throws(() => jstNow(new Date(Number.NaN)), RangeError);
  });
});

describe("isCandidateExpired（日本時間。日程構造化 DESIGN §13.1）", () => {
  // 2026-10-01T03:00:00Z = 日本時間 2026-10-01 12:00
  const noonJst = new Date("2026-10-01T03:00:00Z");

  it("今日より前の日付は過ぎている（時間指定なしでも）", () => {
    assert.equal(isCandidateExpired({ date: "2026-09-30", end: null }, noonJst), true);
    assert.equal(isCandidateExpired({ date: "2026-09-30", end: "21:00" }, noonJst), true);
  });
  it("今日で、現在時刻 ≥ end なら過ぎている（ちょうど end の時刻も含む）", () => {
    assert.equal(isCandidateExpired({ date: "2026-10-01", end: "12:00" }, noonJst), true);
    assert.equal(isCandidateExpired({ date: "2026-10-01", end: "09:00" }, noonJst), true);
  });
  it("今日で、end の前なら過ぎていない（11:59:59 に end 12:00）", () => {
    assert.equal(isCandidateExpired({ date: "2026-10-01", end: "12:00" }, new Date("2026-10-01T02:59:59Z")), false);
    assert.equal(isCandidateExpired({ date: "2026-10-01", end: "12:30" }, noonJst), false);
  });
  it("今日の時間指定なしは過ぎていない", () => {
    assert.equal(isCandidateExpired({ date: "2026-10-01", end: null }, noonJst), false);
  });
  it("明日以降は過ぎていない", () => {
    assert.equal(isCandidateExpired({ date: "2026-10-02", end: "09:00" }, noonJst), false);
  });
  it("UTC ではまだ前日でも、日本時間で日付が変わっていれば前日の候補は過ぎている", () => {
    // 2026-09-30T15:30:00Z = 日本時間 2026-10-01 0:30
    const justAfterMidnightJst = new Date("2026-09-30T15:30:00Z");
    assert.equal(isCandidateExpired({ date: "2026-09-30", end: null }, justAfterMidnightJst), true);
    assert.equal(isCandidateExpired({ date: "2026-10-01", end: "09:00" }, justAfterMidnightJst), false);
  });
  it("不正な日付・書式違いの end は過ぎている扱い（押させない安全側）", () => {
    assert.equal(isCandidateExpired({ date: "2026-02-30", end: null }, noonJst), true);
    assert.equal(isCandidateExpired({ date: "2026-10-02", end: "9:00" }, noonJst), true);
  });
});

describe("「時刻を指定」の選択肢", () => {
  it("開始は 6:00〜21:00、終了は 7:00〜22:00 の30分刻み", () => {
    assert.equal(CUSTOM_START_TIME_OPTIONS[0], "06:00");
    assert.equal(CUSTOM_START_TIME_OPTIONS[CUSTOM_START_TIME_OPTIONS.length - 1], "21:00");
    assert.equal(CUSTOM_START_TIME_OPTIONS.length, 31);
    assert.equal(CUSTOM_END_TIME_OPTIONS[0], "07:00");
    assert.equal(CUSTOM_END_TIME_OPTIONS[CUSTOM_END_TIME_OPTIONS.length - 1], "22:00");
    assert.equal(CUSTOM_END_TIME_OPTIONS.length, 31);
    for (const time of [...CUSTOM_START_TIME_OPTIONS, ...CUSTOM_END_TIME_OPTIONS]) {
      assert.notEqual(visitTimeToMinutes(time), null, time);
    }
  });
  it("既定の 10:00〜12:00 は選択肢に含まれ、時刻の規則を満たす", () => {
    assert.ok(CUSTOM_START_TIME_OPTIONS.includes(DEFAULT_CUSTOM_START_TIME));
    assert.ok(CUSTOM_END_TIME_OPTIONS.includes(DEFAULT_CUSTOM_END_TIME));
    assert.equal(isValidVisitTimeRange(DEFAULT_CUSTOM_START_TIME, DEFAULT_CUSTOM_END_TIME), true);
  });
});

describe("parseScheduleProposalMeta", () => {
  const candidate = (overrides: Record<string, unknown> = {}) => ({
    date: "2026-10-01",
    start: "09:00",
    end: "12:00",
    label: "2026年10月1日（木）9:00〜12:00",
    ...overrides,
  });

  it("v2 を候補つきで読む（余分なキーは無視する）", () => {
    const parsed = parseScheduleProposalMeta({
      v: 2,
      seq: 3,
      candidates: [candidate({ extra: "ignored" }), candidate({ date: "2026-10-03", start: null, end: null, label: "2026年10月3日（土）時間指定なし" })],
    });
    assert.deepEqual(parsed, {
      version: 2,
      seq: 3,
      candidates: [
        { date: "2026-10-01", start: "09:00", end: "12:00", label: "2026年10月1日（木）9:00〜12:00" },
        { date: "2026-10-03", start: null, end: null, label: "2026年10月3日（土）時間指定なし" },
      ],
    });
  });

  it("v2 の候補が1件でも規則に合わなければ全体を unknown にする（添字のずれを防ぐ）", () => {
    const broken: Record<string, unknown>[] = [
      candidate({ start: null }),
      candidate({ date: "2026-02-30" }),
      candidate({ date: 20261001 }),
      candidate({ start: "10:00", end: "10:30" }),
      candidate({ label: "" }),
      candidate({ label: "   " }),
      candidate({ label: 1 }),
    ];
    for (const bad of broken) {
      assert.deepEqual(parseScheduleProposalMeta({ v: 2, seq: 1, candidates: [candidate(), bad] }), { version: "unknown" }, JSON.stringify(bad));
    }
    assert.deepEqual(parseScheduleProposalMeta({ v: 2, seq: 1, candidates: [candidate(), null] }), { version: "unknown" });
  });

  it("v2 の seq・candidates の形が不正なら unknown", () => {
    for (const seq of [undefined, 0, -1, 1.5, "3", Number.NaN]) {
      assert.deepEqual(parseScheduleProposalMeta({ v: 2, seq, candidates: [candidate()] }), { version: "unknown" }, String(seq));
    }
    assert.deepEqual(parseScheduleProposalMeta({ v: 2, seq: 1, candidates: [] }), { version: "unknown" });
    const tooMany = Array.from({ length: MAX_SCHEDULE_CANDIDATES + 1 }, (_, i) =>
      candidate({ date: `2026-10-${String(i + 1).padStart(2, "0")}` }),
    );
    assert.deepEqual(parseScheduleProposalMeta({ v: 2, seq: 1, candidates: tooMany }), { version: "unknown" });
    assert.deepEqual(parseScheduleProposalMeta({ v: 2, seq: 1, slots: ["2026年10月1日（木）9:00〜12:00"] }), { version: "unknown" });
  });

  it("旧形式 {slots} は v1 として文字列だけを取り出す", () => {
    assert.deepEqual(parseScheduleProposalMeta({ slots: ["10月1日 午前", 1, null, "10月2日 午後"] }), {
      version: 1,
      slots: ["10月1日 午前", "10月2日 午後"],
    });
  });

  it("未知の版・オブジェクト以外は unknown", () => {
    for (const meta of [null, undefined, "v2", 2, [], {}, { v: 3, seq: 1, candidates: [candidate()] }, { v: 1, slots: ["a"] }]) {
      assert.deepEqual(parseScheduleProposalMeta(meta), { version: "unknown" }, JSON.stringify(meta));
    }
  });
});

describe("latestProposalId（seq の最大値。サーバーの superseded 判定と同じ定義）", () => {
  const v2 = (id: string, seq: number) => ({
    id,
    kind: "schedule_proposal",
    meta: { v: 2, seq, candidates: [{ date: "2026-10-01", start: null, end: null, label: "2026年10月1日（木）時間指定なし" }] },
  });

  it("配列の順ではなく seq が最大の提示を返す", () => {
    assert.equal(latestProposalId([v2("a", 1), v2("c", 3), v2("b", 2)]), "c");
  });
  it("v1・unknown・他の種類のメッセージは数えない（後ろにあっても）", () => {
    assert.equal(
      latestProposalId([
        v2("a", 2),
        { id: "old", kind: "schedule_proposal", meta: { slots: ["10月1日"] } },
        { id: "broken", kind: "schedule_proposal", meta: { v: 2, seq: 9, candidates: [] } },
        { id: "text", kind: "text", meta: { v: 2, seq: 99 } },
      ]),
      "a",
    );
  });
  it("v2 が無ければ null", () => {
    assert.equal(latestProposalId([]), null);
    assert.equal(latestProposalId([{ id: "old", kind: "schedule_proposal", meta: { slots: ["10月1日"] } }]), null);
  });
  it("同じ seq が並んだ場合は後ろのものを採る", () => {
    assert.equal(latestProposalId([v2("a", 2), v2("b", 2)]), "b");
  });
});

describe("parseScheduleConfirmedMeta", () => {
  it("v2 を読む（source・confirmed_by は既知の値だけ）", () => {
    assert.deepEqual(
      parseScheduleConfirmedMeta({
        v: 2,
        source: "proposal",
        proposal_id: "p1",
        candidate_index: 0,
        visit_date: "2026-10-01",
        visit_time_slot: "9:00〜12:00",
        label: "2026年10月1日（木）9:00〜12:00",
        confirmed_by: "admin",
      }),
      {
        version: 2,
        label: "2026年10月1日（木）9:00〜12:00",
        visitDate: "2026-10-01",
        visitTimeSlot: "9:00〜12:00",
        source: "proposal",
        confirmedBy: "admin",
      },
    );
    const unknownSource = parseScheduleConfirmedMeta({
      v: 2,
      source: "other",
      visit_date: "2026-10-01",
      visit_time_slot: "時間指定なし",
      label: "2026年10月1日（木）時間指定なし",
      confirmed_by: "system",
    });
    assert.equal(unknownSource.version, 2);
    if (unknownSource.version === 2) {
      assert.equal(unknownSource.source, null);
      assert.equal(unknownSource.confirmedBy, null);
    }
  });
  it("v2 で label・visit_date・visit_time_slot が欠けていれば unknown", () => {
    assert.deepEqual(parseScheduleConfirmedMeta({ v: 2, visit_date: "2026-10-01", visit_time_slot: "9:00〜12:00" }), { version: "unknown" });
    assert.deepEqual(parseScheduleConfirmedMeta({ v: 2, visit_date: "2026-10-01", label: "x" }), { version: "unknown" });
  });
  it("旧形式 {visit_date, visit_time_slot} は version 1", () => {
    assert.deepEqual(parseScheduleConfirmedMeta({ visit_date: "2026-10-01", visit_time_slot: "10月1日（木）10:00〜12:00" }), {
      version: 1,
      visitDate: "2026-10-01",
      visitTimeSlot: "10月1日（木）10:00〜12:00",
    });
  });
  it("オブジェクト以外・空・未知の版は unknown", () => {
    for (const meta of [null, undefined, [], {}, { v: 3, label: "x", visit_date: "2026-10-01", visit_time_slot: "9:00〜12:00" }]) {
      assert.deepEqual(parseScheduleConfirmedMeta(meta), { version: "unknown" }, JSON.stringify(meta));
    }
  });
});
