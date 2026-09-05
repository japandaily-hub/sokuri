/**
 * (6) 異常系。
 *   6-1 運営の強制終了 → 依頼者チャットが「この取引は終了しています」・送信 API が 409
 *   6-2 誤パスワード 6 回で 429 の文言（アカウント軸の上限は既定 5 回/15分）
 *
 * 6-2 は審査中業者アカウント（pending@example.com）を使う。ロックしても他テストの
 * 前提に影響しないアカウントを選ぶこと（seller/vendor を使うと後続が全部落ちる）。
 */
import { test, expect } from "@playwright/test";

import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS, API_URL } from "./helpers/env";
import { ensureLiveTransaction } from "./helpers/fixtures";
import { loginAsUser } from "./helpers/ui";

let api: Api;
let adminToken: string;
let sellerToken: string;
let vendor: OperatorSession;

test.beforeAll(async () => {
  api = await Api.create();
  const tokens = await loginAll(api);
  adminToken = tokens.admin;
  sellerToken = tokens.seller;
  vendor = tokens.vendor;
});

test.afterAll(async () => {
  await api.dispose();
});

test("運営が強制終了した取引はチャットが閉じ、送信 API が 409 を返す", async ({ page }) => {
  const txn = await ensureLiveTransaction(api, sellerToken, vendor);
  await api.adminCancelTransaction(txn.id, "E2E: 運営による強制終了の検証", adminToken);

  await loginAsUser(page, ACCOUNTS.seller, `/chat/${txn.id}`);
  await expect(page.getByText(/この取引は終了しています/).first()).toBeVisible({ timeout: 30_000 });

  // 画面表示だけでなく API 側でも閉じている（フロントの見た目だけの回帰を弾く）。
  const res = await api.sendMessageRaw(txn.id, "E2E: 終了後の送信", sellerToken);
  expect(res.status()).toBe(409);
});

test("誤パスワードを 6 回続けると 429 の案内文言が出る", async ({ page }) => {
  // 1〜5 回目は API 直叩きで確実に失敗を積む（UI 経由だと送信完了の待機点が
  // 曖昧になり、試行回数が揺れて 429 に届かないことがある）。6 回目だけ画面から行い、
  // 「パスワードが違います」ではなく 429 専用の文言が出ることを確認する。
  for (let i = 0; i < 5; i += 1) {
    const res = await api
      .raw()
      .post(`${API_URL}/auth/operator/login`, {
        data: { email: ACCOUNTS.pending.email, password: `Wrong-Pass-${i}-2026` },
      });
    expect([401, 403, 429]).toContain(res.status());
  }

  await page.goto("/operator/login");
  await page.locator('input[type="email"]').fill(ACCOUNTS.pending.email);
  await page.locator('input[type="password"]').fill("Wrong-Pass-final-2026");
  await page.locator('button[type="submit"]').click();

  await expect(page.getByText(/短時間に試行が集中しました/)).toBeVisible({ timeout: 30_000 });
});
