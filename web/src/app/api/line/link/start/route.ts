/**
 * LINE通知連携（後付け連携）開始エンドポイント。
 *
 * /notifications から「LINEで通知を受け取る」押下時に遷移してくる:
 *  - has_password===true のユーザー: パスワード確認モーダル通過後、
 *    ?reauth_token=... 付きで遷移してくる。
 *  - has_password===false のユーザー: reauth_token なしで直接遷移してくる。
 *
 * state（CSRF対策の乱数）と reauth_token を短命 httpOnly cookie に積み替えてから
 * LINE の authorize URL へ 302 する。reauth_token をそのまま URL に残したまま
 * LINE側へリダイレクトさせない（Referrer等での漏洩を避けるため、ここで一度cookie化して
 * クエリからは消す）。
 */

import crypto from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { auth } from "@/auth";
import {
  LINE_LINK_COOKIE_MAX_AGE,
  LINE_LINK_REAUTH_COOKIE,
  LINE_LINK_STATE_COOKIE,
  buildLineAuthorizeUrl,
  getAppBaseUrl,
  lineLinkRedirectUri,
} from "@/lib/line-link";

export async function GET(req: NextRequest) {
  // /api/* は middleware.ts の保護対象外（matcherに含まれない）のため、ここで明示的にログイン確認する。
  const session = await auth();
  if (!session?.accessToken) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.search = "?callbackUrl=%2Fnotifications";
    return NextResponse.redirect(loginUrl);
  }

  // 未構成（環境変数欠落）は再試行しても回復しないため link_failed とは別コードで返す。
  const appBaseUrl = getAppBaseUrl();
  if (!appBaseUrl) {
    console.error(
      "[line-link/start] APP_BASE_URL（および VERCEL_PROJECT_PRODUCTION_URL）が未設定のため連携を開始できません",
    );
    return NextResponse.redirect(new URL("/notifications?error=line_unavailable", req.url));
  }

  const redirectUri = lineLinkRedirectUri(appBaseUrl);
  const state = crypto.randomBytes(32).toString("hex");
  const authorizeUrl = buildLineAuthorizeUrl(state, redirectUri);
  if (!authorizeUrl) {
    console.error("[line-link/start] LINE_CLIENT_ID が未設定のため連携を開始できません");
    return NextResponse.redirect(new URL("/notifications?error=line_unavailable", req.url));
  }

  const reauthToken = req.nextUrl.searchParams.get("reauth_token");

  const res = NextResponse.redirect(authorizeUrl);
  const isProd = process.env.NODE_ENV === "production";
  res.cookies.set(LINE_LINK_STATE_COOKIE, state, {
    httpOnly: true,
    sameSite: "lax",
    secure: isProd,
    path: "/",
    maxAge: LINE_LINK_COOKIE_MAX_AGE,
  });
  if (reauthToken) {
    res.cookies.set(LINE_LINK_REAUTH_COOKIE, reauthToken, {
      httpOnly: true,
      sameSite: "lax",
      secure: isProd,
      path: "/",
      maxAge: LINE_LINK_COOKIE_MAX_AGE,
    });
  } else {
    // 前回試行の残骸が万一残っていても混入させない。
    res.cookies.delete(LINE_LINK_REAUTH_COOKIE);
  }
  return res;
}
