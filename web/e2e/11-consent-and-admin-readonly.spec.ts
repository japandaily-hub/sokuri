/**
 * (11) 規約への同意の必須化と、運営の代理閲覧の読み取り専用（QA M-2）。
 *   11-1 /signup: 同意チェック前は「登録する」を押しても登録 API を呼ばない。チェック後は agreed_terms: true と版数を送る。
 *   11-2 /signup・/login: LINE ボタンは同意チェック前は押せない（disabled）。チェック後に押せる。
 *   11-3 運営の代理閲覧: 依頼者の案件詳細・業者のチャットで、メッセージの入力欄が出ない（読み取り専用の案内が出る）。
 *        減額の承認・却下ボタンと日程の確定ボタンも出ない（security M-1・L-7）。
 *
 * 注意: この spec は追加しただけで未実行（作業中は E2E スタックを別の確認で使っていたため）。
 * 11-1・11-2 は backend に触れない（登録 API は route で差し替える）。11-3 は seed 済みのアカウントでログインする。
 */
import { Api, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS } from "./helpers/env";
import { ensureLiveTransaction } from "./helpers/fixtures";
import { test, expect } from "./helpers/test";
import { loginAsUser } from "./helpers/ui";

test.describe("同意の必須化（メール登録・LINE）", () => {
  test("/signup: 同意チェック前は登録 API を呼ばず、チェック後は同意と版数を送る", async ({ page }) => {
    const posted: Record<string, unknown>[] = [];
    await page.route("**/auth/signup", async (route) => {
      posted.push(route.request().postDataJSON() as Record<string, unknown>);
      // 登録後の流れ（自動ログイン）はこの検証の対象外。失敗で返して手順 3 に留まらせる。
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "E2E stub" }) });
    });

    await page.goto("/signup", { waitUntil: "domcontentloaded" });
    await page.locator("#inp-email").fill(`e2e-consent-${Date.now()}@example.com`);
    await page.locator("#inp-pw").fill("Consent-E2E-2026");
    await page.locator("#inp-pw2").fill("Consent-E2E-2026");
    await page.locator(".btn-flow-next").click();
    await page.locator("#inp-name").fill("同意テスト");
    await page.locator(".btn-flow-next").click();

    // 手順 3: 同意前に「登録する」を押しても先へ進まず、理由が出て、登録 API は呼ばれない。
    const agree = page.locator("#agree1");
    await expect(agree).not.toBeChecked();
    await page.getByRole("button", { name: /登録する/ }).click();
    await expect(page.getByText("利用規約およびプライバシーポリシーへの同意が必要です")).toBeVisible();
    expect(posted).toHaveLength(0);

    // 同意後は登録 API に agreed_terms: true と版数（YYYY-MM-DD）が載る。
    await agree.check();
    await page.getByRole("button", { name: /登録する/ }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({ agreed_terms: true });
    expect(String(posted[0].terms_version)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  for (const path of ["/signup", "/login"]) {
    test(`${path}: LINE ボタンは同意チェック前は押せず、チェック後に押せる`, async ({ page }) => {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      const lineButton = page.locator(".btn-line-auth");
      await expect(lineButton).toBeVisible();
      await expect(lineButton).toBeDisabled();

      await page.locator(".line-consent__cb").check();
      await expect(lineButton).toBeEnabled();

      await page.locator(".line-consent__cb").uncheck();
      await expect(lineButton).toBeDisabled();
    });
  }
});

test.describe("運営の代理閲覧は読み取り専用", () => {
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

  test("依頼者の案件詳細: 入力欄・減額の承認却下・日程の確定ボタンが出ない", async ({ page }) => {
    const txn = await ensureLiveTransaction(api, sellerToken, vendor);
    await loginAsUser(page, ACCOUNTS.admin, `/cases/${txn.case_id}`);

    await expect(page.getByTestId("chat-read-only")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByLabel("メッセージを入力")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "承認する" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "却下する" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /で確定$/ })).toHaveCount(0);
  });

  test("業者のチャット: 運営は /operator/* に入れず /forbidden へ戻される（業者の画面を運営が操作できない）", async ({ page }) => {
    const txn = await ensureLiveTransaction(api, sellerToken, vendor);
    await loginAsUser(page, ACCOUNTS.admin, `/operator/chat/${txn.id}`);

    await page.waitForURL(/\/forbidden/, { timeout: 30_000 });
    await expect(page.getByLabel("メッセージを入力")).toHaveCount(0);
  });
});
