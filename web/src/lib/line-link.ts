/**
 * LINE通知連携（後付け連携/解除）— サーバー専用ヘルパー。
 * app/api/line/link/{start,callback}/route.ts から共有利用する。
 *
 * 既存の signIn("line") フロー（auth.ts）は「未ログイン時の新規登録/ログイン」専用のため、
 * こちらは別経路: ログイン済みユーザーが後から通知用にLINEを紐付ける OAuth Authorization Code
 * フローを独自に実装する（NextAuthのLINE providerとは独立）。
 *
 * state・reauth_token は共に短命 httpOnly cookie で受け渡す（CSRF対策 / 誤操作防止）。
 */

const LINE_AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize";
const LINE_TOKEN_URL = "https://api.line.me/oauth2/v2.1/token";

/** state/reauth_token cookie の生存期間（秒）。OAuth往復が長引くケースを見込み5分。 */
export const LINE_LINK_COOKIE_MAX_AGE = 60 * 5;

export const LINE_LINK_STATE_COOKIE = "kdz_line_link_state";
export const LINE_LINK_REAUTH_COOKIE = "kdz_line_link_reauth";

/**
 * アプリの公開ベースURL（末尾スラッシュなし）。
 * LINEのredirect_uriはLINE Developers Console側に事前登録した固定値と完全一致させる必要があるため、
 * リクエストのHostヘッダ（偽装可能）ではなく環境変数から組み立てる。
 * 未設定時は null を返し、呼び出し側で link_failed 扱いにする（fail-safe）。
 */
export function getAppBaseUrl(): string | null {
  const url = process.env.APP_BASE_URL;
  if (!url) return null;
  return url.replace(/\/$/, "");
}

/** LINE連携コールバックのredirect_uri（start/callback 両方で同一値を使う必要がある）。 */
export function lineLinkRedirectUri(appBaseUrl: string): string {
  return `${appBaseUrl}/api/line/link/callback`;
}

/** LINE authorize URL を組み立てる。LINE_CLIENT_ID未設定時は null（fail-safe）。 */
export function buildLineAuthorizeUrl(state: string, redirectUri: string): string | null {
  const clientId = process.env.LINE_CLIENT_ID;
  if (!clientId) return null;
  const params = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri,
    state,
    scope: "profile openid",
  });
  return `${LINE_AUTHORIZE_URL}?${params.toString()}`;
}

/**
 * 認可コードをLINEのaccess_tokenへ交換する。
 * @returns 成功時はaccess_token、失敗時（LINE_CLIENT_SECRET未設定・LINE側エラー含む）は null。
 */
export async function exchangeLineCodeForAccessToken(
  code: string,
  redirectUri: string,
): Promise<string | null> {
  const clientId = process.env.LINE_CLIENT_ID;
  const clientSecret = process.env.LINE_CLIENT_SECRET;
  if (!clientId || !clientSecret) return null;

  try {
    const res = await fetch(LINE_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        code,
        redirect_uri: redirectUri,
        client_id: clientId,
        client_secret: clientSecret,
      }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { access_token?: unknown };
    return typeof data.access_token === "string" ? data.access_token : null;
  } catch {
    return null;
  }
}

/** バックエンド API のベース URL。auth.ts の apiBase() と同じ優先順位（サーバー専用: API_URL優先）。 */
function backendApiBase(): string {
  const FALLBACK_PROD_API_URL = "https://sokuri-backend.onrender.com/api/v1";
  const url =
    process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? FALLBACK_PROD_API_URL;
  return url.replace(/\/$/, "");
}

export type LineExchangeResult =
  | { outcome: "linked" }
  | { outcome: "already_linked" }
  | { outcome: "reauth_required" }
  | { outcome: "failed" };

/**
 * ログイン済みユーザーのLINE後付け連携。バックエンド POST /auth/line/exchange を
 * Bearer(セッションのaccessToken) 付きで呼び出す（未ログイン時の新規登録/ログイン用の
 * auth.ts側 backendLineExchange とは呼び出し方が異なる＝別関数として分離）。
 */
export async function linkLineToCurrentUser(
  sessionAccessToken: string,
  lineAccessToken: string,
  reauthToken: string | null,
): Promise<LineExchangeResult> {
  try {
    const res = await fetch(`${backendApiBase()}/auth/line/exchange`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${sessionAccessToken}`,
      },
      body: JSON.stringify({
        line_access_token: lineAccessToken,
        reauth_token: reauthToken ?? undefined,
      }),
    });
    if (res.status === 200) return { outcome: "linked" };
    if (res.status === 409) return { outcome: "already_linked" };
    if (res.status === 401) return { outcome: "reauth_required" };
    return { outcome: "failed" };
  } catch {
    return { outcome: "failed" };
  }
}
