/**
 * text-guard.ts（表示用自由記述欄の送信前整形）の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/text-guard.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由・import に拡張子を付ける理由は
 * safe-path.test.mts と同じ（tsconfig の include に一致させず、型検査・ビルドの対象から
 * 外したまま実行できるようにするため）。
 *
 * 表記の注意: 対象文字はこのファイル上でも \u 形式のエスケープや実体（生の不可視文字）
 * では書かず、0x.. の数値コードポイントと String.fromCharCode / String.fromCodePoint で
 * 組み立てる（text-guard.ts の冒頭と同じ理由）。
 *
 * katadzuke-api.ts の guardDisplayText/withTextGuard について: 同ファイルの
 * KdzApiError/KdzNetworkError はコンストラクタにパラメータプロパティ
 * （`constructor(public readonly status: number, ...)`）を使っており、これは
 * Node の型除去（strip-only mode）が明示的に非対応の構文のため
 * （実行時に ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX で落ちることを確認済み）、
 * katadzuke-api.ts を本テストから直接 import することはできない。
 * よって本ファイルは text-guard.ts の範囲のみを検査する。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DISALLOWED_DISPLAY_CHAR_RANGES,
  countCodePoints,
  prepareDisplayText,
  sanitizeDisplayText,
} from "./text-guard.ts";

// ---------------------------------------------------------------------------
// 除去されるべき文字
// ---------------------------------------------------------------------------

/** Bidi_Control 12字（ALM・LRM・RLM・LRE・RLE・PDF・LRO・RLO・LRI・RLI・FSI・PDI）。 */
const BIDI_CONTROL_CODE_POINTS: readonly number[] = [
  0x061c,
  0x200e, 0x200f,
  0x202a, 0x202b, 0x202c, 0x202d, 0x202e,
  0x2066, 0x2067, 0x2068, 0x2069,
];

/** 改行(0x0A)以外のCc・DELの代表点（NUL・0x01・0x0B・0x0C・ESC・0x1F・DEL・0x80・NEL・0x9F）。 */
const OTHER_REMOVED_CODE_POINTS: readonly number[] = [
  0x00, 0x01, 0x0b, 0x0c, 0x1b, 0x1f, 0x7f, 0x80, 0x85, 0x9f,
];

describe("sanitizeDisplayText: 拒否文字の除去", () => {
  it("Bidi_Control 12字はすべて除去される", () => {
    for (const cp of BIDI_CONTROL_CODE_POINTS) {
      const input = String.fromCharCode(cp);
      assert.equal(sanitizeDisplayText(input), "", `codepoint=0x${cp.toString(16)}`);
      assert.equal(sanitizeDisplayText(`a${input}b`), "ab", `codepoint=0x${cp.toString(16)}`);
    }
  });

  it("改行(0x0A)以外のCc・DELがすべて除去される", () => {
    for (const cp of OTHER_REMOVED_CODE_POINTS) {
      const input = String.fromCharCode(cp);
      assert.equal(sanitizeDisplayText(input), "", `codepoint=0x${cp.toString(16)}`);
      assert.equal(sanitizeDisplayText(`a${input}b`), "ab", `codepoint=0x${cp.toString(16)}`);
    }
  });
});

// ---------------------------------------------------------------------------
// 改行・タブの正規化
// ---------------------------------------------------------------------------

