/**
 * (9) 運営が口コミを削除・元に戻せる。報告リンク → /contact → /admin/contacts の
 *     「該当の口コミを開く」導線が繋がる。
 *
 * シードには口コミが無いため、前提の完了済み取引・口コミ投稿は (04) と同じ手順
 * （日程確定 → 完了確定 → /review で投稿）で自前に作る。コメントは Date.now() を含む
 * 一意な文字列にし、蓄積される過去実行分の口コミと混同しないようにする。
 * 削除・復元は /admin/reviews の実 UI（ConfirmModal 経由）を通す。
 */
import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS } from "./helpers/env";
import { ensureUnscheduledTransaction } from "./helpers/fixtures";
import { test, expect, newE2EContext } from "./helpers/test";
import { confirmModal, loginAsUser } from "./helpers/ui";

let api: Api;
let sellerToken: string;
let adminToken: string;
let vendor: OperatorSession;

test.beforeAll(async () => {
  api = await Api.create();
  const tokens = await loginAll(api);
  sellerToken = tokens.seller;
  adminToken = tokens.admin;
  vendor = tokens.vendor;
});

test.afterAll(async () => {
  await api.dispose();
});

test("運営が口コミを削除・元に戻せる。報告→問い合わせ→該当口コミの導線が繋がる", async ({ page, browser }) => {
  // ---- 前提: 完了済み取引と依頼者→業者の口コミを1件用意する（04 spec と同じ手順） ----
  const txn = await ensureUnscheduledTransaction(api, sellerToken, vendor);
  await loginAsUser(page, ACCOUNTS.seller, `/schedule?transaction_id=${txn.id}`);

  const nextMonth = page.getByRole("button", { name: "次の月" });
  await expect(nextMonth).toBeVisible({ timeout: 30_000 });
  await nextMonth.click();
  await page.getByRole("button", { name: "15", exact: true }).click();
  await expect(page.getByText("希望時間帯を選んでください")).toBeVisible();
  await page.getByRole("button", { name: /9:00〜12:00/ }).click();
  await page.getByRole("button", { name: /この日程で確定する/ }).click();
  await expect(page.getByText("訪問日程を確定しました")).toBeVisible({ timeout: 30_000 });

  await page.goto(`/cases/${txn.case_id}`);
  await page.getByRole("button", { name: "作業完了を確定する" }).click();
  await confirmModal(page, /作業完了を確定しますか？/, "確定する");
  await expect
    .poll(async () => (await api.getTransaction(txn.id, sellerToken)).status, { timeout: 30_000 })
    .toBe("completed");

  const reportComment = `E2E運営削除検証${Date.now()}`;
  await page.goto(`/review?transaction_id=${txn.id}`);
  await expect(page.getByText("業者を評価してください")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("radio", { name: "よかった" }).check();
  await page.getByPlaceholder("業者の対応の感想（任意）").fill(reportComment);
  await page.getByRole("button", { name: "評価を送信する" }).click();
  await expect(page.getByText("評価を送信しました。")).toBeVisible({ timeout: 30_000 });

  const withReview = await api.getTransaction(txn.id, sellerToken);
  const review = withReview.reviews.find((r) => r.reviewer_type === "user");
  if (!review) throw new Error("前提の口コミ作成に失敗しました");

  // ---- 公開プロフィールに口コミが載っており、報告リンクが /contact に ID を渡す ----
  await page.goto(`/vendors/${vendor.operatorId}`);
  await expect(page.getByText(reportComment)).toBeVisible({ timeout: 30_000 });
  const titleLocator = page.locator(".detail-card-title").filter({ hasText: "口コミ" });
  const countBefore = Number((await titleLocator.innerText()).match(/\d+/)?.[0] ?? "0");

  const reviewCard = page.locator(".review-item").filter({ hasText: reportComment });
  await reviewCard.getByRole("link", { name: "この口コミを報告する" }).click();
  await page.waitForURL("**/contact*");
  await expect(page.getByText(`報告する口コミ: ${review.id}`)).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#category")).toHaveValue("other");

  const contactEmail = `e2e-review-report-${Date.now()}@example.com`;
  await page.locator("#name").fill("E2E 口コミ通報");
  await page.locator("#email").fill(contactEmail);
  await page.locator("#message").fill("この口コミは不適切な内容です。削除をお願いします。");
  await page.getByRole("button", { name: "送信する" }).click();
  await expect(page.getByText("送信を受け付けました")).toBeVisible({ timeout: 30_000 });

  // ---- 運営: /admin/contacts の該当行から /admin/reviews へ ----
  const adminContext = await newE2EContext(browser);
  try {
    const adminPage = await adminContext.newPage();
    await loginAsUser(adminPage, ACCOUNTS.admin, "/admin/contacts");
    const contactRow = adminPage.getByRole("row").filter({ hasText: contactEmail });
    await expect(contactRow).toBeVisible({ timeout: 30_000 });
    await contactRow.getByRole("link", { name: "該当の口コミを開く" }).click();
    await adminPage.waitForURL("**/admin/reviews*");

    // q=<口コミID> の完全一致で絞り込まれ、1件だけ出ること。
    const reviewRows = adminPage.getByRole("row").filter({ hasText: reportComment });
    await expect(reviewRows).toBeVisible({ timeout: 30_000 });
    await expect(reviewRows).toHaveCount(1);

    // ---- 削除する ----
    await reviewRows.getByRole("button", { name: "削除する" }).click();
    const hideDialog = adminPage.getByRole("dialog").filter({ hasText: "この口コミを公開画面から削除します" });
    await expect(hideDialog).toBeVisible();
    await hideDialog.getByLabel(/削除理由/).fill("誹謗中傷・名誉毀損のおそれ：E2E検証");
    await hideDialog.getByRole("button", { name: "削除する" }).click();
    await expect(hideDialog).toBeHidden({ timeout: 30_000 });

    // ---- backend の契約も直接確認する（UI だけでなく API 応答の hidden_reason を検証） ----
    const hiddenCheck = await api.adminListReviews({ visibility: "hidden", q: review.id }, adminToken);
    expect(hiddenCheck.items).toHaveLength(1);
    expect(hiddenCheck.items[0]?.hidden_reason).toBe("誹謗中傷・名誉毀損のおそれ：E2E検証");
    expect(hiddenCheck.items[0]?.hidden_at).toBeTruthy();

    // ---- 公開画面から消え、件数が1件減っていること ----
    await page.goto(`/vendors/${vendor.operatorId}`);
    await expect(page.getByText(reportComment)).toBeHidden({ timeout: 30_000 });
    const countAfterHide = Number((await titleLocator.innerText()).match(/\d+/)?.[0] ?? "0");
    expect(countAfterHide).toBe(countBefore - 1);

    // ---- 削除済み一覧で理由が見える ----
    await adminPage.goto("/admin/reviews");
    await adminPage.getByRole("button", { name: "削除済み" }).click();
    const hiddenRow = adminPage.getByRole("row").filter({ hasText: reportComment });
    await expect(hiddenRow).toBeVisible({ timeout: 30_000 });
    await expect(hiddenRow).toContainText("誹謗中傷・名誉毀損のおそれ：E2E検証");

    // ---- 元に戻す ----
    await hiddenRow.getByRole("button", { name: "元に戻す" }).click();
    const restoreDialog = adminPage.getByRole("dialog").filter({ hasText: "この口コミを元に戻します" });
    await expect(restoreDialog).toBeVisible();
    await restoreDialog.getByRole("button", { name: "元に戻す" }).click();
    await expect(restoreDialog).toBeHidden({ timeout: 30_000 });

    await page.goto(`/vendors/${vendor.operatorId}`);
    await expect(page.getByText(reportComment)).toBeVisible({ timeout: 30_000 });
  } finally {
    await adminContext.close();
  }
});
