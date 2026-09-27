/**
 * (4) 依頼者が日程確定 → 減額申請（業者側 API で作成）→ 依頼者が承認 →
 * 業者が完了確定を依頼 → 依頼者が完了確定 → 評価投稿。
 *
 * 成約後の主要導線を1本で通す。減額申請だけは業者 UI ではなく API で作る
 * （業者側の申請フォームは別テストの範囲。ここでは依頼者側の受け取りと承認を見る）。
 * 業者 context は減額承認の直後に作成し、完了確定の依頼・業者→依頼者の評価投稿まで使い回す
 * （newE2EContext は next dev の開発用オーバーレイを消す。helpers/test.ts）。
 *
 * 日程確定では「業者へのひとこと」に運営を名乗る文面を入れ、依頼者・業者の両チャットで
 * 運営名義の確定メッセージが中央のお知らせ枠（定型文）で出て、ひとことは枠の外の吹き出しに
 * 分かれることも確かめる（日程検証レビュー SEC-L1/SEC-I8）。
 */
import { Page } from "@playwright/test";

import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS } from "./helpers/env";
import { ensureUnscheduledTransaction } from "./helpers/fixtures";
import { test, expect, newE2EContext } from "./helpers/test";
import { confirmModal, loginAsOperator, loginAsUser } from "./helpers/ui";

let api: Api;
let sellerToken: string;
let vendor: OperatorSession;

/** 固定時間帯「9:00〜12:00」。〜は U+301C（WAVE DASH）で、打ち間違えないよう文字コードから組み立てる。 */
const MORNING_SLOT = `9:00${String.fromCharCode(0x301c)}12:00`;

/**
 * 運営名義の日程確定メッセージが中央のお知らせ枠（role="note"）に定型文で出て、依頼者の
 * ひとことはその枠の外（本人の吹き出し）に出ることを確かめる。依頼者・業者のチャットで共通。
 */
async function expectScheduleNoticeWithSeparateNote(page: Page, note: string): Promise<void> {
  const notice = page.getByRole("note").filter({ hasText: "訪問日程が確定しました。" });
  await expect(notice).toBeVisible({ timeout: 30_000 });
  await expect(notice).toContainText("カタヅケからのお知らせ");
  await expect(notice).toContainText(`時間帯：${MORNING_SLOT}`);
  // 固定時間帯での確定なので「業者が提示した候補」の別枠は出ない。
  await expect(notice.getByText("業者が提示した候補")).toHaveCount(0);
  // ひとことは運営の枠に連結されず、枠の外の吹き出しとして出る。
  await expect(notice).not.toContainText(note);
  await expect(page.locator(".msg .bubble").filter({ hasText: note })).toBeVisible();
}

test.beforeAll(async () => {
  api = await Api.create();
  const tokens = await loginAll(api);
  sellerToken = tokens.seller;
  vendor = tokens.vendor;
});

test.afterAll(async () => {
  await api.dispose();
});

