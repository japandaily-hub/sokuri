/**
 * NextAuth.js (v5) 設定 — カタヅケ認証。
 *
 * バックエンド（FastAPI）が JWT を発行し、NextAuth はそれをセッション
 * （JWT strategy）に保持する。API 呼び出し時は session.accessToken を
 * Authorization: Bearer で送る。
 *
 * - user-credentials     : ユーザー（email + password）→ /auth/login
 * - operator-credentials : 業者（email + password）→ /auth/operator/login
 *   ※ 業者の新規登録（招待コード）は /operator/signup ページから
 *     バックエンド /auth/operator/signup を直接呼んだ後に signIn する。
 * - line                 : LINEログイン（未ログイン時の新規登録/ログインのみ対応）。
 *   LINE_CLIENT_ID/LINE_CLIENT_SECRET が両方設定されている場合のみ有効化される
 *   （未設定時はプロバイダを登録しないfail-safe設計）。
 *   signIn コールバックで LINE の access_token を
 *   バックエンド /auth/line/exchange と交換し、既存 Credentials provider と
 *   同じ形の user オブジェクトに正規化して jwt コールバックへ渡す。
 *   ログイン済みユーザーの後付け連携（Bearer 付きexchange）は今回スコープ外。
 *   業者（Operator）のLINE単独新規作成はバックエンド側で行われない。
 */

import NextAuth, { CredentialsSignin } from "next-auth";
import Credentials from "next-auth/providers/credentials";
import LINE from "next-auth/providers/line";
import type { Provider } from "next-auth/providers";

export type AccountType = "user" | "operator";

interface BackendAuthResponse {
  access_token: string;
  account_type: AccountType;
  user?: { id: string; email: string; name: string | null; role: string };
  operator?: {
    id: string;
    company_name: string;
    contact_email: string;
    verified_at: string | null;
  };
}

const FALLBACK_PROD_API_URL = "https://sokuri-backend.onrender.com/api/v1";

function apiBase(): string {
  const url =
    process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? FALLBACK_PROD_API_URL;
  return url.replace(/\/$/, "");
}

/**
 * r3 セキュリティレビュー R-M1 是正: 停止アカウントのログインを
 * 「メールアドレスまたはパスワードが正しくありません」と誤表示しないための専用エラー。
 * NextAuth v5 の仕様（CredentialsSignin を継承し code を設定）に従う。
 * signIn({ redirect: false }) の戻り値で result.code === "account_suspended" として拾える。
 */
class AccountSuspendedError extends CredentialsSignin {
  code = "account_suspended";
}

async function backendLogin(
  path: "/auth/login" | "/auth/operator/login",
  email: string,
  password: string,
): Promise<BackendAuthResponse | null> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    return null;
  }
  if (res.status === 403) {
    // backend は依頼者・業者どちらの停止も 403 { detail: { code: "account_suspended" } } を返す。
    let detailCode: unknown;
    try {
      const body = (await res.json()) as { detail?: { code?: unknown } };
      detailCode = body?.detail?.code;
    } catch {
      /* JSON でないレスポンスは無視し、通常の認証失敗として扱う */
    }
    if (detailCode === "account_suspended") throw new AccountSuspendedError();
    return null;
  }
  if (!res.ok) return null;
  try {
    return (await res.json()) as BackendAuthResponse;
  } catch {
    return null;
  }
}

/**
 * LINEのアクセストークンをバックエンドJWTへ交換する。
 * 未ログイン時の新規登録/ログインのみが対象（Bearerヘッダは付けない）。
 * @param lineAccessToken LINE OAuthで取得したアクセストークン
 * @returns 交換成功時はバックエンドの認証レスポンス、失敗時は null
 */
async function backendLineExchange(
  lineAccessToken: string,
): Promise<BackendAuthResponse | null> {
  try {
    const res = await fetch(`${apiBase()}/auth/line/exchange`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ line_access_token: lineAccessToken }),
    });
    if (!res.ok) return null;
    return (await res.json()) as BackendAuthResponse;
  } catch {
    return null;
  }
}