describe("sanitizeDisplayText: 改行・タブの正規化", () => {
  it("タブは半角空白に置換される", () => {
    const tab = String.fromCharCode(0x09);
    assert.equal(sanitizeDisplayText(tab), " ");
    assert.equal(sanitizeDisplayText(`a${tab}b`), "a b");
  });

  it("CRLFはLF1つにまとめられる", () => {
    const crlf = String.fromCharCode(0x0d) + String.fromCharCode(0x0a);
    assert.equal(sanitizeDisplayText(crlf), "\n");
    assert.equal(sanitizeDisplayText(`a${crlf}b`), "a\nb");
  });

  it("単独のCRはLFになる", () => {
    const cr = String.fromCharCode(0x0d);
    assert.equal(sanitizeDisplayText(cr), "\n");
    assert.equal(sanitizeDisplayText(`a${cr}b`), "a\nb");
  });

  it("「LFの後にCR」は両方がLFになる（古い改行のまま連結しない）", () => {
    const lfCr = String.fromCharCode(0x0a) + String.fromCharCode(0x0d);
    assert.equal(sanitizeDisplayText(lfCr), "\n\n");
    assert.equal(sanitizeDisplayText(`a${lfCr}b`), "a\n\nb");
  });
});

// ---------------------------------------------------------------------------
// サロゲートの扱い
// ---------------------------------------------------------------------------

describe("sanitizeDisplayText: サロゲートの扱い", () => {
  it("孤立した上位サロゲートは除去される", () => {
    const lone = String.fromCharCode(0xd800);
    assert.equal(sanitizeDisplayText(lone), "");
    assert.equal(sanitizeDisplayText(`a${lone}b`), "ab");
  });

  it("孤立した下位サロゲートは除去される", () => {
    const lone = String.fromCharCode(0xdc00);
    assert.equal(sanitizeDisplayText(lone), "");
    assert.equal(sanitizeDisplayText(`a${lone}b`), "ab");
  });

  it("「上位＋RLO＋下位」はすべて除去される（除去後に新しいペアができない＝上位と下位の両方が消える）", () => {
    // 0xD83D + 0xDE00 は本来 U+1F600（正しいペア）になる組だが、間にRLOを挟むと
    // どちらも孤立サロゲート扱いになり、RLOも拒否文字のため全体が空文字になる。
    const broken = String.fromCharCode(0xd83d) + String.fromCharCode(0x202e) + String.fromCharCode(0xde00);
    assert.equal(sanitizeDisplayText(broken), "");
    assert.equal(sanitizeDisplayText(`a${broken}b`), "ab");
  });

  it("正しいサロゲートペア（U+1F600）は残る", () => {
    const emoji = String.fromCodePoint(0x1f600);
    assert.equal(sanitizeDisplayText(emoji), emoji);
    assert.equal(sanitizeDisplayText(`a${emoji}b`), `a${emoji}b`);
  });
});

// ---------------------------------------------------------------------------
// 変更されない文字（誤検知防止の固定）
// ---------------------------------------------------------------------------

/** 単独のコード単位でそのまま残るべき文字。 */
const UNCHANGED_SINGLE_CODE_POINTS: ReadonlyArray<readonly [number, string]> = [
  [0x200c, "ZWNJ"],
  [0x200b, "ZWSP"],
  [0xfeff, "BOM"],
  [0x00ad, "ソフトハイフン"],
  [0xe000, "私用領域(Co) U+E000"],
  [0x2028, "LINE SEPARATOR U+2028"],
  [0x2029, "PARAGRAPH SEPARATOR U+2029"],
  [0x0378, "未割り当て U+0378"],
  [0x00a0, "NBSP"],
  [0xfe0f, "VS16"],
  [0x206a, "非推奨書式文字 U+206A"],
];

/** ZWJ で結合した家族の絵文字（man + ZWJ + woman + ZWJ + girl + ZWJ + boy）。 */
const FAMILY_EMOJI =
  String.fromCodePoint(0x1f468) +
  String.fromCharCode(0x200d) +
  String.fromCodePoint(0x1f469) +
  String.fromCharCode(0x200d) +
  String.fromCodePoint(0x1f467) +
  String.fromCharCode(0x200d) +
  String.fromCodePoint(0x1f466);

/** タグ文字による国旗（スコットランド: 黒旗 + g/b/s/c/t + タグ終端）。 */
const SCOTLAND_FLAG =
  String.fromCodePoint(0x1f3f4) +
  String.fromCodePoint(0xe0067) +
  String.fromCodePoint(0xe0062) +
  String.fromCodePoint(0xe0073) +
  String.fromCodePoint(0xe0063) +
  String.fromCodePoint(0xe0074) +
  String.fromCodePoint(0xe007f);

