/**
 * Playwright（E2E スモーク）の設定。
 *
 * 対象はローカルスタックのみ（本番には決して向けないこと）。サーバーの起動は
 * このファイルでは行わない（webServer 未使用）。バックエンド・フロントは
 * docs/ops/e2e.md の手順で先に起動しておく前提。
 *
 * - E2E_BASE_URL: フロントの起点（既定 http://localhost:3100）
 * - E2E_API_URL : バックエンド API の起点（既定 http://localhost:8000/api/v1）
 *
 * 直列実行（workers: 1 / fullyParallel: false）は意図的。シナリオが同一の
 * 使い捨て DB 上の成約・取引を消費するため、並列化すると別テストが掴んだ
 * 取引を横取りして偽陽性・偽陰性の双方を生む。
 */
import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
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
