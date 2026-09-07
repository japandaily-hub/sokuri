/**
 * (8) 業者の閲覧ゲート・入札情報開示・入札額の引き上げ（r12 レビュー L-4 → 2026-09-07 方針転換）。
 *   8-1 審査中業者（pending@example.com）は /operator/cases を開くと承認待ちの案内が出て
 *       案件が一覧表示されない（API は 403 approval_required）。
 *   8-2 業者（vendor@example.com）の案件詳細に他社の入札額が**匿名で**表示され、他社の社名・
 *       コメントは表示されない（2026-09-07 決定: 金額のみ開示。旧 r12 決定2「非開示」を撤回）。
 *   8-3 業者は自社の入札額を引き上げられる（引き上げのみ・現在額+1,000 円以上）。下回る金額は
 *       サーバーが 409 で拒否し、画面にその理由が出る。
 */
import { test, expect } from "@playwright/test";

import { Api, CaseDetail, OperatorSession, loginAll } from "./helpers/api";
import { ACCOUNTS, API_URL } from "./helpers/env";
import { ensureOpenCaseWithBid } from "./helpers/fixtures";
import { loginAsOperator } from "./helpers/ui";

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

test("審査中業者は /operator/cases で承認待ちの案内が出て案件が表示されない（API は403）", async ({ page }) => {
  // 06 の 429 テストが seed の pending 口座のログイン試行を使い切るため、使い捨ての審査中業者を自己登録して使う。
  const pendingAccount = { email: `e2e-pending-${Date.now()}@example.com`, password: "Pending-E2E-2026" };
  await api.signupOperator(pendingAccount);
  const pending = await api.loginOperator(pendingAccount);
  const res = await api.raw().get(`${API_URL}/cases`, {
    headers: { Authorization: `Bearer ${pending.token}` },
  });
  expect(res.status()).toBe(403);
  const body = (await res.json().catch(() => null)) as { detail?: { code?: string } } | null;
  expect(body?.detail?.code).toBe("approval_required");

  await loginAsOperator(page, pendingAccount, "/operator/cases");
  await expect(page.getByText(/審査|許可証/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".lot-card")).toHaveCount(0);
});

test("業者の案件詳細に他社の入札額が匿名で表示され、他社の社名・コメントは表示されない", async ({ page }) => {
  // 自社（vendor）と他社（rival）の両方が入札した案件を用意する。
  const { caseId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);
  const rival = await api.loginOperator(ACCOUNTS.rival);
  const detail: CaseDetail = await api.getCase(caseId, sellerToken);
  const rivalBid = detail.bids?.find((b) => b.operator?.id === rival.operatorId);
  const rivalMessage = "E2E: 他社コメント（業者画面に出てはいけない）";
  let rivalAmount = rivalBid?.amount ?? 0;
  if (!rivalBid) {
    rivalAmount = 28_000;
    await api.createBid(caseId, rivalAmount, rivalMessage, rival.token);
  }
  const rivalCompanyName = (await api.raw().get(`${API_URL}/operator/me`, {
    headers: { Authorization: `Bearer ${rival.token}` },
  }).then((r) => r.json()).catch(() => ({}))) as { company_name?: string };

  // API: 業者から見た入札一覧は他社分の operator / message が null、amount はある。
  const bidsRes = await api.raw().get(`${API_URL}/cases/${caseId}/bids`, {
    headers: { Authorization: `Bearer ${vendor.token}` },
  });
  expect(bidsRes.status()).toBe(200);
  const bids = (await bidsRes.json()) as Array<{ amount: number; operator: unknown; message: string | null; is_mine: boolean }>;
  const others = bids.filter((b) => !b.is_mine);
  expect(others.length).toBeGreaterThanOrEqual(1);
  for (const b of others) {
    expect(b.operator).toBeNull();
    expect(b.message).toBeNull();
    expect(b.amount).toBeGreaterThan(0);
  }

  // UI: 「現在の最高額」と他社の金額は見えるが、他社の社名・コメントは出ない。
  await loginAsOperator(page, ACCOUNTS.vendor, `/operator/cases/${caseId}`);
  await expect(page.getByText(/自社の入札/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/現在の最高額/)).toBeVisible();
  await expect(page.getByText(rivalMessage)).toHaveCount(0);
  if (rivalCompanyName.company_name) {
    await expect(page.locator("main").getByText(rivalCompanyName.company_name, { exact: true })).toHaveCount(0);
  }
});

test("業者は自社の入札額を引き上げられる（下回る金額は 409 で拒否）", async ({ page }) => {
  const { caseId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);
  const before = (await api.getCase(caseId, sellerToken)).bids?.find(
    (b) => b.status === "pending" && b.operator?.id === vendor.operatorId,
  );
  expect(before).toBeTruthy();
  const current = before!.amount;

  // API: 現在額以下は 409。
  const lower = await api.raw().patch(`${API_URL}/cases/${caseId}/bids/me`, {
    headers: { Authorization: `Bearer ${vendor.token}`, "Content-Type": "application/json" },
    data: { amount: current },
  });
  expect(lower.status()).toBe(409);

  // API: +1,000 円以上は 200 で revision_count が増える。
  const raised = await api.raw().patch(`${API_URL}/cases/${caseId}/bids/me`, {
    headers: { Authorization: `Bearer ${vendor.token}`, "Content-Type": "application/json" },
    data: { amount: current + 1_000 },
  });
  expect(raised.status()).toBe(200);
  const raisedBody = (await raised.json()) as { amount: number; revision_count: number };
  expect(raisedBody.amount).toBe(current + 1_000);
  expect(raisedBody.revision_count).toBeGreaterThanOrEqual(1);

  // UI: 引き上げフォームから更に +1,000 円。確認モーダルを通って反映される。
  await loginAsOperator(page, ACCOUNTS.vendor, `/operator/cases/${caseId}`);
  await expect(page.getByText(/自社の入札/)).toBeVisible({ timeout: 30_000 });
  const heading = page.getByText(/入札額を引き上げる/).first();
  await expect(heading).toBeVisible();
  const next = current + 2_000;
  const raiseForm = page.locator("form", { has: page.getByRole("button", { name: "この金額に引き上げる" }) });
  await raiseForm.locator('input[type="number"]').first().fill(String(next));
  await raiseForm.getByRole("button", { name: "この金額に引き上げる" }).click();
  // ConfirmModal（「入札額を引き上げますか？」→「引き上げる」）
  await page.getByRole("dialog").getByRole("button", { name: "引き上げる" }).click();
  await expect(page.getByText(/入札額を引き上げました/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(new RegExp(next.toLocaleString("ja-JP"))).first()).toBeVisible();
  // 任意: E2E_SCREENSHOT_DIR が指定されていれば、引き上げ後の業者画面を保存する（レビュー・報告用）。
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/operator-bid-raise-${test.info().project.name}.png`, fullPage: true });
  }

  // 依頼者側の入札一覧にも更新後の金額と「更新あり」が出る。
  const after = (await api.getCase(caseId, sellerToken)).bids?.find((b) => b.operator?.id === vendor.operatorId);
  expect(after?.amount).toBe(next);
});
