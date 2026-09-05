/**
 * 画面操作の共通ヘルパー。
 *
 * セレクタは data-testid を足さない方針。role / 表示文言で引き、文言変更に弱い
 * ところは正規表現で緩める（設計方針は docs/ops/e2e.md）。
 */
import { Page, expect } from "@playwright/test";

import { Account } from "./env";

/** ログインフォーム（依頼者 /login・業者 /operator/login・運営 /login 共通の作り）。 */
async function submitLoginForm(page: Page, account: Account): Promise<void> {
  await page.locator('input[type="email"]').fill(account.email);
  await page.locator('input[type="password"]').fill(account.password);
  await page.locator('button[type="submit"]').click();
}

/** 依頼者（および運営）としてログインし、遷移完了まで待つ。 */
export async function loginAsUser(page: Page, account: Account, expectPath = "/cases"): Promise<void> {
  await page.goto("/login");
  await submitLoginForm(page, account);
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 });
  if (expectPath) {
    // 遷移先が callbackUrl 依存で揺れるため、ログイン画面を抜けたことだけを必須とし
    // 目的のパスへは明示遷移する。
    await page.goto(expectPath);
  }
}

/** 業者としてログインする。 */
export async function loginAsOperator(page: Page, account: Account, expectPath = "/operator"): Promise<void> {
  await page.goto("/operator/login");
  await submitLoginForm(page, account);
  await page.waitForURL((url) => !url.pathname.startsWith("/operator/login"), { timeout: 30_000 });
  if (expectPath) await page.goto(expectPath);
}

/**
 * 共通 ConfirmModal（components/kdz/ConfirmModal.tsx, role="dialog"）を確定する。
 * `titlePattern` でどのモーダルかを特定してから確定ボタンを押す。
 */
export async function confirmModal(page: Page, titlePattern: RegExp, confirmLabel: string | RegExp): Promise<void> {
  const dialog = page.getByRole("dialog").filter({ hasText: titlePattern });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: confirmLabel }).click();
  await expect(dialog).toBeHidden({ timeout: 30_000 });
}

/** ページの横スクロール（scrollWidth > clientWidth）が出ていないことを検証する。 */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const el = document.documentElement;
    return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
  });
  // 1px の丸め差はブラウザ実装差で出るため許容する。
  expect(
    overflow.scrollWidth - overflow.clientWidth,
    `横スクロールが発生している（scrollWidth=${overflow.scrollWidth} / clientWidth=${overflow.clientWidth}）`,
  ).toBeLessThanOrEqual(1);
}

/**
 * console error の収集を開始する。返り値を呼ぶと収集済みのエラー配列が得られる。
 * 外部要因（画像 404 等のネットワーク由来）で不安定にならないよう、
 * リソース読み込み失敗は除外して JS 例外・console.error のみを対象とする。
 */
export function collectConsoleErrors(page: Page): () => string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (/Failed to load resource|net::ERR_|favicon/i.test(text)) return;
    errors.push(text);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return () => errors;
}
