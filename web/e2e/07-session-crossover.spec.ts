/**
 * (7) セッションの取り違え。
 *
 * 業者セッションのまま /login を開くと、以前は callbackUrl へ replace → middleware が
 * 差し戻す無限ループの起点になっていた（r3 再レビュー3回目で是正）。行き止まりを作らず
 * サインアウト導線が出ることを守る。
 */
import { test, expect } from "@playwright/test";

import { ACCOUNTS } from "./helpers/env";
import { loginAsOperator } from "./helpers/ui";

test("業者セッションで /login を開くとサインアウト導線が出る", async ({ page }) => {
  await loginAsOperator(page, ACCOUNTS.vendor, "/operator");

  await page.goto("/login");
  // リダイレクトループに入らず /login に留まること。
  await expect(page).toHaveURL(/\/login(\?|$)/);
  await expect(page.getByText(/現在は業者アカウントでログイン中です/)).toBeVisible({ timeout: 30_000 });

  const signOut = page.getByRole("button", { name: /サインアウトして依頼者ログインへ/ });
  await expect(signOut).toBeVisible();
  await signOut.click();

  // サインアウト後は /login に戻り、案内バナーが消える。
  await expect(page.getByText(/現在は業者アカウントでログイン中です/)).toBeHidden({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "ログイン" })).toBeVisible();
});
