/**
 * 運営（role=admin）が依頼者・業者向け画面を開いているときの「代理閲覧」判定（React 非依存）。
 * ペルソナ監査 H-3: 運営が「ユーザー画面で開く」から依頼者向け画面をそのまま操作できるのに、
 * 運営として見ている旨の表示が無く、確定系の操作を依頼者本人のものと取り違える危険があった。
 */

/** 依頼者・業者向けのログイン後画面（/admin 自体と認証画面・公開ページは含めない）。 */
export const PROXY_VIEW_PREFIXES = [
  "/cases",
  "/chat",
  "/mypage",
  "/applications",
  "/notifications",
  "/business",
  "/vendors",
  "/schedule",
  "/review",
  "/result",
  // 運営が業者・依頼者の画面を見ているときは必ず帯を出す（QA L4）。
  "/operator",
  "/create",
] as const;

/** 上の接頭辞配下でも帯を出さない認証画面（業者のログイン・登録などは代理閲覧ではない）。 */
export const PROXY_VIEW_EXCLUDED_PREFIXES = ["/operator/login", "/operator/signup"] as const;

/** 運営が代理で送信できない（入力欄を無効にする）チャット系の画面。 */
export const PROXY_CHAT_PREFIXES = ["/chat", "/cases", "/operator/chat"] as const;

function matchesPrefix(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/** 代理閲覧の帯を出すか。role が "admin" で、依頼者・業者向けの画面のときだけ true。 */
export function shouldShowProxyBanner(pathname: string | null | undefined, role: string | null | undefined): boolean {
  if (role !== "admin" || !pathname) return false;
  if (matchesPrefix(pathname, PROXY_VIEW_EXCLUDED_PREFIXES)) return false;
  return matchesPrefix(pathname, PROXY_VIEW_PREFIXES);
}

/** チャットの入力欄を無効にして「代理で送信できません」を示すか。 */
export function shouldDisableChatInput(pathname: string | null | undefined, role: string | null | undefined): boolean {
  if (role !== "admin" || !pathname) return false;
  return matchesPrefix(pathname, PROXY_CHAT_PREFIXES);
}
