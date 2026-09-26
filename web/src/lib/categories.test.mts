/**
 * categories.ts の stripControlChars / stripControlCharsKeepNewlines / slotMonthDays /
 * formatVisitSchedule の回帰テスト（候補日ラベルからの訪問日の読み取り〔旧 slotVisitDate〕は
 * visit-slots.ts の parseSlotDate に一本化し、そのテストは visit-slots.test.mts にある）。
 *
 * 実行（cwd は web）: node --test src/lib/categories.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由は safe-path.test.mts と同じ
 * （tsconfig の include に一致させず、型検査・ビルドの対象から外したまま実行できるようにするため）。
 *
 * 双方向制御・ゼロ幅等の制御文字はソースに生の文字として埋め込まない。GitHub の
 * hidden bidirectional Unicode 警告（Trojan Source, CVE-2021-42574）の対象になり、
 * レビューでも目視できなくなるため（safe-path.test.mts の \u007f と同じ意図だが、
 * 編集ツール経由で \uXXXX と書いた箇所が実体の文字に変換されて保存される事故が
 * あったため、String.fromCharCode で組み立てる）。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  formatVisitSchedule,
  slotMonthDays,
  stripControlChars,
  stripControlCharsKeepNewlines,
} from "./categories.ts";

/** テスト名の表示用（制御文字そのものを端末に出力しないよう \u+コードポイントで表す）。 */
function codePointLabel(ch: string): string {
  return [...ch].map((c) => `U+${c.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`).join(",");
}

const RLO = String.fromCharCode(0x202e); // 双方向制御: RIGHT-TO-LEFT OVERRIDE
const LRI = String.fromCharCode(0x2066); // 双方向制御: LEFT-TO-RIGHT ISOLATE
const ZWSP = String.fromCharCode(0x200b); // ゼロ幅スペース
const ZWJ = String.fromCharCode(0x200d); // ゼロ幅結合子（絵文字の結合に使われる）
const BOM = String.fromCharCode(0xfeff); // BOM / ZERO WIDTH NO-BREAK SPACE
const WJ = String.fromCharCode(0x2060); // ワードジョイナー
const ALM = String.fromCharCode(0x061c); // ARABIC LETTER MARK（アラビア文字数字形）
const SHY = String.fromCharCode(0x00ad); // ソフトハイフン
const PUA = String.fromCharCode(0xe000); // 私用領域の先頭
const NBSP = String.fromCharCode(0x00a0); // ノーブレークスペース（Cc/Cf/Co/Cs ではないため残す対象）
const LS = String.fromCharCode(0x2028); // 行区切り（Zl）
const PS = String.fromCharCode(0x2029); // 段落区切り（Zp）

/** 月ligature（IDEOGRAPHIC TELEGRAPH SYMBOL FOR MONTH、例: 10月なら U+32C9）を生成する。 */
const monthLigature = (month: number): string => String.fromCharCode(0x32c0 + month - 1);
/** 日ligature（IDEOGRAPHIC TELEGRAPH SYMBOL FOR DAY、例: 1日なら U+33E0）を生成する。 */
const dayLigature = (day: number): string => String.fromCharCode(0x33e0 + day - 1);
/** タイ数字1桁（0〜9）を生成する。NFKC で ASCII 数字には変換されない。 */
const thaiDigit = (n: number): string => String.fromCharCode(0x0e50 + n);

describe("stripControlChars", () => {
  const REMOVED_CHARS: ReadonlyArray<readonly [name: string, ch: string]> = [
    ["双方向制御 RLO", RLO],
    ["双方向制御 LRI", LRI],
    ["ゼロ幅スペース", ZWSP],
    ["BOM/ZWNBSP", BOM],
    ["ワードジョイナー", WJ],
    ["アラビア文字数字形(ALM)", ALM],
    ["ソフトハイフン", SHY],
    ["改行", "\n"],
    ["タブ", "\t"],
    ["私用領域", PUA],
    ["孤立サロゲート", "\uD800"],
    ["行区切り(LS)", LS],
    ["段落区切り(PS)", PS],
  ];
  for (const [name, ch] of REMOVED_CHARS) {
    it(`${name}（${codePointLabel(ch)}）を除去する`, () => {
      assert.equal(stripControlChars(`前${ch}後`), "前後");
    });
  }

  const KEPT_CHARS: ReadonlyArray<readonly [name: string, ch: string]> = [
    ["日本語", "日本語"],
    ["波ダッシュ", "〜"],
    ["絵文字（サロゲートペア）", "😀"],
    ["NBSP", NBSP],
  ];
  for (const [name, ch] of KEPT_CHARS) {
    it(`${name}（${codePointLabel(ch)}）は残す`, () => {
      assert.equal(stripControlChars(`前${ch}後`), `前${ch}後`);
    });
  }
});

