/**
 * /login（依頼者・運営の共通ログイン画面）でログインした後の遷移先の決定。
 *
 * app/login/page.tsx はセッションが確定した時点で、この関数の戻り値へ 1 回だけ遷移する。
 * 送信直後とログイン済みで /login を開いた場合とで遷移先の決め方が分かれていたことが、
 * 運営の着地先の食い違い（/admin のはずが /cases）の原因だったため、ここに 1 つにまとめる
 * （2026-09-26。経緯は page.tsx の遷移処理のコメント）。
 *
 * next/* や next-auth に依存しない純関数に保つこと（node --test で単体テストする。
 * post-login-path.test.mts）。外部入力（クエリの callbackUrl）の検証はここでは行わず、
 * lib/safe-path.ts の safeInternalPath に一本化する。
 */

/** 運営（role=admin）の既定の遷移先（管理画面）。 */
export const ADMIN_HOME_PATH = "/admin";

/** 依頼者の既定の遷移先（マイ案件）。 */
export const USER_HOME_PATH = "/cases";

/**
 * callbackUrl の指定が無い（または検証で弾かれた・遷移先として許可できない）ときの遷移先。
 * @param role セッションの role。"admin" 以外（依頼者・不明）は依頼者として扱う
 */
export function defaultPostLoginPath(role: string | null | undefined): string {
  return role === "admin" ? ADMIN_HOME_PATH : USER_HOME_PATH;
}

/**
 * 依頼者アカウント（accountType==="user"）のセッションで、ログイン後の遷移先として許可できるパスか。
 * - /operator 配下: 業者専用（middleware.ts が /forbidden へ弾く。/operator/login も依頼者の
 *   セッションでは行き止まり）→ 不可（r3 セキュリティレビュー H-2）
 * - /admin 配下: role=admin のみ（それ以外は middleware.ts が /forbidden へ弾く）
 * - /login: ログイン画面そのもの。送っても既定の遷移先へ読み込み直すだけの遠回りになる
 *   （callbackUrl を入れ子にすると段数だけ繰り返す）→ 不可
 * 接頭辞は middleware.ts と同じく startsWith で見る（"/operators" 等も弾く＝安全側に倒す）。
 *
 * @param path safeInternalPath で検証・正規化済みのサイト内パス（pathname + search + hash）
 * @param role セッションの role
 */
export function isAllowedPostLoginPath(path: string, role: string | null | undefined): boolean {
  if (path.startsWith("/operator") || path.startsWith("/login")) return false;
  if (path.startsWith("/admin")) return role === "admin";
  return true;
}

/**
 * ログイン後の遷移先。
 * - callbackUrl の指定なし → 運営は /admin・それ以外は /cases
 * - 指定あり → 遷移先として許可できればそこ、できなければ上の既定
 *
 * @param requestedPath safeInternalPath で検証・正規化済みの callbackUrl。
 *   指定なし・検証で弾かれた値は null
 * @param role セッションの role（取得できなかった場合は undefined＝依頼者として扱う）
 * @returns 遷移先のサイト内パス
 */
export function resolvePostLoginPath(requestedPath: string | null, role: string | null | undefined): string {
  if (requestedPath !== null && isAllowedPostLoginPath(requestedPath, role)) return requestedPath;
  return defaultPostLoginPath(role);
}
