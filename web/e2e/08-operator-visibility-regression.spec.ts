/**
 * (8) 業者の閲覧ゲート・入札情報開示の回帰（r12 レビュー L-4）。
 *   8-1 審査中業者（pending@example.com）は /operator/cases を開くと承認待ちの案内が出て
 *       案件が一覧表示されない（API は 403 approval_required）。
 *   8-2 業者（vendor@example.com）の案件詳細・一覧に他社の入札額・順位が表示されない。
 *       旧モック実装（ae7336f、実API配線前）は「現在の最高入札」「入札首位」で他社の
 *       金額・順位をそのまま業者に見せていた。実配線後は自社入札があれば自社の状況のみ、
 *       無ければ「入札 n 件（他社）」という集計件数のみを示す仕様のため、この回帰を防ぐ。
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

test("業者の案件詳細・一覧に他社の入札額・順位（最高入札額／首位）が表示されない", async ({ page }) => {
  // 自社が入札済みの案件: 詳細ページは「自社の入札」カードのみを表示し、他社の金額・順位には触れない。
  const { caseId: ownBidCaseId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);
  await loginAsOperator(page, ACCOUNTS.vendor, `/operator/cases/${ownBidCaseId}`);
  await expect(page.getByText(/自社の入札/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/最高入札|首位/)).toHaveCount(0);

  // 自社が未入札で他社の入札が付いている案件: 一覧は「入札 n 件（他社）」の集計件数のみを
  // 示し、金額・順位（最高入札額／首位）は出さない。既存データに見つからない場合のみ
  // 新規案件を作る（AI解析のレート上限があるため最後の手段）。
  const rival = await api.loginOperator(ACCOUNTS.rival);
  const cases = await api.listCases(sellerToken);
  let otherBidCaseId: string | null = null;
  for (const c of cases) {
    if (c.status !== "open" && c.status !== "bidding") continue;
    const detail: CaseDetail = await api.getCase(c.id, sellerToken);
    const hasVendorBid = detail.bids?.some((b) => b.operator?.id === vendor.operatorId);
    const hasOtherBid = detail.bids?.some((b) => b.operator?.id && b.operator.id !== vendor.operatorId);
    if (!hasVendorBid && hasOtherBid) {
      otherBidCaseId = c.id;
      break;
    }
  }
  if (!otherBidCaseId) {
    const created = await api.createCase(sellerToken, ["食器棚"]);
    await api.createBid(created.id, 28000, "E2E: 検証用（他社入札の集計件数表示を確認）", rival.token);
    otherBidCaseId = created.id;
  }

  await page.goto("/operator/cases");
  const card = page.locator(`a.lot-card[href="/operator/cases/${otherBidCaseId}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByText(/入札\s*\d+\s*(件|社)/)).toBeVisible();
  await expect(card.getByText(/最高入札|首位/)).toHaveCount(0);
});
