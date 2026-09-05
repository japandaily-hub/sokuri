/**
 * (4) 依頼者が日程確定 → 減額申請（業者側 API で作成）→ 依頼者が承認 → 完了確定 → 評価投稿。
 *
 * 成約後の主要導線を1本で通す。減額申請だけは業者 UI ではなく API で作る
 * （業者側の申請フォームは別テストの範囲。ここでは依頼者側の受け取りと承認を見る）。
 */
import { test, expect } from "@playwright/test";

import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS } from "./helpers/env";
import { ensureUnscheduledTransaction } from "./helpers/fixtures";
import { confirmModal, loginAsUser } from "./helpers/ui";

let api: Api;
let sellerToken: string;
let vendor: OperatorSession;

test.beforeAll(async () => {
  api = await Api.create();
  const tokens = await loginAll(api);
  sellerToken = tokens.seller;
  vendor = tokens.vendor;
});

test.afterAll(async () => {
  await api.dispose();
});

test("日程確定 → 減額承認 → 完了確定 → 評価投稿まで通る", async ({ page }) => {
  const txn = await ensureUnscheduledTransaction(api, sellerToken, vendor);

  await loginAsUser(page, ACCOUNTS.seller, `/schedule?transaction_id=${txn.id}`);

  // ---- 日程確定 ----
  // カレンダーが描画されるまで待つ（月送りボタンの出現を待機点にする）。
  const nextMonth = page.getByRole("button", { name: "次の月" });
  await expect(nextMonth).toBeVisible({ timeout: 30_000 });
  // 当月末に近いと「翌日」が翌月になるため、常に翌月の 15 日を選ぶ（必ず未来日）。
  await nextMonth.click();
  await page.getByRole("button", { name: "15", exact: true }).click();
  await expect(page.getByText("希望時間帯を選んでください")).toBeVisible();
  await page.getByRole("button", { name: /9:00〜12:00/ }).click();
  await page.getByRole("button", { name: /この日程で確定する/ }).click();
  await expect(page.getByText("訪問日程を確定しました")).toBeVisible({ timeout: 30_000 });

  // ---- 業者が減額申請（API）----
  const detail = await api.getTransaction(txn.id, sellerToken);
  const requested = Math.max(1000, detail.initial_amount - 3000);
  await api.createReduction(
    txn.id,
    { requested_amount: requested, reason: "E2E: 現地で搬出経路の追加作業が発生したため。" },
    vendor.token,
  );

  // ---- 依頼者が承認 ----
  await page.goto(`/cases/${txn.case_id}`);
  await expect(page.getByText("業者から減額申請が届いています")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "承認する" }).click();
  await confirmModal(page, /減額を承認しますか？/, "承認する");
  await expect(page.getByText("業者から減額申請が届いています")).toBeHidden({ timeout: 30_000 });

  // ---- 完了確定 ----
  await page.getByRole("button", { name: "作業完了を確定する" }).click();
  await confirmModal(page, /作業完了を確定しますか？/, "確定する");

  await expect
    .poll(async () => (await api.getTransaction(txn.id, sellerToken)).status, { timeout: 30_000 })
    .toBe("completed");

  // ---- 評価投稿 ----
  await page.goto(`/review?transaction_id=${txn.id}`);
  await expect(page.getByText("業者を評価してください")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "5つ星" }).click();
  await page.getByRole("button", { name: "評価を送信する" }).click();
  await expect(page.getByText("評価を送信しました。")).toBeVisible({ timeout: 30_000 });
});
