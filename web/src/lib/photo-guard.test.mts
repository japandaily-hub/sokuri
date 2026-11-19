/**
 * 手持ちの生成写真の使い方ガード（顔の写る人物写真・3D アイコン・水彩イラストを戻さない）。
 *
 * 実行（cwd は web）: node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON "src/**\/*.test.mts"
 * 拡張子を .mts にしている理由は safe-path.test.mts のコメントを参照。
 *
 * 方針（ペルソナ相談で決定）:
 *  1. 顔がはっきり写る人物写真は使わない（景表法: 実在の利用者・スタッフ・業者に見える）。
 *  2. 3D アイコン（/img/real/）と水彩イラスト（/img/ill/・/img/lp/deco/）は全廃。
 *  3. 文字を写真に重ねない・同じ色調補正（.kdz-photo）を使う。
 * design-token-guard.test.mts と同じく、コメント内の言及も対象にする（経緯の説明で旧ファイル名を
 * 書き残すと次の検索・置換で拾われるため。説明が要るときは「旧 3D アイコン」のようにパスを書かずに書く）。
 */
import { CASES, VENDOR_CASES } from "./model-cases.ts";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, it } from "node:test";

const SRC_DIR = join(process.cwd(), "src");
const PUBLIC_DIR = join(process.cwd(), "public");

/** 参照が 0 件であるべき文字列 [表示名, 理由]。部分一致で検査する。 */
const BANNED: ReadonlyArray<readonly [string, string]> = [
  ["staff-m30", "顔の写る人物写真（スタッフ）"],
  ["staff-w20", "顔の写る人物写真（スタッフ）"],
  ["staff-w40", "顔の写る人物写真（スタッフ）"],
  ["founder-new", "顔の写る人物写真（運営者）"],
  ["/img/story-", "顔の写る人物写真（体験談）"],
  ["/img/worry-", "顔の写る人物写真（お悩み）"],
  ["/img/p-", "顔の写る人物写真（ペルソナ）"],
  ["v2/vc-", "業者の肖像（顔）"],
  ["v2/mc-", "モデルケースの肖像（顔）"],
  ["v2/li-side", "ログインの顔写真"],
  ["v2/su-side", "新規登録の顔写真"],
  ["v2/ol-side", "業者ログインの顔写真"],
  ["v2/os-side", "業者登録の顔写真"],
  ["v2/faq-band", "よくある質問の顔写真の帯"],
  ["v2/biz-hero", "業者向けページの顔写真"],
  ["v2/admin-hero", "運営の顔写真"],
  ["top-hero-couple-60s", "顔の写る人物写真（ヒーローのカルーセル）"],
  ["top-hero-couple-child", "顔の写る人物写真（ヒーローのカルーセル）"],
  ["top-hero-man-20s", "顔の写る人物写真（ヒーローのカルーセル）"],
  ["top-hero-person", "顔の写る人物写真（ヒーロー）"],
  ["top-hero-woman-20s", "顔の写る人物写真（ヒーローのカルーセル）"],
  ["top-founder-desk", "運営者の人物写真"],
  ["v2/undefined", "画像 id が未定義のまま組み立てられた URL（404）"],
  ["/img/ill/", "水彩イラストは全廃"],
  ["/img/lp/deco/", "水彩イラストは全廃"],
  ["/img/real/", "3D アイコンは全廃"],
];

const TARGET_EXTENSIONS = [".css", ".tsx", ".ts"] as const;
/** テストファイル自身は禁止語を文字列として含むため除く。 */
const isTestFile = (name: string) => name.endsWith(".test.mts") || name.endsWith(".test.ts");

function toPosix(relPath: string): string {
  return relPath.split(sep).join("/");
}

function collectFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      collectFiles(full, out);
    } else if (TARGET_EXTENSIONS.some((ext) => name.endsWith(ext)) && !isTestFile(name)) {
      out.push(full);
    }
  }
  return out;
}

const FILES = collectFiles(SRC_DIR).map((full) => ({
  rel: toPosix(relative(SRC_DIR, full)),
  text: readFileSync(full, "utf8"),
}));

describe("photo-guard: 顔写真・3D アイコン・水彩イラストの参照が src 配下に無い", () => {
  it("走査対象が空でない（検査が空振りしていない）", () => {
    assert.ok(FILES.length > 50, `走査対象が少なすぎる: ${FILES.length}`);
  });

  for (const [needle, reason] of BANNED) {
    it(`「${needle}」の参照が 0 件（${reason}）`, () => {
      const hits = FILES.filter((f) => f.text.includes(needle)).map((f) => f.rel);
      assert.deepEqual(hits, [], `${needle} を参照しているファイル: ${hits.join(", ")}`);
    });
  }
});

describe("photo-guard: 写真の参照が実在し、共通の色調補正が定義されている", () => {
  it("静的な /img/ 参照のファイルが public に存在する（テンプレート式は除く）", () => {
    const missing: string[] = [];
    for (const f of FILES) {
      for (const m of f.text.matchAll(/["'`(](\/img\/[A-Za-z0-9_\-./]+\.(?:webp|png|jpg|jpeg|svg))/g)) {
        if (!existsSync(join(PUBLIC_DIR, m[1]))) missing.push(`${f.rel}: ${m[1]}`);
      }
    }
    assert.deepEqual(missing, []);
  });

  it(".kdz-photo は top.css の .tp-photo と同じ色調補正と角丸を持つ", () => {
    const css = FILES.find((f) => f.rel === "app/katazuke.css")?.text ?? "";
    assert.match(css, /\.kdz-photo img\{[^}]*filter:saturate\(\.8\) contrast\(\.96\) sepia\(\.06\)/);
    assert.match(css, /\.kdz-photo img\{[^}]*border-radius:var\(--radius\)/);
  });
});

describe("photo-guard: モデルケースに人物の肖像・仮名・一人称の引用が無い", () => {
  it("依頼者ケースの lot が public/img/v2 に実在する", () => {
    for (const c of CASES) {
      assert.ok(existsSync(join(PUBLIC_DIR, "img", "v2", `${c.lot}.webp`)), `lot が存在しない: ${c.lot}`);
    }
  });

  it("依頼者ケースは仮名・アバター・一人称の引用（name/avatar/quote）を持たない", () => {
    for (const c of CASES) {
      for (const key of ["name", "avatar", "quote", "quoteShort", "portrait", "portraitAlt", "thumbs"]) {
        assert.ok(!(key in c), `CaseItem に ${key} が残っている (id:${c.id})`);
      }
      assert.ok(c.point.length > 0);
    }
  });

  it("業者ケースは speaker（肩書・年代）・quote・portrait を持たず、point を持つ", () => {
    for (const v of VENDOR_CASES) {
      for (const key of ["speaker", "quote", "portrait", "portraitAlt"]) {
        assert.ok(!(key in v), `VendorCase に ${key} が残っている (${v.id})`);
      }
      assert.ok(v.point.length > 0);
    }
  });
});
