/** NextAuth 型拡張 — backend JWT・アカウント種別をセッションに載せる。 */

import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface User {
    accessToken: string;
    accountType: "user" | "operator";
    role: string;
    verified?: boolean;
  }

  interface Session {
    accessToken: string;
    accountType: "user" | "operator";
    role: string;
    verified: boolean;
    user: {
      name?: string | null;
      email?: string | null;
      image?: string | null;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    accountType?: "user" | "operator";
    role?: string;
    verified?: boolean;
  }
}
