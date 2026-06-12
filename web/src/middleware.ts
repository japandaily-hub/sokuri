/**
 * ルート保護ミドルウェア — user / operator / admin の 3 区分。
 *
 * - /create, /cases/*        : ユーザーのみ
 * - /operator/*              : 業者のみ（/operator/login・/operator/signup は公開）
 * - /admin/*                 : role=admin のユーザーのみ
 *
 * 住所詳細などの機微情報の開示制御はバックエンド側で行う（ここは UX 用の導線制御）。
 */

import { auth } from "@/auth";
import { NextResponse } from "next/server";

const OPERATOR_PUBLIC = ["/operator/login", "/operator/signup"];

export default auth((req) => {
  const { pathname } = req.nextUrl;
  const session = req.auth;

  const isOperatorPublic = OPERATOR_PUBLIC.some((p) => pathname.startsWith(p));
  const needsUser = pathname.startsWith("/create") || pathname.startsWith("/cases");
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
  matcher: ["/create/:path*", "/cases/:path*", "/operator/:path*", "/admin/:path*"],
};
