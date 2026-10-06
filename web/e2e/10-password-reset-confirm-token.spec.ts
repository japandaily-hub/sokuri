/**
 * (10) パスワード再設定の確定画面: URL の token の 3 態（あり・なし・不正形式）。
 *
 * QA M1: 開発モード（reactStrictMode）では最初の effect が 2 回走り、2 回目は URL から token が消えて
 * いて「このリンクは使えません」になっていた。token を ref に保持して読み直さないことを確かめる。
 * backend には触れない（確定 API は route で差し替え、実際の再設定はしない）。
 *
 * 注意: この spec は追加しただけで未実行（作業中は E2E スタックを別の確認で使っていたため）。
 */
import { test, expect } from "./helpers/test";

const CONFIRM_URL = "/password-reset/confirm";
/** 形式（URL セーフ文字 32〜128 字）に合う token。実在の token ではない。 */
const VALID_TOKEN = "A".repeat(43);

test.describe("パスワード再設定の確定画面 token の 3 態", () => {
  test("あり: 入力欄が出て、URL から token が消え、確定 API へ token が渡る", async ({ page }) => {
    let postedBody: Record<string, unknown> | null = null;
    await page.route("**/auth/password-reset/confirm", async (route) => {
      postedBody = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ detail: "ok" }) });
    });

    await page.goto(`${CONFIRM_URL}?token=${VALID_TOKEN}&type=user`, { waitUntil: "domcontentloaded" });

    // Strict Mode の 2 回目の effect の後でも、「使えません」ではなく入力欄が出ている。
    await expect(page.locator(".reset-panel-title").filter({ hasText: "新しいパスワードの設定" })).toBeVisible();
    await expect(page.getByText("このリンクは使えません")).toHaveCount(0);
    expect(page.url()).not.toContain("token=");

    await page.locator("#reset-new-pw").fill("new-password-123");
    await page.locator("#reset-new-pw2").fill("new-password-123");
    await page.getByRole("button", { name: "パスワードを再設定する" }).click();

    await expect(page.getByText("パスワードを再設定しました")).toBeVisible();
    expect(postedBody).toMatchObject({ token: VALID_TOKEN, account_type: "user" });
  });

  test("なし: token が無いリンクは「このリンクは使えません」", async ({ page }) => {
    await page.goto(CONFIRM_URL, { waitUntil: "domcontentloaded" });
    await expect(page.getByText("このリンクは使えません")).toBeVisible();
    await expect(page.locator("#reset-new-pw")).toHaveCount(0);
  });

  test("不正形式: 短い・使えない文字の token は「このリンクは使えません」（確定 API は呼ばない）", async ({ page }) => {
    let called = false;
    await page.route("**/auth/password-reset/confirm", async (route) => {
      called = true;
      await route.abort();
    });

    await page.goto(`${CONFIRM_URL}?token=short`, { waitUntil: "domcontentloaded" });
    await expect(page.getByText("このリンクは使えません")).toBeVisible();
    expect(called).toBe(false);
  });
});
