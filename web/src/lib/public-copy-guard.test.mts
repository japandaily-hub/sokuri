/**
 * 公開ページの表記ガード（2026-10-06 の表記・法務監査で直した表現が戻らないようにする）。
 *
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/public-copy-guard.test.mts
 * 拡張子を .mts にしている理由は safe-path.test.mts のコメントを参照。
 *
 * ソースの文字列を直接読む簡易な検査。コメント内の言及（「〜を削った」等の経緯）まで拾うと
 * 誤検知になるため、行コメント・ブロックコメントの行は除いてから照合する。
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

const APP_DIR = join(process.cwd(), "src", "app");

/** 公開ページ・共通表記（このテストの対象）。 */
const PUBLIC_FILES = [
  "page.tsx",
  "layout.tsx",
  "faq/page.tsx",
  "company/page.tsx",
  "contact/page.tsx",
  "legal/page.tsx",
  "privacy/page.tsx",
  "terms/page.tsx",
  "terms/TermsTabs.tsx",
  "photo-guide/page.tsx",
  "examples/page.tsx",
  "examples/layout.tsx",
  "business/page.tsx",
  "vendors/page.tsx",
  "verify-email/page.tsx",
  "lp/_components/LpChrome.tsx",
] as const;

/** コメント行（// ・ * ・ /* ・ {/* で始まる行）を除いた本文。 */
function codeWithoutComments(relPath: string): string {
  const raw = readFileSync(join(APP_DIR, relPath), "utf8");
  return raw
    .split(/\r?\n/)
    .filter((line) => !/^\s*(\/\/|\*|\/\*|\{\/\*)/.test(line))
    .join("\n");
}

/** [禁止する表現, 理由, 対象を絞る場合のファイル] */
const BANNED: ReadonlyArray<readonly [string, string, readonly string[]?]> = [
  ["第58条の2", "M-5: 業務提供誘引販売の条文で、本サービスと無関係"],
  ["定期的なセキュリティ監査", "C-4: 個人事業の実態と合わない（実施していない措置は書かない）"],
  ["従業員への個人情報保護教育", "C-4: 同上"],
  // contact の入力欄の「例）」プレースホルダは対象外（確認済みのアドレスとして表示しているのは verify-email だけ）
  ["example@email.com", "H-1: ダミーのアドレスを確認済みとして出さない", ["verify-email/page.tsx"]],
  ["成約後に業者からご案内", "H-2/方針①: 代金の流れ（誰が案内するか）を断定しない"],
  // 利用規約の「利用をもって同意」は契約の成立の論点で別扱い（ここではお問い合わせだけを見る）
  ["同意したものとみなします", "M-8: お問い合わせはチェックで明示的に同意を得る", ["contact/page.tsx"]],
  ["値がつかない物も、まとめて", "H-8: 廃棄物の無許可収集を誘う恐れ"],
  ["値がつかない物まで引き取り", "H-8: 同上"],
  ["高くなりやすい", "M-2: 根拠を示せない効果表現"],
  ["買い取ってもらえることが多い", "M-2: 同上"],
  ["5分で完了", "M-2: 同上"],
  ["登録時・取引前に確認", "H-5: 取引前に確認する実装はない"],
  ["中古品として再流通します", "M-3: 再流通の断定"],
  ["会社概要", "M-4: 個人事業のため「運営者情報」"],
  ["家具・家電等は対象外", "M-6: クーリング・オフの対象外物品を簡略化して断定しない"],
  ["「当社」", "M-4: 個人事業のため「運営者」"],
];

describe("公開ページに禁止表現が残っていない", () => {
  for (const file of PUBLIC_FILES) {
    const body = codeWithoutComments(file);
    for (const [phrase, reason, only] of BANNED) {
      if (only && !only.includes(file)) continue;
      it(`${file}: 「${phrase}」を含まない（${reason}）`, () => {
        assert.equal(body.includes(phrase), false);
      });
    }
  }
});

describe("必須の表記がある", () => {
  it("/verify-email は URL の ?email= を読まない（任意の文字列を公式画面に出さない）", () => {
    assert.equal(codeWithoutComments("verify-email/page.tsx").includes('get("email")'), false);
  });

  it("/verify-email・/forbidden・/login・/signup・/unsubscribe は noindex", () => {
    for (const file of [
      "verify-email/layout.tsx",
      "forbidden/page.tsx",
      "login/layout.tsx",
      "signup/layout.tsx",
      "unsubscribe/layout.tsx",
    ]) {
      assert.match(codeWithoutComments(file), /robots:\s*\{\s*index:\s*false/, file);
    }
  });

  it("プライバシーポリシーに外部サービス・外国にある事業者の条がある（C-3）", () => {
    const body = codeWithoutComments("privacy/page.tsx");
    for (const needle of ["外国にある事業者", "Google LLC", "米国", "Sendinblue SAS", "フランス"]) {
      assert.ok(body.includes(needle), needle);
    }
  });

  it("訪問時の本人確認の注記が、氏名・電話を渡さない旨と同じ場所にある（H-4）", () => {
    for (const file of ["page.tsx", "company/page.tsx", "privacy/page.tsx"]) {
      assert.ok(codeWithoutComments(file).includes("業者が法令に基づき本人確認をする場合があります"), file);
    }
  });

  it("構造化データのロゴは存在するファイル（/icon.png）を指す（M-10）", () => {
    const body = codeWithoutComments("layout.tsx");
    assert.ok(body.includes("/icon.png"));
    assert.equal(body.includes("/icon.svg"), false);
  });
});
