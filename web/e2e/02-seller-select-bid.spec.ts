/**
 * (2) 依頼者ログイン → マイページ → 案件詳細で入札を選定（確認モーダル）→ 業者決定の表示。
 *
 * 選定の確認は window.confirm ではなく共通 ConfirmModal（role="dialog"）である点が
 * 回帰しやすいので、ダイアログの出現・確定・成約パネル表示までを通しで見る。
 */
import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS } from "./helpers/env";
import { ensureOpenCaseWithBid } from "./helpers/fixtures";
import { test, expect } from "./helpers/test";
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
  await expect(page.locator("text=業者決定済み >> visible=true").first()).toBeVisible();

  // 対象案件のカードから詳細へ。カードは <Link href="/cases/{id}"> なので href で引く。
  const card = page.locator(`a[href="/cases/${caseId}"]`).first();
  await expect(card).toBeVisible();
  await card.click();
  await page.waitForURL(`**/cases/${caseId}`);

  // 入札一覧が出ていること。
  await expect(page.getByRole("heading", { name: /入札一覧/ })).toBeVisible();

  // 対象入札（業者A＝ensureOpenCaseWithBid が返した入札）の行の「この業者に決める」を押す。
  // 一覧は金額の高い順に並ぶため（シードの案件1は業者B 45,000 円が業者A 30,000 円より上）、
  // 先頭を押すと業者B に決まり、業者A が当事者である前提の 03/04 が別業者の取引を掴んでしまう。
  const beforeSelect = await api.getCase(caseId, sellerToken);
  const vendorCompanyName = beforeSelect.bids.find((b) => b.id === bidId)?.operator?.company_name;
  expect(vendorCompanyName, "対象入札の業者名が取得できること").toBeTruthy();
  const selectButton = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("button", { name: "この業者に決める" }) })
    .filter({ hasText: vendorCompanyName! })
    .getByRole("button", { name: "この業者に決める" });
  await expect(selectButton).toHaveCount(1);
  await selectButton.click();

  // window.confirm ではなく ConfirmModal であること。
  await confirmModal(page, /この業者に決定しますか？/, "決定する");

  // 決定パネル（業者が決まりました: 〇〇）と、チャット・日程調整の導線が出る。
  // チャットは別ページへのリンクではなく、この画面内に開いた状態で埋め込まれる
  // （r-chat-inline・d9b4c06 以降）。開閉ボタンは開いている間「チャットを閉じる」
  // （未読があると「（未読N）」が続くため前方一致）で、入力欄まで描画されることを見る。
  await expect(page.getByRole("heading", { name: /^業者が決まりました: / })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: /^チャットを閉じる/, expanded: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "メッセージを入力", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "訪問日程を調整する" })).toBeVisible();

  // API 側でも、押した業者A の入札が選ばれ、取引が生成されている（画面表示だけの偽陽性を防ぐ）。
  const detail = await api.getCase(caseId, sellerToken);
  const selected = detail.bids.filter((b) => b.status === "selected");
  expect(selected).toHaveLength(1);
  expect(selected[0].id).toBe(bidId);
  const txns = await api.listTransactions(sellerToken);
  expect(txns.some((t) => t.case_id === caseId)).toBe(true);
});
