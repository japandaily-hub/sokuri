/**
 * local-target（E2E 接続先のローカル検査）の回帰テスト。
 *
 * 実行（cwd は web）: node --test e2e/helpers/local-target.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。拡張子を .mts にしている理由は src/lib/safe-path.test.mts の
 * コメントを参照（tsconfig の include に一致させず、型検査の対象から外したまま実行する）。
 * 加えて playwright.config.ts の testMatch を "**\/*.spec.ts" に絞っているため、このファイルは
 * Playwright の収集対象にもならない（既定の testMatch は *.test.* も拾ってしまう）。
 * node --test 専用なので @playwright/test は import しない（web/eslint.config.mjs の e2e 向けの
 * 制限は *.ts が対象で .mts には掛からないため、ここは慣習で守る）。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { E2ETarget } from "./local-target.ts";
import {
  ALLOW_REMOTE_ENV,
  assertLocalTarget,
  assertLocalTargets,
  describeTargetOrigins,
  isRemoteTargetAllowed,
} from "./local-target.ts";

/** assert.throws の第2引数用: Error であることと、message が全ての部分文字列を含むことを見る。 */
function messageIncludes(...parts: readonly string[]): (error: unknown) => boolean {
  return (error: unknown) => {
    assert.ok(error instanceof Error, `Error ではない: ${String(error)}`);
    for (const part of parts) {
      assert.ok(error.message.includes(part), `message=${JSON.stringify(error.message)} に ${JSON.stringify(part)} を含まない`);
    }
    return true;
  };
}

describe("assertLocalTarget", () => {
  describe("ローカルスタックは通す", () => {
    const passUrls: readonly string[] = [
      "http://localhost:3100",
      "https://localhost",
      "http://127.0.0.1:8000/api/v1",
      "http://[::1]:3100",
      "http://LOCALHOST:3100", // URL の解釈で小文字化される
      "http://0x7f.1:8000", // 16進・短縮 IPv4 も 127.0.0.1 に正規化される
    ];
    for (const url of passUrls) {
      it(`${url} は通る`, () => {
        assert.doesNotThrow(() => assertLocalTarget({ label: "対象", url }));
      });
    }
  });

  describe("許可リスト外は origin を含めて止める", () => {
    const blockedUrls: readonly string[] = [
      "http://remote.invalid:3100",
      "http://localhost.:3100", // 末尾ドット。URL は "localhost." のまま保持し "localhost" と一致しない
      "http://127.0.0.2",
      "http://0.0.0.0:3100",
      "http://app.localhost:3100",
      "http://localhost@remote.invalid", // "localhost" は userinfo。実ホストは remote.invalid
      "http://[::ffff:127.0.0.1]", // IPv4 射影は "[::1]" に正規化されないため許可リスト外
    ];
    for (const url of blockedUrls) {
      it(`${url} は止まる（${new URL(url).origin} を含む）`, () => {
        const origin = new URL(url).origin;
        assert.throws(
          () => assertLocalTarget({ label: "対象", url }),
          messageIncludes("がローカルではありません", origin),
        );
      });
    }
  });

  it("認証情報・パス・クエリはメッセージに出さない（実ホストの origin だけ出す）", () => {
    const url = "http://user:s3cret@remote.invalid/path?token=abc";
    assert.throws(() => assertLocalTarget({ label: "対象", url }), (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.ok(!error.message.includes("s3cret"), error.message);
      assert.ok(!error.message.includes("token"), error.message);
      assert.ok(!error.message.includes("/path"), error.message);
      assert.ok(error.message.includes("http://remote.invalid"), error.message);
      return true;
    });
  });

  it("URL として解釈できない値は値そのものをメッセージに含めない", () => {
    const url = "not-a-url";
    assert.throws(() => assertLocalTarget({ label: "対象", url }), (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.ok(!error.message.includes(url));
      assert.ok(error.message.includes("URL として解釈できません"));
      return true;
    });
  });

  describe("http(s) 以外のスキームは専用の文言で止める", () => {
    // "localhost:8000/..." はスキーム省略のつもりが "localhost:" スキームの URL に解釈され、
    // origin が "null" になる（環境変数に http:// を書き忘れたケースを想定）。
    const nonHttpUrls: readonly string[] = ["localhost:8000/api/v1", "ftp://localhost"];
    for (const url of nonHttpUrls) {
      it(`${url} は http(s) の文言で止まる`, () => {
        assert.throws(
          () => assertLocalTarget({ label: "対象", url }),
          messageIncludes("http:// か https://"),
        );
      });
    }
  });
});

describe("assertLocalTargets", () => {
  const remoteTarget: E2ETarget = { label: "E2E_BASE_URL", url: "http://remote.invalid" };

  it(`env.${ALLOW_REMOTE_ENV} が "1" 完全一致なら遠隔でも通る`, () => {
    assert.doesNotThrow(() => assertLocalTargets([remoteTarget], { [ALLOW_REMOTE_ENV]: "1" }));
  });

  describe('"1" 以外（表記ゆれ・未設定）は止める', () => {
    const nonExactValues: ReadonlyArray<[name: string, value: string | undefined]> = [
      ['"true"', "true"],
      ['" 1"', " 1"],
      ['"0"', "0"],
      ['""', ""],
      ["未設定", undefined],
    ];
    for (const [name, value] of nonExactValues) {
      it(`${name} は止まる`, () => {
        const env = value === undefined ? {} : { [ALLOW_REMOTE_ENV]: value };
        assert.throws(() => assertLocalTargets([remoteTarget], env));
      });
    }
  });

  it("複数件のうち1件でも許可リスト外なら止める", () => {
    const targets: readonly E2ETarget[] = [
      { label: "E2E_BASE_URL", url: "http://localhost:3100" },
      { label: "E2E_API_URL", url: "http://remote.invalid:8000" },
    ];
    assert.throws(() => assertLocalTargets(targets, {}), messageIncludes("E2E_API_URL"));
  });
});

describe("isRemoteTargetAllowed", () => {
  it('"1" 完全一致のときだけ true', () => {
    assert.equal(isRemoteTargetAllowed({ [ALLOW_REMOTE_ENV]: "1" }), true);
  });

  it("表記ゆれ・未設定は false", () => {
    const nonExactValues: ReadonlyArray<string | undefined> = ["true", " 1", "1 ", "0", "", undefined];
    for (const value of nonExactValues) {
      assert.equal(isRemoteTargetAllowed({ [ALLOW_REMOTE_ENV]: value }), false, `value=${JSON.stringify(value)}`);
    }
  });
});

describe("describeTargetOrigins", () => {
  it("origin だけを label=origin の形で「、」区切りにする（パス・クエリ・userinfo は含めない）", () => {
    const targets: readonly E2ETarget[] = [
      { label: "E2E_BASE_URL", url: "http://localhost:3100" },
      { label: "E2E_API_URL", url: "http://user:s3cret@remote.invalid/path?token=abc" },
    ];
    const described = describeTargetOrigins(targets);
    assert.equal(described, "E2E_BASE_URL=http://localhost:3100、E2E_API_URL=http://remote.invalid");
    assert.ok(!described.includes("s3cret"));
    assert.ok(!described.includes("token"));
    assert.ok(!described.includes("/path"));
  });

  it("URL として解釈できない値は「解釈できない値」と表示する", () => {
    const targets: readonly E2ETarget[] = [{ label: "E2E_BASE_URL", url: "not-a-url" }];
    assert.equal(describeTargetOrigins(targets), "E2E_BASE_URL=（解釈できない値）");
  });
});
