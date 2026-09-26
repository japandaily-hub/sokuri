/**
 * backend-api-base（バックエンド API 接続先解決）の回帰テスト。
 *
 * 実行（cwd は web）: node --test src/lib/backend-api-base.test.mts
 * Node 24 の組み込みテストランナーと既定有効の型除去（type stripping）だけで動かす
 * （npm 依存は追加しない）。
 *
 * 拡張子を .mts にしている理由は safe-path.test.mts のコメントを参照
 * （tsconfig の include に一致させず、アプリの型検査・ビルドの対象から外したまま実行する）。
 */
import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { BackendApiBaseCandidate } from "./backend-api-base.ts";
import {
  BackendApiBaseNotConfiguredError,
  PRODUCTION_FALLBACK_API_BASE,
  publicBackendApiBase,
  resolveBackendApiBase,
  serverBackendApiBase,
} from "./backend-api-base.ts";

const API_URL_CANDIDATE = "API_URL";
const NEXT_PUBLIC_API_URL_CANDIDATE = "NEXT_PUBLIC_API_URL";

/** テスト名・失敗時メッセージの表示用（undefined と空文字・空白を見分けられるようにする）。 */
function describeValue(value: string | undefined): string {
  return value === undefined ? "undefined" : JSON.stringify(value);
}

describe("resolveBackendApiBase", () => {
  describe("設定値があればそれを使う（末尾スラッシュ・前後の空白を正規化する）", () => {
    const cases: ReadonlyArray<readonly [input: string, expected: string]> = [
      ["http://localhost:8000/api/v1", "http://localhost:8000/api/v1"],
      ["http://localhost:8000/api/v1/", "http://localhost:8000/api/v1"],
      ["http://localhost:8000/api/v1///", "http://localhost:8000/api/v1"],
      ["  http://localhost:8000/api/v1  ", "http://localhost:8000/api/v1"],
      ["\n http://localhost:8000/api/v1 \n", "http://localhost:8000/api/v1"],
    ];
    for (const [input, expected] of cases) {
      for (const nodeEnv of ["development", "production"]) {
        it(`${describeValue(input)}（nodeEnv=${nodeEnv}）→ ${expected}`, () => {
          const candidates: readonly BackendApiBaseCandidate[] = [
            { envVarName: NEXT_PUBLIC_API_URL_CANDIDATE, value: input },
          ];
          assert.equal(resolveBackendApiBase(candidates, nodeEnv), expected);
        });
      }
    }
  });

  it("空の候補（undefined・\"\"・空白のみ）は飛ばして次の候補を使う", () => {
    const emptyValues: ReadonlyArray<string | undefined> = [undefined, "", "   "];
    for (const emptyValue of emptyValues) {
      const candidates: readonly BackendApiBaseCandidate[] = [
        { envVarName: API_URL_CANDIDATE, value: emptyValue },
        { envVarName: NEXT_PUBLIC_API_URL_CANDIDATE, value: "http://localhost:8000/api/v1" },
      ];
      assert.equal(
        resolveBackendApiBase(candidates, "development"),
        "http://localhost:8000/api/v1",
        `empty value=${describeValue(emptyValue)}`,
      );
    }
  });

  it("先頭の候補が優先される", () => {
    const candidates: readonly BackendApiBaseCandidate[] = [
      { envVarName: API_URL_CANDIDATE, value: "http://localhost:9000/api/v1" },
      { envVarName: NEXT_PUBLIC_API_URL_CANDIDATE, value: "http://localhost:8000/api/v1" },
    ];
    assert.equal(resolveBackendApiBase(candidates, "development"), "http://localhost:9000/api/v1");
  });

  it("production で全て未設定なら PRODUCTION_FALLBACK_API_BASE を返す", () => {
    const candidates: readonly BackendApiBaseCandidate[] = [
      { envVarName: API_URL_CANDIDATE, value: undefined },
      { envVarName: NEXT_PUBLIC_API_URL_CANDIDATE, value: "" },
    ];
    assert.equal(resolveBackendApiBase(candidates, "production"), PRODUCTION_FALLBACK_API_BASE);
  });

  describe("本番ビルドでなく全て未設定なら例外を投げてログを残す", () => {
    const nonProductionNodeEnvs: ReadonlyArray<string | undefined> = [
      "development",
      "test",
      undefined,
      "",
      "Production", // 表記ゆれは本番扱いにしない（完全一致。backend-api-base.ts 参照）
      " production", // 前後に空白が付いた場合も同様
    ];
    for (const nodeEnv of nonProductionNodeEnvs) {
      it(`nodeEnv=${describeValue(nodeEnv)} → BackendApiBaseNotConfiguredError`, (t) => {
        const errorMock = t.mock.method(console, "error", () => {});
        const candidates: readonly BackendApiBaseCandidate[] = [
          { envVarName: API_URL_CANDIDATE, value: undefined },
          { envVarName: NEXT_PUBLIC_API_URL_CANDIDATE, value: "   " },
        ];

        let thrownMessage = "";
        assert.throws(
          () => resolveBackendApiBase(candidates, nodeEnv),
          (error: unknown) => {
            assert.ok(error instanceof BackendApiBaseNotConfiguredError);
            thrownMessage = error.message;
            return true;
          },
        );
        // 参照した環境変数名が優先順にすべて並ぶこと（/API_URL/ だけでは NEXT_PUBLIC_API_URL にも一致してしまう）。
        assert.ok(
          thrownMessage.includes("（API_URL / NEXT_PUBLIC_API_URL）"),
          `message=${JSON.stringify(thrownMessage)}`,
        );

        assert.equal(errorMock.mock.callCount(), 1);
        const loggedArgs = errorMock.mock.calls[0]?.arguments ?? [];
        assert.equal(loggedArgs.length, 1);
        const loggedMessage = loggedArgs[0];
        assert.ok(typeof loggedMessage === "string" && loggedMessage.includes(thrownMessage));
      });
    }
  });
});

