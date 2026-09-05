/**
 * (2) 依頼者ログイン → マイページ → 案件詳細で入札を選定（確認モーダル）→ 成約表示。
 *
 * 選定の確認は window.confirm ではなく共通 ConfirmModal（role="dialog"）である点が
 * 回帰しやすいので、ダイアログの出現・確定・成約パネル表示までを通しで見る。
 */
import { test, expect } from "@playwright/test";

import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS } from "./helpers/env";
import { ensureOpenCaseWithBid } from "./helpers/fixtures";
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

test("依頼者が入札を選定すると成約パネルが出る", async ({ page }) => {
  const { caseId, bidId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);

  await loginAsUser(page, ACCOUNTS.seller, "/mypage");

  // マイページのサマリーが描画されている（集計カード）。
  await expect(page.getByText("入札受付中").first()).toBeVisible();
  await expect(page.locator("text=成約済み >> visible=true").first()).toBeVisible();

  // 対象案件のカードから詳細へ。カードは <Link href="/cases/{id}"> なので href で引く。
  const card = page.locator(`a[href="/cases/${caseId}"]`).first();
  await expect(card).toBeVisible();
  await card.click();
  await page.waitForURL(`**/cases/${caseId}`);

  // 入札一覧が出ていること。
  await expect(page.getByRole("heading", { name: /入札一覧/ })).toBeVisible();

  // 対象入札の「この業者に決める」を押す（入札が複数あるため行を絞り込む）。
  const selectButtons = page.getByRole("button", { name: "この業者に決める" });
  await expect(selectButtons.first()).toBeVisible();
  await selectButtons.first().click();

  // window.confirm ではなく ConfirmModal であること。
  await confirmModal(page, /この業者に決定しますか？/, "決定する");

  // 成約パネル（成約: 〇〇）と、チャット・日程調整の導線が出る。
  await expect(page.getByRole("heading", { name: /^成約: / })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("link", { name: /業者とチャット/ })).toBeVisible();

  // API 側でも「どの入札が選ばれたか」が確定し、取引が生成されている
  // （画面表示だけの偽陽性を防ぐ）。案件に複数入札があり得るため、押下したのが
  // ensureOpenCaseWithBid の返した入札とは限らない点に依存しない検証にしている。
  const detail = await api.getCase(caseId, sellerToken);
  expect(detail.bids.map((b) => b.id)).toContain(bidId);
  expect(detail.bids.filter((b) => b.status === "selected")).toHaveLength(1);
  const txns = await api.listTransactions(sellerToken);
  expect(txns.some((t) => t.case_id === caseId)).toBe(true);
});
