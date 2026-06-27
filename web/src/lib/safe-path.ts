/**
 * オープンリダイレクト対策。
 * クエリ等の外部入力を遷移先に使う際、サイト内の相対パスのみを許可する。
 * - "/foo" は許可
 * - "//evil.example" / "/\evil" / "https://evil" / "javascript:" 等は fallback
 */
export function safeInternalPath(raw: string | null | undefined, fallback: string): string {
  if (!raw) return fallback;
  // 先頭が単一スラッシュ、かつ2文字目が "/" や "\" でない相対パスのみ許可
  if (/^\/(?![/\\])/.test(raw)) return raw;
  return fallback;
}