test("日程確定 → 減額承認 → 完了確定を依頼 → 完了確定 → 評価投稿まで通る", async ({ page, browser }) => {
  const txn = await ensureUnscheduledTransaction(api, sellerToken, vendor);

  await loginAsUser(page, ACCOUNTS.seller, `/schedule?transaction_id=${txn.id}`);

  // ---- 日程確定 ----
  // カレンダーが描画されるまで待つ（月送りボタンの出現を待機点にする）。
  await expect(page.getByRole("button", { name: "次の月" })).toBeVisible({ timeout: 30_000 });
  // 完了確定の依頼は「visiting かつ訪問日が今日以前」でなければ押せなくなるため、
  // 次の月には進めず当月の「今日」を選ぶ。playwright.config の timezoneId（Asia/Tokyo）
  // とテスト実行端末のタイムゾーンが異なる場合があるため、日付はブラウザ側で取る
  // （実行端末で 0〜9 時に走らせても、ブラウザ内は JST の日付として一致させる）。
  const todayDay = await page.evaluate(() => String(new Date().getDate()));
  await page.getByRole("button", { name: todayDay, exact: true }).click();
  await expect(page.getByText("希望時間帯を選んでください")).toBeVisible();
  await page.getByRole("button", { name: /9:00〜12:00/ }).click();
  // 運営を名乗る文面のひとこと（運営名義のお知らせに見えないことを後で両チャットで確かめる）。
  const note = `（運営補足）E2E ひとこと ${Date.now()}`;
  await page.getByLabel(/業者へのひとこと/).fill(note);
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

  // ---- 依頼者: 案件詳細のチャットで、日程確定のお知らせ枠とひとことの吹き出しが分かれている ----
  await expectScheduleNoticeWithSeparateNote(page, note);

  // ---- 業者 context を前倒しで作成し、完了確定の依頼〜評価投稿まで使い回す ----
  const operatorContext = await newE2EContext(browser);
  try {
    const operatorPage = await operatorContext.newPage();
    // ---- 業者: チャットでも、日程確定のお知らせ枠とお客様のひとことの吹き出しが分かれている ----
    await loginAsOperator(operatorPage, ACCOUNTS.vendor, `/operator/chat/${txn.id}`);
    await expectScheduleNoticeWithSeparateNote(operatorPage, note);
    await operatorPage.goto(`/operator/transactions/${txn.id}`);

    // ---- 業者: 完了確定を依頼する ----
    const requestCompletionButton = operatorPage.getByRole("button", { name: "完了確定を依頼する" });
    await requestCompletionButton.click();
    await expect(operatorPage.getByText("ユーザーに完了確定を依頼しました。")).toBeVisible({ timeout: 30_000 });
    // 24時間のクールダウンでボタンが無効化され、次に依頼できる時刻の注記に変わる。
    await expect(requestCompletionButton).toBeDisabled();
    await expect(operatorPage.getByText(/^依頼済みです。次に依頼できるのは/)).toBeVisible({ timeout: 30_000 });

    // ---- 依頼者: /cases のチャットに依頼メッセージが届く ----
    await page.goto(`/cases/${txn.case_id}`);
    await expect(page.getByText("作業完了の確定をお願いします。")).toBeVisible({ timeout: 30_000 });

    // ---- 完了確定 ----
    await page.getByRole("button", { name: "作業完了を確定する" }).click();
    await confirmModal(page, /作業完了を確定しますか？/, "確定する");

    await expect
      .poll(async () => (await api.getTransaction(txn.id, sellerToken)).status, { timeout: 30_000 })
      .toBe("completed");

    // ---- 業者: 完了確定済みではボタンが消え、確定済みの案内文言に変わる ----
    // reload 直後は読み込み中でボタンがまだ描画されておらず toHaveCount(0) が
    // 空振りで成立してしまうため、案内文言の表示を先に待ってからボタン0件を確かめる。
    await operatorPage.reload();
    await expect(operatorPage.getByText("作業完了はユーザーが確定済みです。")).toBeVisible({ timeout: 30_000 });
    await expect(operatorPage.getByRole("button", { name: "完了確定を依頼する" })).toHaveCount(0);

    // ---- 案件詳細のインライン評価フォーム: 評価を選ぶまで送信不可であることを確認 ----
    // (別画面の /review へ実際に投稿する前に、cases/[id] 側のフォームだけを軽く確認する。
    //  ここでは投稿しない＝取引を追加消費しない。)
    await page.goto(`/cases/${txn.case_id}`);
    const inlineSubmitButton = page.getByRole("button", { name: "評価を投稿する" });
    await expect(inlineSubmitButton).toBeVisible({ timeout: 30_000 });
    await expect(inlineSubmitButton).toBeDisabled();

    // ---- 評価投稿（依頼者→業者。既存どおり /review で行う） ----
    await page.goto(`/review?transaction_id=${txn.id}`);
    await expect(page.getByText("業者を評価してください")).toBeVisible({ timeout: 30_000 });
    const submitReviewButton = page.getByRole("button", { name: "評価を送信する" });
    await expect(submitReviewButton).toBeDisabled();
    await page.getByRole("radio", { name: "よかった" }).check();
    await page.getByRole("button", { name: "安心して取引できました！" }).click();
    await submitReviewButton.click();
    await expect(page.getByText("評価を送信しました。")).toBeVisible({ timeout: 30_000 });

    const reviewedByUser = await api.getTransaction(txn.id, sellerToken);
    expect(reviewedByUser.reviews.find((r) => r.reviewer_type === "user")?.verdict).toBe("good");

    // ---- 評価投稿（業者→依頼者。同じ operatorPage を使い回して /operator/transactions/[id] から投稿する） ----
    await operatorPage.goto(`/operator/transactions/${txn.id}`);
    await expect(operatorPage.getByText("ユーザーを評価する")).toBeVisible({ timeout: 30_000 });
    await operatorPage.getByRole("radio", { name: "よかった" }).check();
    await operatorPage
      .getByRole("button", { name: "事前の写真と説明が正確で助かりました！" })
      .click();
    await operatorPage.getByRole("button", { name: "レビューを投稿" }).click();
    await expect(operatorPage.getByText("評価投稿済み（よかった）")).toBeVisible({ timeout: 30_000 });
  } finally {
    await operatorContext.close();
  }

  const reviewedByOperator = await api.getTransaction(txn.id, sellerToken);
  expect(reviewedByOperator.reviews.find((r) => r.reviewer_type === "operator")?.verdict).toBe("good");
});
