/**
 * categories.ts の stripControlChars / stripControlCharsKeepNewlines / formatVisitSchedule の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/categories.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由は safe-path.test.mts と同じ
 * （tsconfig の include に一致させず、型検査・ビルドの対象から外したまま実行できるようにするため）。
 *
 * 双方向制御・ゼロ幅等の制御文字はソースに生の文字として埋め込まない。GitHub の
 * hidden bidirectional Unicode 警告（Trojan Source, CVE-2021-42574）の対象になり、
 * レビューでも目視できなくなるため（編集ツール経由で \uXXXX と書いた箇所が実体の文字に
 * 変換されて保存される事故があったため、String.fromCharCode で組み立てる）。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { formatVisitSchedule, stripControlChars, stripControlCharsKeepNewlines } from "./categories.ts";
import { VISIT_TIME_SLOTS } from "./visit-slots.ts";

/** テスト名の表示用（制御文字そのものを端末に出力しないよう U+コードポイントで表す）。 */
function codePointLabel(ch: string): string {
  return [...ch].map((c) => `U+${c.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`).join(",");
}

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

const RLO = String.fromCharCode(0x202e); // 双方向制御: RIGHT-TO-LEFT OVERRIDE
const LRI = String.fromCharCode(0x2066); // 双方向制御: LEFT-TO-RIGHT ISOLATE
const ZWSP = String.fromCharCode(0x200b); // ゼロ幅スペース
const ZWJ = String.fromCharCode(0x200d); // ゼロ幅結合子（絵文字の結合に使われる）
const BOM = String.fromCharCode(0xfeff); // BOM / ZERO WIDTH NO-BREAK SPACE
const WJ = String.fromCharCode(0x2060); // ワードジョイナー
const ALM = String.fromCharCode(0x061c); // ARABIC LETTER MARK
const SHY = String.fromCharCode(0x00ad); // ソフトハイフン
const PUA = String.fromCharCode(0xe000); // 私用領域の先頭
const LONE_SURROGATE = String.fromCharCode(0xd800); // 孤立サロゲート
const NBSP = String.fromCharCode(0x00a0); // ノーブレークスペース（Cc/Cf/Co/Cs ではないため残す対象）
const LS = String.fromCharCode(0x2028); // 行区切り（Zl）
const PS = String.fromCharCode(0x2029); // 段落区切り（Zp）
const FULLWIDTH_TILDE = String.fromCharCode(0xff5e); // 全角チルダ（波ダッシュ U+301C との取り違え）

describe("stripControlChars", () => {
  const REMOVED_CHARS: ReadonlyArray<readonly [name: string, ch: string]> = [
    ["双方向制御 RLO", RLO],
    ["双方向制御 LRI", LRI],
    ["ゼロ幅スペース", ZWSP],
    ["BOM/ZWNBSP", BOM],
    ["ワードジョイナー", WJ],
    ["アラビア文字マーク(ALM)", ALM],
    ["ソフトハイフン", SHY],
    ["改行", "\n"],
    ["タブ", "\t"],
    ["私用領域", PUA],
    ["孤立サロゲート", LONE_SURROGATE],
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
    ["私用領域", PUA],
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

describe("formatVisitSchedule（日程構造化 DESIGN §13.4・2026-10-01 は木曜）", () => {
  it("visitDate が無ければ空文字（時間帯だけは出さない）", () => {
    assert.equal(formatVisitSchedule(null, null), "");
    assert.equal(formatVisitSchedule(undefined, "9:00〜12:00"), "");
    assert.equal(formatVisitSchedule("", "時間指定なし"), "");
  });

  it("(visitDate, null/空文字) → 日付ラベルのみ", () => {
    assert.equal(formatVisitSchedule("2026-10-01", null), "10月1日（木）");
    assert.equal(formatVisitSchedule("2026-10-01", undefined), "10月1日（木）");
    assert.equal(formatVisitSchedule("2026-10-01", ""), "10月1日（木）");
  });

  it("固定5種（VISIT_TIME_SLOTS）はすべて日付の後ろに付ける", () => {
    for (const slot of VISIT_TIME_SLOTS) {
      assert.equal(formatVisitSchedule("2026-10-01", slot.value), `10月1日（木） ${slot.value}`);
    }
  });

  it("「時刻を指定」の時刻の範囲（例: 10:30〜12:00・6:00〜7:00）も付ける", () => {
    assert.equal(formatVisitSchedule("2026-10-01", "10:30〜12:00"), "10月1日（木） 10:30〜12:00");
    assert.equal(formatVisitSchedule("2026-10-01", "6:00〜7:00"), "10月1日（木） 6:00〜7:00");
  });

  const NOT_APPENDED: ReadonlyArray<readonly [name: string, slot: string]> = [
    ["日付入りの旧ラベル（visit_date と一致）", "10月1日（木）10:00〜12:00"],
    ["日付入りの旧ラベル（visit_date と食い違う）", "9月28日（月）10:00〜12:00"],
    ["年入りの旧ラベル", "2026年10月1日（木）9:00〜12:00"],
    ["業者の自由記述", "午前中にお願いします"],
    ["ハイフン区切り", "10:00-12:00"],
    ["全角チルダ（U+FF5E）", `9:00${FULLWIDTH_TILDE}12:00`],
    ["双方向制御入り", `${RLO}00:21〜00:01`],
    ["ゼロ幅入り", `9:00〜${ZWSP}12:00`],
    ["前後の空白", " 9:00〜12:00"],
    ["末尾の改行", "9:00〜12:00\n"],
    ["時間指定なし＋余分な文字", "時間指定なし（午後希望）"],
  ];
  for (const [name, slot] of NOT_APPENDED) {
    it(`${name}は付けず、日付だけを出す`, () => {
      assert.equal(formatVisitSchedule("2026-10-01", slot), "10月1日（木）");
    });
  }

  it("visitDate が形式違い・実在しない日付なら、その文字列（制御文字を除去）を日付の位置に出す", () => {
    assert.equal(formatVisitSchedule("invalid-date", "9:00〜12:00"), "invalid-date 9:00〜12:00");
    assert.equal(formatVisitSchedule("2026-02-30", null), "2026-02-30");
    assert.equal(formatVisitSchedule(`2026-10-01${RLO}`, null), "2026-10-01");
  });

  it("ブラウザのタイムゾーンが違っても同じ曜日になる", () => {
    for (const timeZone of ["Pacific/Honolulu", "Pacific/Kiritimati", "UTC"]) {
      withTimeZone(timeZone, () => {
        assert.equal(formatVisitSchedule("2026-10-01", "9:00〜12:00"), "10月1日（木） 9:00〜12:00", timeZone);
      });
    }
  });
});
