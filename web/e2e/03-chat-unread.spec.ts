/**
 * (3) 依頼者チャット送信 → 業者ログイン（別 context）→ 取引一覧に未読1 → 返信 →
 * 候補日提案（日付入力＋時間帯ボタン） → 依頼者側にも候補日が届く。
 *
 * 未読カウントは r6 で入れた導線なので、依頼者→業者の向きで実際に増えることを見る。
 */
import { BrowserContext, Page } from "@playwright/test";

import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS, API_URL } from "./helpers/env";
import { ensureUnscheduledTransaction } from "./helpers/fixtures";
import { test, expect, newE2EContext } from "./helpers/test";
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
  // pending・visit_date なしの取引を使う（visiting だと業者側で新しい候補日を提示できない）。
  const txn = await ensureUnscheduledTransaction(api, sellerToken, vendor);

  // ---- 依頼者: チャットで送信 ----
  const body = `E2E 依頼者メッセージ ${Date.now()}`;
  await loginAsUser(page, ACCOUNTS.seller, `/chat/${txn.id}`);
  // 見出し「交渉チャット」はモバイル幅で非表示になるため、入力欄の出現で画面到達を判定する。
  await expect(page.getByRole("textbox", { name: "メッセージを入力", exact: true })).toBeVisible();

  const input = page.getByRole("textbox", { name: "メッセージを入力", exact: true });
  await input.fill(body);
  await page.getByRole("button", { name: "送信", exact: true }).click();
  await expect(page.getByText(body)).toBeVisible({ timeout: 30_000 });

  // 業者が提示する候補日（3日後・必ず未来日になる）。期待ラベルはテスト内で独自に
  // 組み立てる（アプリの formatSlotLabel を import せず、DOM に出た文言と純粋比較する）。
  const target = new Date();
  target.setDate(target.getDate() + 3);
  const targetIso = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}-${String(target.getDate()).padStart(2, "0")}`;
  const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"];
  const expectedSlotLabel = `${target.getFullYear()}年${target.getMonth() + 1}月${target.getDate()}日（${DOW_LABELS[target.getDay()]}）9:00〜12:00`;

  // 同日・同一取引の再実行では前回の候補日と同じラベルになりうるため、単純な visible 判定
  // では新規追加を確認できない（前回分がそのまま見えているだけでも空振りで成立してしまう）。
  // 依頼者側の件数は業者操作の前に確定させておき、送信後に +1 になることで検証する。
  const matchingRadios = page.getByRole("radio", { name: expectedSlotLabel, exact: true });
  const radioCountBefore = await matchingRadios.count();

  // ---- 業者: 別 context で未読を確認 ----
  // browser.newContext() ではなく newE2EContext()。375px 幅では左下の next dev 用
  // インジケーターが入力欄左端の「日程を提案」に重なるため、それを消したコンテキストで開く。
  const vendorContext: BrowserContext = await newE2EContext(browser);
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

    // 送信前に「提示した候補日」リスト全体（複数メッセージぶんの ul をまとめて対象にする）の中で
    // 期待ラベルに一致する件数を数えておく（同日再実行での重複と新規追加を区別するため）。
    const matchingSlotTexts = vendorPage
      .getByRole("list", { name: "提示した候補日" })
      .getByText(expectedSlotLabel, { exact: true });
    const slotCountBefore = await matchingSlotTexts.count();

    // 候補日 1（role="group"）内で日付入力→時間帯ボタンを選ぶ（自由入力からボタン化）。
    const slot1 = vendorPage.getByRole("group", { name: "候補日 1" });
    await slot1.getByLabel("候補日 1 の日付").fill(targetIso);
    await slot1.getByRole("button", { name: /9:00〜12:00/ }).click();
    await vendorPage.getByRole("button", { name: "候補日を送信する" }).click();
    await expect(matchingSlotTexts).toHaveCount(slotCountBefore + 1, { timeout: 30_000 });
  } finally {
    await vendorContext.close();
  }

  // ---- 依頼者: 候補日が反映される（5秒間隔ポーリング。ページ遷移なしで届く）----
  await expect(matchingRadios).toHaveCount(radioCountBefore + 1, { timeout: 30_000 });

  // 依頼者側の未読が溜まったままだと後続テストの前提が濁るので既読化しておく。
  await api
    .raw()
    .post(`${API_URL}/transactions/${encodeURIComponent(txn.id)}/messages/read`, {
      headers: { Authorization: `Bearer ${sellerToken}` },
    })
    .catch(() => undefined);
});
