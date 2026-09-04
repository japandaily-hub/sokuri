/**
 * ルート保護ミドルウェア — user / operator / admin の 3 区分。
 *
 * - /create, /cases/*, /mypage/*, /result/*, /applications/*,
 *   /notifications/*, /chat/*, /schedule/*, /review/*
 *                              : ユーザーのみ（role=admin は特権ユーザーとしてそのまま通過）
 * - /operator/*              : 業者のみ（/operator/login・/operator/signup は公開）
 * - /admin/*                 : role=admin のユーザーのみ
 *
 * このミドルウェアは「認証（ログイン済みか／アカウント種別）」のみを見る。
 * 「本人のリソースか」の認可（IDOR対策）はここでは判定できないため、
 * /chat/[id]・/vendors/[id]・/result 等をバックエンド配線する際は、
 * API 側でリクエスト者IDとリソース所有者IDを必ず突合すること（OWASP API1 BOLA）。
 *
 * 業者の承認状態（vendor_status）も意図的にここでは見ない。pending（admin未承認）の
 * 業者にも /operator 配下の「閲覧」は許可する設計（閲覧可・入札不可の非対称）で、
 * 入札等の書き込みはバックエンド deps.get_verified_operator（vendor_status==="active"）が、
 * 取引情報は get_current_actor＋当事者スコープが遮断する。ミドルウェアに
 * vendor_status ゲートを足す変更は、この製品判断（2026-07-02確定）を覆すため不可。
 *
 * 重要: 保護対象パスは USER_PROTECTED_PATHS / OPERATOR_PUBLIC_PATHS
 * （lib/protected-routes.ts・実行時判定）と config.matcher（Next.js の
 * 静的リテラル制約でここでしか書けない）の2箇所に重複定義されている。
 * matcher にマッチしないパスはこの関数自体が実行されないため、
 * USER_PROTECTED_PATHS 等に追加しても matcher の更新を忘れると保護が
 * 効かない（fail-open）。新規パス追加時は必ず両方を同時に更新すること。
 * パス一覧自体は katadzuke-api.ts の401共通処理からも参照するため
 * lib/protected-routes.ts に集約し、ここでは二重定義しない
 * （r6-fix-frontend4）。
 */

import { auth } from "@/auth";
import { NextResponse } from "next/server";
import { OPERATOR_PUBLIC_PATHS, USER_PROTECTED_PATHS } from "@/lib/protected-routes";

export default auth((req) => {
  const { pathname } = req.nextUrl;
  const session = req.auth;

  const isOperatorPublic = OPERATOR_PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const needsUser = USER_PROTECTED_PATHS.some((p) => pathname.startsWith(p));
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

  // r3 セキュリティレビュー H-2 是正: 非admin かつログイン済みのユーザーを /login へ送ると、
  // login/page.tsx の「認証済みなら自動で replace」が callbackUrl（=/admin配下）へ即座に
  // 送り返し、ミドルウェアが再度弾く…という無限リダイレクトループになりうる。
  // ログイン済みには /forbidden（権限不足の案内。再ログインを促さない）へ送る。
  if (needsAdmin && session.role !== "admin") {
    const url = req.nextUrl.clone();
    url.pathname = "/forbidden";
    url.search = "";
    return NextResponse.redirect(url);
  }
  // r3 再レビュー N-3 是正: 上と同じ理由で、ログイン済みだが accountType が異なる場合
  // （業者セッションが /cases 等を踏む・依頼者セッションが /operator 配下を踏む）も
  // loginUrl（=ログインページ）へ戻すと login/page.tsx 側の callbackUrl 自動 replace と
  // 往復し無限ループになりうる。/forbidden（?reason=account_type）へ送り、再ログインを促さない。
  if (
    (needsOperator && session.accountType !== "operator") ||
    (needsUser && session.accountType !== "user")
  ) {
    const url = req.nextUrl.clone();
    url.pathname = "/forbidden";
    url.search = "?reason=account_type";
    return NextResponse.redirect(url);
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
    "/operator/:path*",
    "/admin/:path*",
  ],
};
