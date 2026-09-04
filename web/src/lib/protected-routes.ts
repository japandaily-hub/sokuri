/**
 * 保護ルート判定の単一情報源。
 *
 * middleware.ts（ページ遷移時のログインゲート）と katadzuke-api.ts（401共通処理が
 * 強制ログアウト＋画面遷移してよいパスかどうかの判定）の双方から参照する。
 * next/server・next-auth の auth() 等サーバー専用の依存を一切持たない純粋なモジュール
 * とすること。katadzuke-api.ts は "use client" コンポーネントから import されるため、
 * middleware.ts を直接 import すると next/server が client bundle に混入し得る
 * （r6-fix-frontend4 で分離）。
 *
 * 重要: config.matcher（Next.js の静的リテラル制約で middleware.ts にしか書けない）
 * とも内容が対応している。新規パス追加時は USER_PROTECTED_PATHS に足すだけでなく
 * middleware.ts の config.matcher にも "/xxx/:path*" を追記すること。
 */

/** 業者ログイン導線のうち /operator 配下で例外的に未ログインでも開けるパス。 */
export const OPERATOR_PUBLIC_PATHS = ["/operator/login", "/operator/signup"];

/** ユーザー（依頼者）ログインが必須のパス（role=admin は特権ユーザーとしてそのまま通過）。 */
export const USER_PROTECTED_PATHS = [
  "/create",
  "/cases",
  "/mypage",
  "/result",
  "/applications",
  "/notifications",
  "/chat",
  "/schedule",
  "/review",
];

/**
 * 指定パスがログイン必須（ユーザー/業者/管理者いずれか）かどうかを判定する。
 * middleware.ts の needsUser || needsOperator || needsAdmin と同じロジック。
 * katadzuke-api.ts の 401 共通処理は、この判定が false のパス（公開ページ）では
 * 画面遷移・文言表示をせず、セッションを静かに破棄するだけに留める。
 */
export function isProtectedRoutePath(pathname: string): boolean {
  const isOperatorPublic = OPERATOR_PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const needsUser = USER_PROTECTED_PATHS.some((p) => pathname.startsWith(p));
  const needsOperator = pathname.startsWith("/operator") && !isOperatorPublic;
  const needsAdmin = pathname.startsWith("/admin");
  return needsUser || needsOperator || needsAdmin;
}
