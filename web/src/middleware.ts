/**
 * ルート保護ミドルウェア — user / operator / admin の 3 区分。
 *
 * - /create, /cases/*, /mypage/*, /result/*, /applications/*,
 *   /notifications/*, /chat/*, /schedule/*, /review/*, /vendors/*
 *                              : ユーザーのみ（role=admin は特権ユーザーとしてそのまま通過）
 * - /operator/*              : 業者のみ（/operator/login・/operator/signup は公開）
 * - /admin/*                 : role=admin のユーザーのみ
 *
 * このミドルウェアは「認証（ログイン済みか／アカウント種別）」のみを見る。
 * 「本人のリソースか」の認可（IDOR対策）はここでは判定できないため、
 * /chat/[id]・/vendors/[id]・/result 等をバックエンド配線する際は、
 * API 側でリクエスト者IDとリソース所有者IDを必ず突合すること（OWASP API1 BOLA）。
 *
 * 重要: 保護対象パスは USER_PROTECTED / OPERATOR_PUBLIC（実行時判定）と
 * config.matcher（Next.js の静的リテラル制約でここでしか書けない）の
 * 2箇所に重複定義されている。matcher にマッチしないパスはこの関数自体が
 * 実行されないため、USER_PROTECTED 等に追加しても matcher の更新を忘れると
 * 保護が効かない（fail-open）。新規パス追加時は必ず両方を同時に更新すること。
 */

import { auth } from "@/auth";
import { NextResponse } from "next/server";

const OPERATOR_PUBLIC = ["/operator/login", "/operator/signup"];
/** config.matcher と対で管理。新規パス追加時は下の matcher にも "/xxx/:path*" を追記すること。 */
const USER_PROTECTED = [
  "/create",
  "/cases",
  "/mypage",
  "/result",
  "/applications",
  "/notifications",
  "/chat",
  "/schedule",
  "/review",
  "/vendors",
];

export default auth((req) => {
  const { pathname } = req.nextUrl;
  const session = req.auth;

  const isOperatorPublic = OPERATOR_PUBLIC.some((p) => pathname.startsWith(p));
  const needsUser = USER_PROTECTED.some((p) => pathname.startsWith(p));
  const needsOperator = pathname.startsWith("/operator") && !isOperatorPublic;
  const needsAdmin = pathname.startsWith("/admin");

  if (!needsUser && !needsOperator && !needsAdmin) return NextResponse.next();

  const loginUrl = (path: string) => {
    const url = req.nextUrl.clone();
    url.pathname = path;
    url.search = `?callbackUrl=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  };

  if (!session) {
    if (needsOperator) return loginUrl("/operator/login");
    return loginUrl("/login");
  }

  if (needsAdmin && session.role !== "admin") {
    return loginUrl("/login");
  }
  if (needsOperator && session.accountType !== "operator") {
    return loginUrl("/operator/login");
  }
  if (needsUser && session.accountType !== "user") {
    return loginUrl("/login");
  }
  return NextResponse.next();
});

export const config = {
  matcher: [
    "/create/:path*",
    "/cases/:path*",
    "/mypage/:path*",
    "/result/:path*",
    "/applications/:path*",
    "/notifications/:path*",
    "/chat/:path*",
    "/schedule/:path*",
    "/review/:path*",
    "/vendors/:path*",
    "/operator/:path*",
    "/admin/:path*",
  ],
};
