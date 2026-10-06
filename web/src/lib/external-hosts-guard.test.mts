/**
 * 外部ホストとプライバシーポリシー第5条の一致ガード（2026-10-06 法務・表記レビュー M-1）。
 *
 * 実行（cwd は web）: node --experimental-strip-types --test src/lib/external-hosts-guard.test.mts
 * 拡張子を .mts にしている理由は safe-path.test.mts のコメントを参照。
 *
 * 目的: web のコードが通信する外部ホストを足したのに /privacy 第5条の一覧を直し忘れる（または
 * 機能を外したのに一覧に残る）ことを防ぐ。src 配下の .ts/.tsx（テストを除く）からコメント行を除いて
 * `https://ホスト` を集め、下の KNOWN_HOSTS と突き合わせる。
 *
 * - KNOWN_HOSTS に無いホストがコードに現れたら失敗する → /privacy 第5条（PROCESSORS）に行を足し、
 *   ここにも登録する（通信しない識別子などは vendor を null にして理由を書く）。
 * - KNOWN_HOSTS にあるのにコードから消えたホストも失敗する（一覧の陳腐化）。
 * - browserDirect のホスト（利用者のブラウザが直接呼ぶもの）は、privacy/page.tsx のコメント行
 *   「external-hosts: …」と完全に一致させる。
 *
 * 簡易検査のため、コメント内の URL（経緯・参考リンク）は対象外。backend が呼ぶ外部サービス
 * （Gemini・Brevo・R2・Webhook）はこのテストの範囲外で、privacy/page.tsx の PROCESSORS のコメントで管理する。
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, it } from "node:test";

const SRC_DIR = join(process.cwd(), "src");
const PRIVACY_PAGE = join(SRC_DIR, "app", "privacy", "page.tsx");

interface KnownHost {
  /** /privacy 第5条に載っている事業者名（本文にこの文字列があること）。通信が発生しないものは null。 */
  readonly vendor: string | null;
  /** 利用者のブラウザから直接呼ぶか（true なら privacy の「external-hosts:」行に載せる）。 */
  readonly browserDirect: boolean;
  /** 登録の理由（どこで何のために使うか）。 */
  readonly reason: string;
}

const KNOWN_HOSTS: Readonly<Record<string, KnownHost>> = {
  "zipcloud.ibsnet.co.jp": {
    vendor: "株式会社アイビス（zipcloud）",
    browserDirect: true,
    reason: "lib/postal-lookup.ts の郵便番号検索（入力された郵便番号を送る）",
  },
  "bank.teraren.com": {
    vendor: "合同会社テラレン（銀行くん）",
    browserDirect: true,
    reason: "lib/bank-lookup.ts の銀行名・支店名の候補検索（入力中の銀行名・支店名を送る）",
  },
  "access.line.me": {
    vendor: "LINEヤフー株式会社",
    browserDirect: false,
    reason: "lib/line-link.ts の LINE 連携の認可画面（ブラウザの遷移先。LINE の行で記載済み）",
  },
  "api.line.me": {
    vendor: "LINEヤフー株式会社",
    browserDirect: false,
    reason: "lib/line-link.ts のトークン交換（Vercel のサーバーから呼ぶ）",
  },
  "sokuri-backend.onrender.com": {
    vendor: "Render Services, Inc.",
    browserDirect: false,
    reason: "lib/backend-api-base.ts の本番 API（運営者のサーバー。Render の行で記載済み）",
  },
  "sokuri.vercel.app": {
    vendor: "Vercel Inc.",
    browserDirect: false,
    reason: "サイト自身の URL（seo・robots・sitemap・layout）",
  },
  "schema.org": {
    vendor: null,
    browserDirect: false,
    reason: "layout.tsx の構造化データの @context の識別子で、通信は発生しない",
  },
  "internal.invalid": {
    vendor: null,
    browserDirect: false,
    reason: "lib/safe-path.ts の相対パス解釈用の基準 URL（予約 TLD .invalid。通信は発生しない）",
  },
};

function collectSourceFiles(dirAbs: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dirAbs)) {
    const childAbs = join(dirAbs, entry);
    if (statSync(childAbs).isDirectory()) {
      out.push(...collectSourceFiles(childAbs));
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\./.test(entry)) {
      out.push(childAbs);
    }
  }
  return out;
}