/** LINE_CLIENT_ID/LINE_CLIENT_SECRET が両方設定されている場合のみプロバイダを構成する。 */
function buildProviders(): Provider[] {
  const providers: Provider[] = [
    Credentials({
      id: "user-credentials",
      name: "ユーザーログイン",
      credentials: { email: {}, password: {} },
      async authorize(credentials) {
        const email = String(credentials?.email ?? "");
        const password = String(credentials?.password ?? "");
        if (!email || !password) return null;
        const data = await backendLogin("/auth/login", email, password);
        if (!data?.user) return null;
        return {
          id: data.user.id,
          email: data.user.email,
          name: data.user.name ?? data.user.email,
          accessToken: data.access_token,
          accountType: "user" as const,
          role: data.user.role,
        };
      },
    }),
    Credentials({
      id: "operator-credentials",
      name: "業者ログイン",
      credentials: { email: {}, password: {} },
      async authorize(credentials) {
        const email = String(credentials?.email ?? "");
        const password = String(credentials?.password ?? "");
        if (!email || !password) return null;
        const data = await backendLogin("/auth/operator/login", email, password);
        if (!data?.operator) return null;
        return {
          id: data.operator.id,
          email: data.operator.contact_email,
          name: data.operator.company_name,
          accessToken: data.access_token,
          accountType: "operator" as const,
          role: "operator",
          verified: data.operator.verified_at != null,
        };
      },
    }),
  ];

  if (process.env.LINE_CLIENT_ID && process.env.LINE_CLIENT_SECRET) {
    providers.push(
      LINE({
        clientId: process.env.LINE_CLIENT_ID,
        clientSecret: process.env.LINE_CLIENT_SECRET,
      }),
    );
  }

  return providers;
}

/**
 * backend JWT の有効期限（config.py の jwt_expire_minutes = 60*24*7 = 7日）と揃える。
 * 根本対策は katadzuke-api.ts の 401 共通ハンドリング（signOut→再ログイン誘導）であり、
 * これは補助（NextAuthセッションだけが独り歩きして「見た目はログイン中」の期間を短くする）。
 * updateAge を maxAge と同値にし、アクセスの都度スライド延長されないようにする
 * （スライドすると継続利用中のセッションが7日を超えて残り続け、揃えた意味が薄れるため）。
 */
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  session: {
    strategy: "jwt",
    maxAge: SESSION_MAX_AGE_SECONDS,
    updateAge: SESSION_MAX_AGE_SECONDS,
  },
  pages: { signIn: "/login" },
  providers: buildProviders(),
  callbacks: {
    async signIn({ user, account }) {
      // LINEプロバイダ以外（Credentials等）はそのまま通す。
      if (!account || account.provider !== "line") return true;

      const lineAccessToken = account.access_token;
      if (!lineAccessToken) return false;

      const data = await backendLineExchange(lineAccessToken);
      if (!data) return false; // 交換失敗時はログインを不成立にする（不完全なセッションを作らない）

      if (data.account_type === "operator") {
        // 契約上「LINE単独でのOperator新規作成」は行われないため、
        // operatorが返るケースは想定外。安全側で不成立にする。
        if (!data.operator) return false;
        Object.assign(user, {
          id: data.operator.id,
          email: data.operator.contact_email,
          name: data.operator.company_name,
          accessToken: data.access_token,
          accountType: "operator" as const,
          role: "operator",
          verified: data.operator.verified_at != null,
        });
        return true;
      }

      if (!data.user) return false;
      Object.assign(user, {
        id: data.user.id,
        email: data.user.email,
        name: data.user.name ?? data.user.email,
        accessToken: data.access_token,
        accountType: "user" as const,
        role: data.user.role,
      });
      return true;
    },
    jwt({ token, user, trigger, session }) {
      if (user) {
        token.accessToken = user.accessToken;
        token.accountType = user.accountType;
        token.role = user.role;
        token.verified = user.verified ?? true;
      }
      // クライアントの useSession().update({...}) 経由（自セッションの書換のみ・権限昇格リスクなし）。
      // 例: パスワード変更後の新JWT反映、プロフィール保存後のヘッダー氏名即時反映。
      if (trigger === "update" && session) {
        const patch = session as { accessToken?: unknown; name?: unknown };
        if (typeof patch.accessToken === "string" && patch.accessToken) {
          token.accessToken = patch.accessToken;
        }
        if (typeof patch.name === "string" && patch.name.trim()) {
          token.name = patch.name;
        }
      }
      return token;
    },
    session({ session, token }) {
      session.accessToken = token.accessToken as string;
      session.accountType = token.accountType as AccountType;
      session.role = token.role as string;
      session.verified = Boolean(token.verified);
      return session;
    },
  },
});
