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
 */

import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

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

async function backendLogin(
  path: "/auth/login" | "/auth/operator/login",
  email: string,
  password: string,
): Promise<BackendAuthResponse | null> {
  try {
    const res = await fetch(`${apiBase()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) return null;
    return (await res.json()) as BackendAuthResponse;
  } catch {
    return null;
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
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
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        token.accessToken = user.accessToken;
        token.accountType = user.accountType;
        token.role = user.role;
        token.verified = user.verified ?? true;
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
