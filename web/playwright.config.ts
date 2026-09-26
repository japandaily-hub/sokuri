/**
 * Playwright（E2E スモーク）の設定。
 *
 * 対象はローカルスタックのみ（本番には決して向けないこと）。接続先の検査は4段構えで、
 * ここ（設定ファイルの読み込み時・defineConfig の前）が主防御。ここで throw すれば
 * ワーカーを1つも起動しない（beforeAll・afterAll も一切走らない）。残り3段
 * （worker fixture・context 生成・API クライアント生成）は e2e/helpers/local-target.ts の
 * 冒頭コメントを参照。サーバーの起動はこのファイルでは行わない（webServer 未使用）。
 * バックエンド・フロントは docs/ops/e2e.md の手順で先に起動しておく前提。
 *
 * - E2E_BASE_URL: フロントの起点（既定 http://localhost:3100）
 * - E2E_API_URL : バックエンド API の起点（既定 http://localhost:8000/api/v1）
 * - E2E_ALLOW_REMOTE: 1 のときだけローカル以外への実行を許す（既定は拒否）
 *
 * 直列実行（workers: 1 / fullyParallel: false）は意図的。シナリオが同一の
 * 使い捨て DB 上の成約・取引を消費するため、並列化すると別テストが掴んだ
 * 取引を横取りして偽陽性・偽陰性の双方を生む。
 */
import { defineConfig, devices } from "@playwright/test";
import { API_URL, BASE_URL } from "./e2e/helpers/env";
import { assertLocalTargets } from "./e2e/helpers/local-target";

// 設定の読み込み時に止める（主防御）。beforeAll・afterAll を含め、ワーカーを1つも
// 起動する前に throw する。
assertLocalTargets([
  { label: "E2E_BASE_URL", url: BASE_URL },
  { label: "E2E_API_URL", url: API_URL },
]);

export default defineConfig({
  testDir: "./e2e",
  // e2e/ 配下の *.test.mts は node --test で実行する単体テスト（Playwright の既定の
  // testMatch は *.test.* も拾ってしまう）。spec だけに絞ることで、eslint の import 制限
  // （e2e/**/*.spec.ts が対象。docs/ops/e2e.md）の外にテストが置かれるのも防ぐ。
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    locale: "ja-JP",
    timezoneId: "Asia/Tokyo",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } },
    },
    {
      // モバイル幅の回帰（横スクロール・折返し）を見る。chromium のまま幅だけ 375px に
      // する（タッチエミュレーションを入れると hover 前提の導線が別要因で落ちるため）。
      name: "mobile",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } },
    },
  ],
});
