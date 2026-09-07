/**
 * (99) モバイル表示の視覚監査用スクリーンショット収集（通常の E2E では実行しない）。
 *   E2E_AUDIT_DIR に保存先を指定したときだけ動く。依頼者・業者・運営・公開ページを
 *   375px 幅でフルページ撮影し、改行・折返し・余白のバランス確認に使う。
 *   実行例: E2E_AUDIT_DIR=C:/tmp/shots npx playwright test e2e/99-mobile-audit.spec.ts --project=mobile
 */
import { test } from "@playwright/test";

import { Api, loginAll, OperatorSession } from "./helpers/api";
import { ACCOUNTS } from "./helpers/env";
import { ensureOpenCaseWithBid } from "./helpers/fixtures";
import { loginAsOperator, loginAsUser } from "./helpers/ui";

const DIR = process.env.E2E_AUDIT_DIR;
test.skip(!DIR, "E2E_AUDIT_DIR 未指定のためスキップ（視覚監査専用）");

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

/** 1枚あたりの高さ（px）。長いページは目視できる大きさに分割して保存する。 */
const CHUNK = 1400;

async function shot(page: import("@playwright/test").Page, name: string, path: string): Promise<void> {
  await page.goto(path, { waitUntil: "networkidle" }).catch(() => page.goto(path));
  await page.waitForTimeout(800);
  // 監査用: スクロール連動の表示（.rv → .in）と遅延読込画像を強制的に表示状態にしてから撮る
  // （実ユーザーはスクロールで自然に表示されるが、フルページ撮影では未発火のまま空白になる）。
  await page.addStyleTag({ content: ".rv{opacity:1!important;transform:none!important;transition:none!important}" });
  await page.evaluate(async () => {
    document.querySelectorAll<HTMLImageElement>("img[loading='lazy']").forEach((img) => {
      img.loading = "eager";
    });
    const step = 600;
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
    window.scrollTo(0, 0);
    await new Promise((r) => setTimeout(r, 600));
  });
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  if (height <= CHUNK * 1.5) {
    await page.screenshot({ path: `${DIR}/${name}.png`, fullPage: true });
    return;
  }
  const chunks = Math.ceil(height / CHUNK);
  for (let i = 0; i < chunks; i++) {
    await page.screenshot({
      path: `${DIR}/${name}-${String(i + 1).padStart(2, "0")}.png`,
      fullPage: true,
      clip: { x: 0, y: i * CHUNK, width: 375, height: Math.min(CHUNK, height - i * CHUNK) },
    });
  }
}

test("公開ページ", async ({ page }) => {
  for (const [name, path] of [
    ["pub-home", "/"],
    ["pub-business", "/business"],
    ["pub-faq", "/faq"],
    ["pub-vendors", "/vendors"],
    ["pub-examples", "/examples"],
    ["pub-company", "/company"],
    ["pub-terms", "/terms"],
    ["pub-privacy", "/privacy"],
    ["pub-legal", "/legal"],
    ["pub-contact", "/contact"],
    ["pub-photo-guide", "/photo-guide"],
    ["pub-login", "/login"],
    ["pub-signup", "/signup"],
    ["pub-operator-login", "/operator/login"],
    ["pub-operator-signup", "/operator/signup"],
    ["pub-applications", "/applications"],
  ] as const) {
    await shot(page, name, path);
  }
});

test("依頼者", async ({ page }) => {
  const { caseId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);
  const txns = await api.listTransactions(sellerToken);
  await loginAsUser(page, ACCOUNTS.seller, "/cases");
  await shot(page, "user-cases", "/cases");
  await shot(page, "user-case-detail", `/cases/${caseId}`);
  await shot(page, "user-create", "/create");
  await shot(page, "user-mypage", "/mypage");
  await shot(page, "user-profile", "/mypage/profile");
  await shot(page, "user-identity", "/mypage/identity");
  await shot(page, "user-bank", "/mypage/bank-account");
  await shot(page, "user-notifications", "/notifications");
  if (txns[0]) {
    await shot(page, "user-chat", `/chat/${txns[0].id}`);
  }
});

test("業者", async ({ page }) => {
  const { caseId } = await ensureOpenCaseWithBid(api, sellerToken, vendor);
  const txns = await api.listTransactions(vendor.token);
  await loginAsOperator(page, ACCOUNTS.vendor, "/operator");
  await shot(page, "op-dashboard", "/operator");
  await shot(page, "op-cases", "/operator/cases");
  await shot(page, "op-case-detail", `/operator/cases/${caseId}`);
  await shot(page, "op-transactions", "/operator/transactions");
  await shot(page, "op-profile", "/operator/profile");
  if (txns[0]) {
    await shot(page, "op-transaction-detail", `/operator/transactions/${txns[0].id}`);
    await shot(page, "op-chat", `/operator/chat/${txns[0].id}`);
  }
});

test("運営", async ({ page }) => {
  await loginAsUser(page, ACCOUNTS.admin, "/admin");
  for (const [name, path] of [
    ["admin-home", "/admin"],
    ["admin-cases", "/admin/cases"],
    ["admin-transactions", "/admin/transactions"],
    ["admin-users", "/admin/users"],
    ["admin-contacts", "/admin/contacts"],
    ["admin-applications", "/admin/operator-applications"],
    ["admin-identity", "/admin/identity-documents"],
  ] as const) {
    await shot(page, name, path);
  }
});
