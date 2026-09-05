/**
 * (5) 運営ログイン → /admin のバッジ → /admin/operator-applications で申込を承認
 *     → 招待コード表示、/admin/contacts で対応済み。
 *
 * 前提の申込・お問い合わせは API で作る（/business・/contact のフォーム送信そのものは
 * 公開ページのスモークで担保する範囲外なので、ここでは運営側の処理だけを見る）。
 */
import { test, expect } from "@playwright/test";

import { Api } from "./helpers/api";
import { ACCOUNTS, uniqueSuffix } from "./helpers/env";
import { loginAsUser } from "./helpers/ui";

let api: Api;

test.beforeAll(async () => {
  api = await Api.create();
});

test.afterAll(async () => {
  await api.dispose();
});

test("運営が事前申込を承認して招待コードを受け取り、お問い合わせを対応済みにできる", async ({ page }) => {
  const suffix = uniqueSuffix();
  const companyName = `E2E審査テスト商会${suffix}`;
  const contactEmail = `e2e-contact-${suffix}@example.com`;

  await api.submitOperatorApplication({
    company_name: companyName,
    email: `e2e-apply-${suffix}@example.com`,
    // 許可番号は数字のみで組み立てる（シードの "第301234567890号" と同じ形）。
    license_number: `第30${String(Date.now()).slice(-10)}号`,
  });
  await api.submitContact({
    name: "E2E 問合せ",
    email: contactEmail,
    category: "service",
    message: "E2E 自動テストからのお問い合わせです。",
  });

  // ---- 運営トップ: 各審査画面への導線とバッジ ----
  await loginAsUser(page, ACCOUNTS.admin, "/admin");
  await expect(page.getByRole("heading", { name: "管理画面" })).toBeVisible({ timeout: 30_000 });
  const applicationsLink = page.getByRole("link", { name: /事前申込の審査へ/ });
  const contactsLink = page.getByRole("link", { name: /お問い合わせへ/ });
  await expect(applicationsLink).toBeVisible();
  await expect(contactsLink).toBeVisible();
  // 直前に投入した分があるので、件数バッジ（1以上）が付いていること。
  await expect(applicationsLink).toHaveText(/[1-9]\d*/);
  await expect(contactsLink).toHaveText(/[1-9]\d*/);

  // ---- 事前申込の承認 → 招待コード表示 ----
  await applicationsLink.click();
  await page.waitForURL("**/admin/operator-applications");
  const row = page.getByRole("row").filter({ hasText: companyName });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "詳細を確認" }).click();

  const detailDialog = page.getByRole("dialog").filter({ hasText: companyName });
  await expect(detailDialog).toBeVisible();
  await detailDialog.getByRole("button", { name: "承認する" }).click();

  // ConfirmModal（招待コード発行の確認）で確定する。
  const confirm = page.getByRole("dialog").filter({ hasText: /承認すると招待コードが発行され/ });
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: "承認する" }).click();

  await expect(page.getByText(/承認しました。招待コード：/)).toBeVisible({ timeout: 30_000 });

  // ---- お問い合わせを対応済みへ ----
  await page.goto("/admin/contacts");
  const contactRow = page.getByRole("row").filter({ hasText: contactEmail });
  await expect(contactRow).toBeVisible({ timeout: 30_000 });
  await contactRow.getByRole("button", { name: "対応済みにする" }).click();

  const contactConfirm = page.getByRole("dialog").filter({ hasText: /対応済みにすると未対応の一覧/ });
  await expect(contactConfirm).toBeVisible();
  await contactConfirm.getByRole("button", { name: "対応済みにする" }).click();
  await expect(contactConfirm).toBeHidden({ timeout: 30_000 });

  // 既定の絞り込み（未対応）から外れる、または状態が「対応済み」になる。
  await expect
    .poll(
      async () => {
        const stillListed = await page.getByRole("row").filter({ hasText: contactEmail }).count();
        if (stillListed === 0) return "handled";
        const text = await page.getByRole("row").filter({ hasText: contactEmail }).first().innerText();
        return text.includes("対応済み") ? "handled" : "pending";
      },
      { timeout: 30_000 },
    )
    .toBe("handled");
});
