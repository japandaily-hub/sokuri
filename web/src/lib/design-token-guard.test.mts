/**
 * デザイントークンの旧値ガード（見本 v12 への移行で捨てた値が戻らないようにする）。
 *
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/design-token-guard.test.mts
 * 拡張子を .mts にしている理由は safe-path.test.mts のコメントを参照。
 *
 * 旧テーマ（人の森整合: コバルトブルー・苔色・濃紺・明朝・英字ディスプレイ書体・ピル形ボタン）の直書きが
 * web/src 配下の .css/.tsx/.ts に 0 件であることを固定する。色は katazuke.css :root のトークン
 * （--primary / --primary-rgb / --deep-rgb 等）を参照すること。
 * public-copy-guard.test.mts と違い、コメント内の言及も対象にする（経緯の説明で旧値を書き残すと
 * 次の検索・置換で拾われて紛れ込むため。説明が要るときは「旧コバルト」のように値を書かずに書く）。
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, it } from "node:test";

const SRC_DIR = join(process.cwd(), "src");

/**
 * 旧値の検査パターン [表示名, 正規表現, 理由]。
 * 空白の揺れ（`border-radius: 99px`）も拾うため、値の前後の空白は \s* で許す。
 */
const BANNED: ReadonlyArray<readonly [string, RegExp, string]> = [
  ["#1447e0", /#1447e0/i, "旧コバルトブルー。--primary（#2e4a7d）を参照する"],
  ["#0f37b4", /#0f37b4/i, "旧コバルトの hover。--primary-d を参照する"],
  ["rgba(82,126,82", /rgba\(\s*82\s*,\s*126\s*,\s*82/i, "旧苔色の半透明。rgba(var(--primary-rgb),.x) と書く"],
  ["rgba(20,35,92", /rgba\(\s*20\s*,\s*35\s*,\s*92/i, "旧濃紺の半透明。rgba(var(--deep-rgb),.x) と書く"],
  ["Montserrat", /Montserrat/, "旧英字書体。数字・英字は --num（Inter）"],
  ["Libre_Baskerville", /Libre_Baskerville/, "旧英字ディスプレイ書体"],
  ["Libre Baskerville", /Libre Baskerville/, "旧英字ディスプレイ書体"],
  ["Noto_Serif_JP", /Noto_Serif_JP/, "旧明朝。和文は --maru（見出し）/ --goth（本文）"],
  ["Noto Serif", /Noto Serif/, "旧明朝。和文は --maru（見出し）/ --goth（本文）"],
  ["border-radius:99px", /border-radius:\s*99px/, "ピル形は廃止。角丸は --radius（6px）/ --radius-s（4px）"],
];

/**
 * 除外（src からの相対パス。ディレクトリは配下すべて）。いずれも後続の作業で消える・作り直すため、
 * そのコミットで本リストからも外す（外し忘れても、対象が消えれば検査に影響しない）。
 *  - app/opengraph-image.tsx … OGP 画像（next/og）。CSS 変数が使えず色を直書きするうえ、
 *                             Satori 用の書体指定も絡むため、専用の作業（C11）で作り直す。
 * app/page.tsx・app/top.css（トップ）は作り直し済みで旧値が無いため除外しない。
 */
const EXCLUDED: readonly string[] = ["app/opengraph-image.tsx"];

/** 検査対象の拡張子（テストファイル自身は旧値を文字列として含むため除く） */
const TARGET_EXTENSIONS = [".css", ".tsx", ".ts"] as const;

/** POSIX 形式の相対パス（Windows の区切りを / に揃える）。 */
function toPosix(relPath: string): string {
  return relPath.split(sep).join("/");
}

function isExcluded(relPath: string): boolean {
  return EXCLUDED.some((entry) => (entry.endsWith("/") ? relPath.startsWith(entry) : relPath === entry));
}

/** src 配下の対象ファイル（POSIX 相対パス）を再帰で集める。 */
function collectTargetFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const abs = join(dir, entry);
    const stat = statSync(abs);
    if (stat.isDirectory()) {
      out.push(...collectTargetFiles(abs));
      continue;
    }
    if (!TARGET_EXTENSIONS.some((ext) => entry.endsWith(ext))) continue;
    if (/\.test\.[cm]?[jt]s$/.test(entry)) continue;
    const relPath = toPosix(relative(SRC_DIR, abs));
    if (!isExcluded(relPath)) out.push(relPath);
  }
  return out.sort();
}

const TARGET_FILES = collectTargetFiles(SRC_DIR);

describe("デザイントークンの旧値が残っていない", () => {
  it("検査対象のファイルを拾えている（走査の空振りで常時成功にならない）", () => {
    assert.ok(TARGET_FILES.length > 50, `対象 ${TARGET_FILES.length} 件`);
    assert.ok(TARGET_FILES.includes("app/katazuke.css"));
    assert.ok(TARGET_FILES.includes("app/layout.tsx"));
  });

  it("除外は opengraph-image.tsx だけで、走査に入らない", () => {
    assert.equal(TARGET_FILES.includes("app/opengraph-image.tsx"), false);
  });

  for (const [label, pattern, reason] of BANNED) {
    it(`「${label}」が 0 件（${reason}）`, () => {
      const hits: string[] = [];
      for (const relPath of TARGET_FILES) {
        const lines = readFileSync(join(SRC_DIR, relPath), "utf8").split(/\r?\n/);
        lines.forEach((line, index) => {
          if (pattern.test(line)) hits.push(`${relPath}:${index + 1}`);
        });
      }
      assert.deepEqual(hits, []);
    });
  }
});