describe("stripControlCharsKeepNewlines", () => {
  it("改行は残す", () => {
    assert.equal(stripControlCharsKeepNewlines("前\n後"), "前\n後");
  });

  const REMOVED: ReadonlyArray<readonly [name: string, ch: string]> = [
    ["CR", "\r"],
    ["タブ", "\t"],
    ["双方向制御 RLO", RLO],
    ["ゼロ幅スペース", ZWSP],
    ["ZWJ", ZWJ],
  ];
  for (const [name, ch] of REMOVED) {
    it(`${name}（${codePointLabel(ch)}）は除去する`, () => {
      assert.equal(stripControlCharsKeepNewlines(`前${ch}後`), "前後");
    });
  }

  it("改行と除去対象が混在していても改行だけ残す", () => {
    assert.equal(stripControlCharsKeepNewlines(`一行目${RLO}\n二行目${ZWJ}`), "一行目\n二行目");
  });
});

describe("slotMonthDays", () => {
  it("ASCII数字: 10月1日 → [{month:10, day:1}]", () => {
    assert.deepEqual(slotMonthDays("10月1日"), [{ month: 10, day: 1 }]);
  });

  it("全角数字: １０月１日 → [{month:10, day:1}]（NFKCでASCIIに正規化される）", () => {
    assert.deepEqual(slotMonthDays("１０月１日"), [{ month: 10, day: 1 }]);
  });

  it("月日の合字（IDEOGRAPHIC TELEGRAPH SYMBOL）→ NFKCで10月1日に正規化される", () => {
    const slot = `${monthLigature(10)}${dayLigature(1)}`;
    assert.deepEqual(slotMonthDays(slot), [{ month: 10, day: 1 }]);
  });

  it("数字と月/日の間に空白があっても許容する: 10月 1日", () => {
    assert.deepEqual(slotMonthDays("10月 1日"), [{ month: 10, day: 1 }]);
  });

  it("タイ数字は NFKC で ASCII 数字に変換されないため空配列", () => {
    const slot = `${thaiDigit(1)}${thaiDigit(0)}月${thaiDigit(1)}日`; // タイ数字の "10月1日"
    assert.deepEqual(slotMonthDays(slot), []);
  });

  it("複数の日付をすべて拾う: 10月1日〜10月2日", () => {
    assert.deepEqual(slotMonthDays("10月1日〜10月2日"), [
      { month: 10, day: 1 },
      { month: 10, day: 2 },
    ]);
  });

  it("日付を含まない文字列は空配列", () => {
    assert.deepEqual(slotMonthDays("9:00〜12:00"), []);
  });
});

describe("formatVisitSchedule（2026-10-01 は木曜）", () => {
  it("(null, null) → 空文字", () => {
    assert.equal(formatVisitSchedule(null, null), "");
  });

  it("(visitDate, null) → 日付ラベルのみ", () => {
    assert.equal(formatVisitSchedule("2026-10-01", null), "10月1日（木）");
  });

  it("slot に日付を含まない → 日付ラベル + slot", () => {
    assert.equal(formatVisitSchedule("2026-10-01", "9:00〜12:00"), "10月1日（木） 9:00〜12:00");
  });

  it("slot 内の日付が visit_date と一致 → slot のみ（日付を重ねない）", () => {
    assert.equal(
      formatVisitSchedule("2026-10-01", "10月1日（木）10:00〜12:00"),
      "10月1日（木）10:00〜12:00",
    );
  });

  it("slot 内の数字と月/日の間に空白があっても一致判定する → slot のみ", () => {
    assert.equal(
      formatVisitSchedule("2026-10-01", "10月 1日（木）10:00〜12:00"),
      "10月 1日（木）10:00〜12:00",
    );
  });

  it("slot 内の日付が visit_date と食い違う → visit_date を先頭に出す", () => {
    assert.equal(
      formatVisitSchedule("2026-10-01", "9月28日（月）10:00〜12:00"),
      "10月1日（木） 9月28日（月）10:00〜12:00",
    );
  });

  it("全角数字の slot も NFKC 正規化して一致判定する → slot のみ", () => {
    assert.equal(formatVisitSchedule("2026-10-01", "１０月１日 10:00"), "１０月１日 10:00");
  });

  it("slot 内に別々の日付が2つ以上ある → 一致とみなさず visit_date を先頭に出す", () => {
    assert.equal(
      formatVisitSchedule("2026-10-01", "10月1日〜10月2日"),
      "10月1日（木） 10月1日〜10月2日",
    );
  });

  it("(null, slot) → slot をそのまま返す", () => {
    assert.equal(formatVisitSchedule(null, "10月1日 10:00"), "10月1日 10:00");
  });

  it("双方向制御文字入りの slot → 除去した文字列で visit_date を先頭に出す", () => {
    assert.equal(
      formatVisitSchedule("2026-10-01", `${RLO}00:21〜00:01`),
      "10月1日（木） 00:21〜00:01",
    );
  });

  it("visitDate が不正な日付 → 文字列そのものを先頭に出す", () => {
    assert.equal(
      formatVisitSchedule("invalid-date", "10月1日 10:00"),
      "invalid-date 10月1日 10:00",
    );
  });
});
