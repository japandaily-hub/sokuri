/**
 * LINE通知連携（後付け連携）コールバックエンドポイント。
 * start/route.ts が積んだ state/reauth_token cookie を検証し、認可コードを
 * LINEのaccess_tokenへ交換したうえで、バックエンド /auth/line/exchange と突合する。
 *
 * どの分岐でも生JSONは返さず /notifications への302リダイレクトに統一する
 * （リダイレクト先: ?linked=1 / ?error=already_linked|reauth_required|link_failed）。
 * 使用したcookie（state・reauth_token）はどの分岐でも必ず破棄する。
 */

import crypto from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { auth } from "@/auth";
import {
  LINE_LINK_REAUTH_COOKIE,
  LINE_LINK_STATE_COOKIE,
  exchangeLineCodeForAccessToken,
  getAppBaseUrl,
  linkLineToCurrentUser,
  lineLinkRedirectUri,
} from "@/lib/line-link";

/** state比較。長さが異なる場合はtimingSafeEqual自体が例外を投げるため、事前にlengthチェックする。 */
function isValidState(expected: string, actual: string): boolean {
  const expectedBuf = Buffer.from(expected, "utf8");
  const actualBuf = Buffer.from(actual, "utf8");
  if (expectedBuf.length !== actualBuf.length) return false;
  return crypto.timingSafeEqual(expectedBuf, actualBuf);
}

function redirectWithCookiesCleared(req: NextRequest, query: string) {
  const res = NextResponse.redirect(new URL(`/notifications${query}`, req.url));
  res.cookies.delete(LINE_LINK_STATE_COOKIE);
  res.cookies.delete(LINE_LINK_REAUTH_COOKIE);
  return res;
}

/**
 * 失敗分岐をサーバーログに残してからリダイレクトする。
 * ユーザーに見えるのは単一の「LINE連携に失敗しました」バナーのみで、どの段階で
 * 落ちたのかを運用側から一切追跡できなかったため（2026-09-02の不具合調査で判明）、
 * 分岐ごとの reason を必ず記録する。code/state/トークン等の秘匿値は出力しない。
 */
function failWithLog(req: NextRequest, reason: string, query = "?error=link_failed") {
  console.error("[line-link/callback] 連携失敗: reason=%s", reason);
  return redirectWithCookiesCleared(req, query);
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const lineError = params.get("error");
  const code = params.get("code");
  const returnedState = params.get("state");

  const storedState = req.cookies.get(LINE_LINK_STATE_COOKIE)?.value ?? null;
  const reauthToken = req.cookies.get(LINE_LINK_REAUTH_COOKIE)?.value ?? null;

  // LINE側でユーザーが拒否した場合等、認可コード自体が発行されないケース。
  if (lineError) return failWithLog(req, `line_error=${lineError}`);
  if (!code) return failWithLog(req, "no_code");
  if (!returnedState) return failWithLog(req, "no_state_param");
  // state cookie 欠落は「別ブラウザで開いた / cookieが5分で失効した / SameSite阻害」を示す。
  if (!storedState) return failWithLog(req, "no_state_cookie");

  // CSRF対策: state不一致（cookie未保持・改ざん・別セッションからの使い回し等）は即失敗させる。
  if (!isValidState(storedState, returnedState)) {
    return failWithLog(req, "state_mismatch");
  }

  const session = await auth();
  if (!session?.accessToken) {
    return failWithLog(req, "no_session");
  }

  const appBaseUrl = getAppBaseUrl();
  if (!appBaseUrl) {
    return failWithLog(req, "no_app_base_url", "?error=line_unavailable");
  }

  // start側と完全に同じ redirect_uri でないとLINE側のトークン交換が失敗するため、同じ組み立て関数を使う。
  const redirectUri = lineLinkRedirectUri(appBaseUrl);
  const lineAccessToken = await exchangeLineCodeForAccessToken(code, redirectUri);
  if (!lineAccessToken) {
    return failWithLog(req, "token_exchange_failed");
  }

  const result = await linkLineToCurrentUser(session.accessToken, lineAccessToken, reauthToken);
  switch (result.outcome) {
    case "linked":
      return redirectWithCookiesCleared(req, "?linked=1");
    case "already_linked":
      return redirectWithCookiesCleared(req, "?error=already_linked");
    case "reauth_required":
      return redirectWithCookiesCleared(req, "?error=reauth_required");
    case "unavailable":
      return failWithLog(req, "backend_line_not_configured", "?error=line_unavailable");
    default:
      return failWithLog(req, "backend_exchange_failed");
  }
}