/** 地域指示子による国旗（日本: J + P）。 */
const JAPAN_FLAG = String.fromCodePoint(0x1f1ef) + String.fromCodePoint(0x1f1f5);

describe("sanitizeDisplayText: 許可文字は変更されない", () => {
  for (const [cp, label] of UNCHANGED_SINGLE_CODE_POINTS) {
    it(`${label} はそのまま残る`, () => {
      const input = String.fromCharCode(cp);
      assert.equal(sanitizeDisplayText(input), input);
      assert.equal(sanitizeDisplayText(`a${input}b`), `a${input}b`);
    });
  }

  it("補助面の私用領域 U+F0000 はそのまま残る", () => {
    const input = String.fromCodePoint(0xf0000);
    assert.equal(sanitizeDisplayText(input), input);
  });

  it("ZWJ で結合した家族の絵文字はそのまま残る", () => {
    assert.equal(sanitizeDisplayText(FAMILY_EMOJI), FAMILY_EMOJI);
  });

  it("タグ文字による国旗（スコットランド）はそのまま残る", () => {
    assert.equal(sanitizeDisplayText(SCOTLAND_FLAG), SCOTLAND_FLAG);
  });

  it("地域指示子による国旗（日本）はそのまま残る", () => {
    assert.equal(sanitizeDisplayText(JAPAN_FLAG), JAPAN_FLAG);
  });

  it("日本語はそのまま残る", () => {
    const input = "こんにちは、片付けのご相談です。よろしくお願いします。";
    assert.equal(sanitizeDisplayText(input), input);
  });
});

// ---------------------------------------------------------------------------
// 全BMPコード単位の網羅照合
// ---------------------------------------------------------------------------

/**
 * backend の DISALLOWED_DISPLAY_CHAR_RANGES をこのテストにも書き写したもの。
 * text-guard.ts 側の DISALLOWED_DISPLAY_CHAR_RANGES を import して使い回さず、
 * 意図的に別の配列として保持する（範囲表そのものを書き換えるミスを、この複製が
 * 独立して検知できるようにするため）。
 */
const EXPECTED_DISALLOWED_RANGES: ReadonlyArray<readonly [number, number]> = [
  [0x0000, 0x0009],
  [0x000b, 0x001f],
  [0x007f, 0x009f],
  [0x061c, 0x061c],
  [0x200e, 0x200f],
  [0x202a, 0x202e],
  [0x2066, 0x2069],
  [0xd800, 0xdfff],
];

function isExpectedDisallowed(code: number): boolean {
  return EXPECTED_DISALLOWED_RANGES.some(([lo, hi]) => code >= lo && code <= hi);
}

describe("DISALLOWED_DISPLAY_CHAR_RANGES", () => {
  it("エクスポートされた範囲表がこのテストの複製と一致する", () => {
    assert.deepEqual(DISALLOWED_DISPLAY_CHAR_RANGES, EXPECTED_DISALLOWED_RANGES);
  });
});

describe("sanitizeDisplayText: 全BMPコード単位の網羅照合", () => {
  it("0x0000〜0xFFFFの各コード単位を単独で渡すと、書き写した範囲表どおりに変換される", () => {
    for (let code = 0x0000; code <= 0xffff; code++) {
      const input = String.fromCharCode(code);
      const actual = sanitizeDisplayText(input);
      let expected: string;
      if (code === 0x09) {
        expected = " "; // タブ→空白
      } else if (code === 0x0d) {
        expected = "\n"; // 単独CR→LF
      } else if (code === 0x0a) {
        expected = "\n"; // LFはそのまま
      } else if (isExpectedDisallowed(code)) {
        expected = ""; // 他の拒否範囲は除去（サロゲートも単独では孤立扱いになる）
      } else {
        expected = input; // それ以外は許可
      }
      assert.equal(actual, expected, `code=0x${code.toString(16)}`);
    }
  });
});

