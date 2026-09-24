/**
 * safeInternalPath（オープンリダイレクト対策）の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/safe-path.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。
 *
 * 拡張子を .mts にしている理由: Node の ESM ローダは拡張子付きの import（"./safe-path.ts"）を
 * 要求するが、web/tsconfig.json は allowImportingTsExtensions を有効にしていないため、
 * .ts のテストファイルに書くと tsc --noEmit / next build の型検査が TS5097 で落ちる。
 * tsconfig の include（"**\/*.ts" / "**\/*.tsx"）に一致しない .mts に置くことで、
 * アプリの型検査・ビルドの対象から外したまま（tsconfig を変えずに）実行できる。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { safeInternalPath } from "./safe-path.ts";

const FALLBACK = "/fallback";

/** 本番の遷移先解釈（Next のルーターの new URL(href, location.href)）を模すための現在地。 */
const CURRENT_LOCATION = "https://katazuke.example/login?callbackUrl=x";

/**
 * テスト名の表示用。JSON.stringify は U+0000〜U+001F をエスケープするが DEL（U+007F）は
 * 生のまま出すため（端末上で "//evil.example" に見えてしまう）、DEL も \u007f で表示する。
 */
function describeInput(input: string | null | undefined): string {
  if (input == null) return String(input);
  return JSON.stringify(input).replace(/\u007f/g, "\\u007f");
}

/** fallback になるべき入力（外部 origin・スキーム相対 URL に解釈されうるもの・不正値）。 */
const REJECTED_INPUTS: ReadonlyArray<string | null | undefined> = [
  // セキュリティレビュー MEDIUM の再現入力: URL パーサが TAB/LF/CR を除去して "//evil.example" になる
  "/\t/evil.example",
  "/\n/evil.example",
  "/\r/evil.example",
  "/\t\\evil.example",
  // 旧実装から拒否していた形
  "//evil",
  "/\\evil",
  "https://evil",
  "javascript:alert(1)",
  "",
  null,
  undefined,
  // ドットセグメント解決後に "//" で始まる（遷移時にスキーム相対 URL になる）
  "/a/..//evil",
  "/.//evil",
  "/%2e%2e//evil",
  // TAB/LF/CR 以外の制御文字・DEL・先頭のバックスラッシュ・先頭が "/" でないもの
  "/\u0000/evil.example",
  "/\u000b/evil.example",
  "/\u007f/evil.example",
  "\\\\evil.example",
  " /cases",
  "cases",
];

/** 許可されるべき入力と、正規化後に返るべき値。 */
const ALLOWED_CASES: ReadonlyArray<readonly [input: string, expected: string]> = [
  ["/cases", "/cases"],
  ["/cases/abc?tab=bids#top", "/cases/abc?tab=bids#top"],
  ["/mypage", "/mypage"],
  ["/operator/cases", "/operator/cases"],
  ["/cases/../mypage", "/mypage"],
  // 呼び出し側の接頭辞判定が実際の遷移先で行われるよう、ドットセグメントは解決して返す
  ["/cases/../operator", "/operator"],
  ["/operator/../mypage", "/mypage"],
  // 空のクエリ・フラグメントは URL の直列化で落ちる
  ["/cases?", "/cases"],
  ["/cases#", "/cases"],
];

describe("safeInternalPath", () => {
  describe("外部へ解釈されうる入力・不正値は fallback を返す", () => {
    for (const input of REJECTED_INPUTS) {
      it(`${describeInput(input)} → fallback`, () => {
        assert.equal(safeInternalPath(input, FALLBACK), FALLBACK);
      });
    }
  });

  describe("サイト内パスは正規化して返す", () => {
    for (const [input, expected] of ALLOWED_CASES) {
      it(`${describeInput(input)} → ${describeInput(expected)}`, () => {
        assert.equal(safeInternalPath(input, FALLBACK), expected);
      });
    }
  });

  it("正規化済みの戻り値を再度通しても同じ値になる（冪等）", () => {
    for (const [input] of ALLOWED_CASES) {
      const once = safeInternalPath(input, FALLBACK);
      assert.equal(safeInternalPath(once, FALLBACK), once);
    }
  });

  it("fallback は正規化せずそのまま返す", () => {
    assert.equal(safeInternalPath(null, "/operator"), "/operator");
    assert.equal(safeInternalPath("//evil", "/cases"), "/cases");
  });

  it("どの入力でも、戻り値を遷移先として解釈した結果は同一 origin に留まる", () => {
    const currentOrigin = new URL(CURRENT_LOCATION).origin;
    const inputs = [...REJECTED_INPUTS, ...ALLOWED_CASES.map(([input]) => input)];
    for (const input of inputs) {
      const destination = new URL(safeInternalPath(input, FALLBACK), CURRENT_LOCATION);
      assert.equal(destination.origin, currentOrigin, `input=${describeInput(input)}`);
    }
  });
});
