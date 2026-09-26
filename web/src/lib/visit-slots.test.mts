/**
 * visit-slots.ts の純関数の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/visit-slots.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由・import に拡張子を付ける理由は
 * safe-path.test.mts / review-verdict.test.mts と同じ（tsconfig の include に一致させず、
 * 型検査・ビルドの対象から外したまま実行できるようにするため）。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  VISIT_TIME_SLOTS,
  VISIT_TIME_SLOT_MAX_LENGTH,
  formatSlotLabel,
  parseSlotDate,
  toIsoDateString,
} from "./visit-slots.ts";

describe("VISIT_TIME_SLOTS", () => {
  it("5件の時間帯（値・表示名）を持つ", () => {
    assert.deepEqual(VISIT_TIME_SLOTS, [
      { value: "9:00〜12:00", label: "午前" },
      { value: "12:00〜15:00", label: "昼" },
      { value: "15:00〜18:00", label: "午後" },
      { value: "18:00〜21:00", label: "夜" },
      { value: "時間指定なし", label: "業者に一任" },
    ]);
  });

  it("すべての候補ラベル（年入り・最長の時間帯 18:00〜21:00）が VISIT_TIME_SLOT_MAX_LENGTH 以内", () => {
    for (const slot of VISIT_TIME_SLOTS) {
      const label = formatSlotLabel("2026-12-31", slot.value);
      assert.ok(
        label.length <= VISIT_TIME_SLOT_MAX_LENGTH,
        `"${label}" (${label.length}字) が上限 ${VISIT_TIME_SLOT_MAX_LENGTH} 字を超えている`,
      );
    }
  });
});

describe("toIsoDateString", () => {
  it("年月日を2桁ゼロ埋めで整形する", () => {
    assert.equal(toIsoDateString(new Date(2026, 0, 5)), "2026-01-05");
  });
  it("2桁の月日はそのまま整形する", () => {
    assert.equal(toIsoDateString(new Date(2026, 9, 15)), "2026-10-15");
  });
});

describe("formatSlotLabel", () => {
  it("1桁の月日でも年・曜日入りラベルを生成する（日付と時間の間に空白を入れない）", () => {
    // 2026-01-05 は月曜日
    assert.equal(formatSlotLabel("2026-01-05", "9:00〜12:00"), "2026年1月5日（月）9:00〜12:00");
  });
  it("2桁の月日でもラベルを生成する", () => {
    // 2026-10-15 は木曜日
    assert.equal(formatSlotLabel("2026-10-15", "18:00〜21:00"), "2026年10月15日（木）18:00〜21:00");
  });
  it("「時間指定なし」も値のまま連結する", () => {
    assert.equal(formatSlotLabel("2026-10-15", "時間指定なし"), "2026年10月15日（木）時間指定なし");
  });
  it("うるう年の2月29日を正しく扱う（2028年はうるう年）", () => {
    assert.equal(formatSlotLabel("2028-02-29", "9:00〜12:00"), "2028年2月29日（火）9:00〜12:00");
  });
  it("実在しない日付（2月30日）は空文字を返す", () => {
    assert.equal(formatSlotLabel("2026-02-30", "9:00〜12:00"), "");
  });
  it("うるう年でない年の2月29日は空文字を返す", () => {
    assert.equal(formatSlotLabel("2026-02-29", "9:00〜12:00"), "");
  });
  it("ISO形式でない日付は空文字を返す", () => {
    assert.equal(formatSlotLabel("2026/10/15", "9:00〜12:00"), "");
    assert.equal(formatSlotLabel("10月15日", "9:00〜12:00"), "");
    assert.equal(formatSlotLabel("", "9:00〜12:00"), "");
  });
});

describe("parseSlotDate", () => {
  const today = new Date(2026, 5, 15); // 2026-06-15 とみなす

  it("年入りラベルはその年をそのまま使う（未来日）", () => {
    assert.equal(parseSlotDate("2026年10月15日（木）9:00〜12:00", today), "2026-10-15");
  });
  it("年入りラベルはその年をそのまま使う（過去日でも解析自体は成功する）", () => {
    assert.equal(parseSlotDate("2026年1月5日（月）9:00〜12:00", today), "2026-01-05");
  });
  it("年入りで実在しない日付（2月30日）は null", () => {
    assert.equal(parseSlotDate("2026年2月30日（月）9:00〜12:00", today), null);
  });
  it("年入りでうるう年でない年の2月29日は null", () => {
    assert.equal(parseSlotDate("2026年2月29日（日）9:00〜12:00", today), null);
  });
  it("年入りでうるう年の2月29日は解析できる", () => {
    assert.equal(parseSlotDate("2028年2月29日（火）9:00〜12:00", today), "2028-02-29");
  });

  it("年なし・今日の月より後の月なら今年を採用する（旧形式の後方互換）", () => {
    assert.equal(parseSlotDate("10月15日（木）9:00〜12:00", today), "2026-10-15");
  });
  it("年なし・今日の月より前の月なら来年を採用する（繰り上げ推定）", () => {
    assert.equal(parseSlotDate("1月5日（月）9:00〜12:00", today), "2027-01-05");
  });
  it("年なし・今日と同じ月日は今年（過去日扱いにしない）", () => {
    assert.equal(parseSlotDate("6月15日（月）9:00〜12:00", today), "2026-06-15");
  });
  it("年なし・同月内でも today より前の日付なら来年を採用する（月単位ではなく日付そのもので判定する）", () => {
    assert.equal(parseSlotDate("6月1日（月）9:00〜12:00", today), "2027-06-01");
  });

  it("月日パターンに一致しない文字列は null", () => {
    assert.equal(parseSlotDate("来週の午前中でお願いします", today), null);
    assert.equal(parseSlotDate("", today), null);
  });
  it("月が範囲外（13月）は null", () => {
    assert.equal(parseSlotDate("13月1日", today), null);
  });
  it("日が範囲外（32日）は null", () => {
    assert.equal(parseSlotDate("1月32日", today), null);
  });

  it("年なしで存在しない日（4月31日）は null", () => {
    assert.equal(parseSlotDate("4月31日（金）9:00〜12:00", today), null);
  });
  it("年なしで繰り上げ先の年も平年の2月29日は null（2026年・2027年とも平年）", () => {
    assert.equal(parseSlotDate("2月29日（日）9:00〜12:00", today), null);
  });
  it("年なしでも繰り上げ先の年がうるう年なら2月29日は実在する", () => {
    // 2027-12-20（2027年は平年）を基準にすると、2月は今日の月より前なので来年（2028）へ繰り上がる。
    // 2028年はうるう年なので 2月29日 は実在する。
    const todayLateInLeapCycle = new Date(2027, 11, 20);
    assert.equal(parseSlotDate("2月29日（火）9:00〜12:00", todayLateInLeapCycle), "2028-02-29");
  });

  it("formatSlotLabel の出力を再度 parseSlotDate に通すと同じ ISO 日付に戻る（年入り・往復一致）", () => {
    const isoDates = ["2026-01-05", "2026-10-15", "2026-12-31", "2028-02-29"];
    for (const iso of isoDates) {
      const label = formatSlotLabel(iso, "9:00〜12:00");
      assert.equal(parseSlotDate(label, today), iso, `label=${label}`);
    }
  });
});