// ---------------------------------------------------------------------------
// 冪等性
// ---------------------------------------------------------------------------

describe("sanitizeDisplayText: 冪等性", () => {
  it("2回整形しても結果が変わらない", () => {
    const samples = [
      "",
      "こんにちは",
      `a${String.fromCharCode(0x09)}b`,
      `a${String.fromCharCode(0x0d)}${String.fromCharCode(0x0a)}b`,
      String.fromCodePoint(0x1f600),
      FAMILY_EMOJI,
      SCOTLAND_FLAG,
      `${String.fromCharCode(0x202e)}秘密${String.fromCharCode(0xd800)}`,
    ];
    for (const sample of samples) {
      const once = sanitizeDisplayText(sample);
      assert.equal(sanitizeDisplayText(once), once, `sample=${JSON.stringify(sample)}`);
    }
  });
});

// ---------------------------------------------------------------------------
// countCodePoints
// ---------------------------------------------------------------------------

describe("countCodePoints", () => {
  it("サロゲートペアは1文字として数える（Pythonのlen()と一致させるため）", () => {
    assert.equal(countCodePoints(String.fromCodePoint(0x1f600)), 1);
    assert.equal(countCodePoints(String.fromCodePoint(0x1f600).repeat(3)), 3);
  });

  it("孤立サロゲートもそれ自体を1文字として数える", () => {
    assert.equal(countCodePoints(String.fromCharCode(0xd800)), 1);
  });

  it("日本語は1文字ずつ数える", () => {
    assert.equal(countCodePoints("こんにちは"), 5);
  });

  it("空文字は0", () => {
    assert.equal(countCodePoints(""), 0);
  });
});

// ---------------------------------------------------------------------------
// prepareDisplayText
// ---------------------------------------------------------------------------

describe("prepareDisplayText", () => {
  it("拒否文字だけの入力は only_disallowed", () => {
    const rlo = String.fromCharCode(0x202e);
    const result = prepareDisplayText(rlo + rlo);
    assert.deepEqual(result, { ok: false, reason: "only_disallowed" });
  });

  it("空白だけの入力は ok（必須入力かどうかは呼び出し側の画面チェックに委ねる）", () => {
    assert.deepEqual(prepareDisplayText("   "), { ok: true, value: "   " });
  });

  it("空文字は ok", () => {
    assert.deepEqual(prepareDisplayText(""), { ok: true, value: "" });
  });

  it("「理由です」+LRM6個（見た目は10文字）はLRMが除去されてminLength=10未満になりtoo_short", () => {
    const lrm = String.fromCharCode(0x200e);
    const input = "理由です" + lrm.repeat(6);
    assert.equal(input.length, 10);
    const result = prepareDisplayText(input, { minLength: 10 });
    assert.deepEqual(result, { ok: false, reason: "too_short", minLength: 10 });
  });

  it("絵文字5個はUTF-16長は10だがコードポイント数は5でminLength=10未満になりtoo_short", () => {
    const emoji = String.fromCodePoint(0x1f600);
    const input = emoji.repeat(5);
    assert.equal(input.length, 10); // サロゲートペア×5 = UTF-16コード単位10個
    assert.equal(countCodePoints(input), 5);
    const result = prepareDisplayText(input, { minLength: 10 });
    assert.deepEqual(result, { ok: false, reason: "too_short", minLength: 10 });
  });

  it("minLengthを満たす通常の文章はok", () => {
    const input = "これは十分な長さの理由です";
    const result = prepareDisplayText(input, { minLength: 10 });
    assert.deepEqual(result, { ok: true, value: input });
  });

  it("minLength未指定なら短い文章でもok", () => {
    assert.deepEqual(prepareDisplayText("短い"), { ok: true, value: "短い" });
  });
});
