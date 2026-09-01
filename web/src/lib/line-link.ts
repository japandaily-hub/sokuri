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
 *
 * 優先順位:
 *   1. APP_BASE_URL（正本。カスタムドメイン運用時は必ずこちらを設定する）
 *   2. VERCEL_PROJECT_PRODUCTION_URL（Vercelのシステム環境変数。プレビュー環境でも
 *      常に「本番ドメイン」を返す固定値で、Hostヘッダ由来ではないため偽装できない）
 * どちらも無ければ null を返し、呼び出し側で「未構成」として扱う（fail-safe）。
 *
 * 2. にフォールバックした場合は警告ログを残す。APP_BASE_URL の設定漏れは
 * 「LINE連携が無言で失敗し続ける」形でしか表面化しなかったため（2026-09-02の不具合）、
 * サーバーログで気付けるようにする。
 */
export function getAppBaseUrl(): string | null {
  const explicit = process.env.APP_BASE_URL;
  if (explicit) return explicit.replace(/\/$/, "");

  const vercelProdHost = process.env.VERCEL_PROJECT_PRODUCTION_URL;
  if (vercelProdHost) {
    console.warn(
      "[line-link] APP_BASE_URL が未設定のため VERCEL_PROJECT_PRODUCTION_URL にフォールバックしました。" +
        " LINE Developers Console の Callback URL と一致しているか確認してください: host=%s",
      vercelProdHost,
    );
    return `https://${vercelProdHost.replace(/\/$/, "")}`;
  }
  return null;
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
  if (!clientId || !clientSecret) {
    console.error("[line-link] token交換不可: LINE_CLIENT_ID / LINE_CLIENT_SECRET が未設定です");
    return null;
  }

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
    if (!res.ok) {
      // LINE側のエラーは原因特定に直結する（invalid_grant=code再利用/期限切れ、
      // invalid_request=redirect_uri不一致 等）。認可コード自体は残さない。
      const body = await res.text().catch(() => "");
      console.error(
        "[line-link] LINE token交換に失敗: status=%s redirect_uri=%s body=%s",
        res.status,
        redirectUri,
        body.slice(0, 500),
      );
      return null;
    }
    const data = (await res.json()) as { access_token?: unknown };
    if (typeof data.access_token !== "string") {
      console.error("[line-link] LINE token応答に access_token が含まれていません");
      return null;
    }
    return data.access_token;
  } catch (e) {
    console.error("[line-link] LINE token交換で例外: %s", e);
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
  /** バックエンドがLINE機能を未構成として拒否（503）。再試行しても回復しない。 */
  | { outcome: "unavailable" }
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
    // 503 = バックエンドの LINE_CLIENT_ID 未設定（_LINE_NOT_CONFIGURED）。
    // 「時間をおいて再試行」では永久に回復しないため、failed と区別して扱う。
    if (res.status === 503) {
      console.error(
        "[line-link] バックエンドがLINE未構成のため連携を拒否（503）。" +
          " Render の環境変数 LINE_CLIENT_ID を設定してください。",
      );
      return { outcome: "unavailable" };
    }
    const body = await res.text().catch(() => "");
    console.error(
      "[line-link] /auth/line/exchange が想定外の応答: status=%s body=%s",
      res.status,
      body.slice(0, 500),
    );
    return { outcome: "failed" };
  } catch (e) {
    console.error("[line-link] /auth/line/exchange の呼び出しで例外: %s", e);
    return { outcome: "failed" };
  }
}