describe("serverBackendApiBase / publicBackendApiBase", () => {
  const ENV_KEYS = ["API_URL", "NEXT_PUBLIC_API_URL", "NODE_ENV"] as const;
  type EnvKey = (typeof ENV_KEYS)[number];
  // beforeEach で退避して未設定にし、afterEach で元の値に戻す。process.env に undefined を
  // 代入すると文字列 "undefined" になってしまうため、未設定にするときは必ず delete を使う。
  const savedEnv: Partial<Record<EnvKey, string>> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      const current = process.env[key];
      if (current !== undefined) savedEnv[key] = current;
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      const saved = savedEnv[key];
      if (saved === undefined) delete process.env[key];
      else process.env[key] = saved;
      delete savedEnv[key];
    }
  });

  it("server は API_URL を NEXT_PUBLIC_API_URL より優先する", () => {
    process.env.NODE_ENV = "development";
    process.env.API_URL = "http://localhost:9000/api/v1";
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000/api/v1";
    assert.equal(serverBackendApiBase(), "http://localhost:9000/api/v1");
  });

  it("server は API_URL 未設定なら NEXT_PUBLIC_API_URL を使う", () => {
    process.env.NODE_ENV = "development";
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000/api/v1";
    assert.equal(serverBackendApiBase(), "http://localhost:8000/api/v1");
  });

  it("public は API_URL を見ない（API_URL だけ設定・development なら例外）", (t) => {
    t.mock.method(console, "error", () => {});
    process.env.NODE_ENV = "development";
    process.env.API_URL = "http://localhost:9000/api/v1";
    assert.throws(() => publicBackendApiBase(), BackendApiBaseNotConfiguredError);
  });

  it("両方とも development で未設定なら例外（本番 URL を返さない）", (t) => {
    t.mock.method(console, "error", () => {});
    process.env.NODE_ENV = "development";
    assert.throws(() => serverBackendApiBase(), BackendApiBaseNotConfiguredError);
    assert.throws(() => publicBackendApiBase(), BackendApiBaseNotConfiguredError);
  });

  it("production で未設定ならフォールバックを返す", () => {
    process.env.NODE_ENV = "production";
    assert.equal(serverBackendApiBase(), PRODUCTION_FALLBACK_API_BASE);
    assert.equal(publicBackendApiBase(), PRODUCTION_FALLBACK_API_BASE);
  });
});