/** コメント行（// ・ * ・ /* ・ {/* で始まる行）を除いた本文（public-copy-guard と同じ規則）。 */
function codeWithoutComments(absPath: string): string {
  return readFileSync(absPath, "utf8")
    .split(/\r?\n/)
    .filter((line) => !/^\s*(\/\/|\*|\/\*|\{\/\*)/.test(line))
    .join("\n");
}

const HOST_RE = /https:\/\/([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)/gi;

/** ホスト → それが現れたファイル（src からの相対パス）。 */
function hostsInCode(): Map<string, Set<string>> {
  const found = new Map<string, Set<string>>();
  for (const abs of collectSourceFiles(SRC_DIR)) {
    const rel = relative(SRC_DIR, abs).split(sep).join("/");
    for (const match of codeWithoutComments(abs).matchAll(HOST_RE)) {
      const host = match[1].toLowerCase();
      if (!found.has(host)) found.set(host, new Set());
      found.get(host)!.add(rel);
    }
  }
  return found;
}

/** privacy/page.tsx の「external-hosts: a b」行に書かれたホスト。 */
function declaredBrowserHosts(): string[] {
  const raw = readFileSync(PRIVACY_PAGE, "utf8");
  const lines = raw.split(/\r?\n/).filter((line) => /external-hosts:/.test(line));
  assert.equal(lines.length, 1, "privacy/page.tsx に「external-hosts:」の行がちょうど1行あること");
  const list = lines[0].split("external-hosts:")[1].replace(/\*\/.*$/, "").trim();
  return list.split(/\s+/).filter(Boolean).sort();
}

describe("外部ホストと /privacy 第5条の一致（M-1）", () => {
  const found = hostsInCode();
  const privacyBody = codeWithoutComments(PRIVACY_PAGE);

  it("走査が空振りしていない（郵便番号・銀行検索の URL を拾えている）", () => {
    assert.ok(found.has("zipcloud.ibsnet.co.jp"), "postal-lookup.ts の URL を拾えていない");
    assert.ok(found.has("bank.teraren.com"), "bank-lookup.ts の URL を拾えていない");
  });

  it("コードに現れる外部ホストは、すべて登録済み（未登録なら /privacy 第5条と KNOWN_HOSTS に足す）", () => {
    const unknown = [...found.keys()]
      .filter((host) => !(host in KNOWN_HOSTS))
      .map((host) => `${host}（${[...found.get(host)!].join(", ")}）`);
    assert.deepEqual(unknown, []);
  });

  it("登録済みのホストは、コードに今も現れる（使わなくなったら一覧からも外す）", () => {
    const stale = Object.keys(KNOWN_HOSTS).filter((host) => !found.has(host));
    assert.deepEqual(stale, []);
  });

  for (const [host, info] of Object.entries(KNOWN_HOSTS)) {
    if (info.vendor === null) continue;
    it(`${host}: /privacy の本文に事業者名「${info.vendor}」がある（${info.reason}）`, () => {
      assert.ok(privacyBody.includes(info.vendor!), info.vendor!);
    });
  }

  it("ブラウザが直接呼ぶホストと、privacy/page.tsx の「external-hosts:」行が一致する", () => {
    const expected = Object.entries(KNOWN_HOSTS)
      .filter(([, info]) => info.browserDirect)
      .map(([host]) => host)
      .sort();
    assert.deepEqual(declaredBrowserHosts(), expected);
  });

  it("Cloudflare R2 の行は品物の写真だけを書く（書類画像はデータベースに保存）", () => {
    const r2Line = privacyBody.split("\n").find((line) => line.includes("Cloudflare, Inc.（R2）"));
    assert.ok(r2Line, "R2 の行が見つからない");
    assert.ok(r2Line.includes("品物の写真の保存"), r2Line);
    assert.equal(r2Line.includes("書類画像の保存"), false, r2Line);
  });

  it("Gemini を「業務の委託」と断定しない（H-1。区分は弁護士確認前の暫定表記）", () => {
    assert.equal(privacyBody.includes("外部サービスの利用（業務の委託）"), false);
    assert.ok(privacyBody.includes("Gemini API に、品物の写真（位置情報などは除去済み）を送信します"));
    assert.ok(privacyBody.includes("弁護士の確認前の暫定表記"));
  });
});
