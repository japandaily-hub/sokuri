/**
 * (3) 依頼者チャット送信 → 業者ログイン（別 context）→ 取引一覧に未読1 → 返信 → 候補日提案。
 *
 * 未読カウントは r6 で入れた導線なので、依頼者→業者の向きで実際に増えることを見る。
 */
import { test, expect, BrowserContext, Page } from "@playwright/test";

import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS, API_URL } from "./helpers/env";
import { ensureLiveTransaction } from "./helpers/fixtures";
import { loginAsOperator, loginAsUser } from "./helpers/ui";

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

test("依頼者の送信が業者側で未読になり、業者が返信と候補日提案をできる", async ({ page, browser }) => {
  const txn = await ensureLiveTransaction(api, sellerToken, vendor);

  // ---- 依頼者: チャットで送信 ----
  const body = `E2E 依頼者メッセージ ${Date.now()}`;
  await loginAsUser(page, ACCOUNTS.seller, `/chat/${txn.id}`);
  // 見出し「交渉チャット」はモバイル幅で非表示になるため、入力欄の出現で画面到達を判定する。
  await expect(page.getByRole("textbox", { name: "メッセージを入力", exact: true })).toBeVisible();

  const input = page.getByRole("textbox", { name: "メッセージを入力", exact: true });
  await input.fill(body);
  await page.getByRole("button", { name: "送信", exact: true }).click();
  await expect(page.getByText(body)).toBeVisible({ timeout: 30_000 });

  // ---- 業者: 別 context で未読を確認 ----
  const vendorContext: BrowserContext = await browser.newContext();
  const vendorPage: Page = await vendorContext.newPage();
  try {
    await loginAsOperator(vendorPage, ACCOUNTS.vendor, "/operator/transactions");
    await expect(vendorPage.getByRole("heading", { name: "取引一覧" })).toBeVisible();
    // 「未読1」以上のチップが出ること（他取引の未読が混ざっても成立する緩い判定）。
    await expect(vendorPage.getByText(/^未読[1-9]\d*$/).first()).toBeVisible({ timeout: 30_000 });

    // ---- 業者: 返信 ----
    await vendorPage.goto(`/operator/chat/${txn.id}`);
    await expect(vendorPage.getByText(body)).toBeVisible({ timeout: 30_000 });

    const reply = `E2E 業者返信 ${Date.now()}`;
    await vendorPage.getByRole("textbox", { name: "メッセージを入力", exact: true }).fill(reply);
    await vendorPage.getByRole("button", { name: "送信", exact: true }).click();
    await expect(vendorPage.getByText(reply)).toBeVisible({ timeout: 30_000 });

    // ---- 業者: 候補日提案 ----
    await vendorPage.getByRole("button", { name: "日程を提案", exact: true }).click();
    await expect(vendorPage.getByText("引き取り候補日を提案する")).toBeVisible();

    const slotText = `E2E候補日 ${Date.now()} 10:00〜12:00`;
    await vendorPage.getByRole("textbox", { name: "候補日 1", exact: true }).fill(slotText);
    await vendorPage.getByRole("button", { name: "候補日を送信する" }).click();
    await expect(vendorPage.getByText(slotText).first()).toBeVisible({ timeout: 30_000 });
  } finally {
    await vendorContext.close();
  }

  // 依頼者側の未読が溜まったままだと後続テストの前提が濁るので既読化しておく。
  await api
    .raw()
    .post(`${API_URL}/transactions/${encodeURIComponent(txn.id)}/messages/read`, {
      headers: { Authorization: `Bearer ${sellerToken}` },
    })
    .catch(() => undefined);
});
