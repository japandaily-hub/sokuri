/**
 * (1) 公開ページのスモーク。
 *
 * 200 で返ること・横スクロールが出ないこと・console error が出ないことの3点だけを
 * 見る。文言の細部は各導線のテストで担保する。
 */
import { test, expect } from "@playwright/test";

import { collectConsoleErrors, expectNoHorizontalScroll } from "./helpers/ui";

/** 未ログインで開ける代表ページ（middleware の保護対象外）。 */
const PUBLIC_PAGES = [
  "/",
  "/business",
  "/examples",
  "/faq",
  "/vendors",
  "/company",
  "/terms",
  "/privacy",
] as const;

test.describe("公開ページ", () => {
  for (const path of PUBLIC_PAGES) {
    test(`${path} が 200・横スクロールなし・console error なし`, async ({ page }) => {
      const errors = collectConsoleErrors(page);

      const res = await page.goto(path, { waitUntil: "domcontentloaded" });
      expect(res, `${path} のレスポンスが取得できない`).not.toBeNull();
      expect(res!.status(), `${path} のステータス`).toBe(200);

      // クライアント描画（use client のページが大半）を待ってから幅を測る。
      await page.waitForLoadState("networkidle");
      await expect(page.locator("body")).toBeVisible();

      await expectNoHorizontalScroll(page);
      expect(errors(), `${path} で console error が出ている`).toEqual([]);
    });
  }
});
