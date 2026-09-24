/**
 * オープンリダイレクト対策。
 * クエリ等の外部入力を遷移先に使う際、サイト内の相対パスのみを許可する。
 * - "/foo" は許可（戻り値は URL パーサで正規化した pathname + search + hash）
 * - "//evil.example" / "/\evil" / "https://evil" / "javascript:" 等は fallback
 * - "/\t/evil.example" のように制御文字を挟んだものも fallback
 */

/** 相対パスを解釈するための基準 URL。予約 TLD（.invalid・RFC 2606）のため実在の origin と衝突しない。 */
const INTERNAL_URL_BASE = "https://internal.invalid";

/**
 * C0 制御文字（U+0000〜U+001F）・DEL（U+007F）・バックスラッシュを含むか。
 * 正規表現に制御文字の範囲を書くと eslint の no-control-regex に掛かるため、1文字ずつ走査する（O(n)）。
 */
function hasControlCharOrBackslash(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code <= 0x1f || code === 0x7f || code === 0x5c) return true;
  }
  return false;
}

/**
 * 外部入力をサイト内の遷移先パスとして検証・正規化する。
 *
 * 制御文字を先に弾く理由（セキュリティレビュー MEDIUM 是正）:
 * WHATWG URL パーサ（ブラウザの new URL。Next のルーターも router.push/replace の
 * href を new URL(href, location.href) で解釈する）は、解釈の前に入力から TAB/LF/CR を
 * 除去する。旧実装は先頭2文字しか見ていなかったため "/\t/evil.example" が通過し、
 * 遷移時に "//evil.example"（スキーム相対 URL＝外部サイト）として解釈されていた。
 * TAB/LF/CR 以外の C0 制御文字・DEL もサイト内パスに現れる正当な理由が無いため
 * まとめて拒否する。バックスラッシュは http(s) の URL では "/" と同一視されるため拒否する。
 *
 * 正規化済みの値を返す理由:
 * "/cases/../operator" のドットセグメントやパーセントエンコードされたドット（"%2e%2e"）は
 * 遷移時に解決されるため、生の文字列のまま返すと呼び出し側の接頭辞判定
 * （/login の reachable 判定、/operator/login の "/operator" 接頭辞強制）が実際の遷移先と
 * 食い違う。URL パーサで解決した後の値を返し、呼び出し側が実際の遷移先そのものを判定
 * できるようにする。解決後の pathname が "//" で始まる場合（例: "/a/..//evil" → "//evil"）は、
 * 返した値を遷移に使った時点でスキーム相対 URL になるため拒否する。
 *
 * @param raw 外部入力（クエリの callbackUrl 等）。null / undefined / 空文字は fallback
 * @param fallback 不正・未指定時の遷移先。呼び出し側の定数をそのまま返す（正規化しない）
 * @returns 正規化済みのサイト内パス（pathname + search + hash）または fallback
 */
export function safeInternalPath(raw: string | null | undefined, fallback: string): string {
  if (!raw) return fallback;
  if (hasControlCharOrBackslash(raw)) return fallback;
  // 先頭が単一スラッシュの相対パスのみ許可（"//" で始まるものはスキーム相対 URL＝外部）
  if (!raw.startsWith("/") || raw.startsWith("//")) return fallback;
  let resolved: URL;
  try {
    resolved = new URL(raw, INTERNAL_URL_BASE);
  } catch {
    return fallback;
  }
  // 多層防御: 上の判定で外部 origin に解釈される入力は弾いているが、パーサの解釈で
  // origin が基準から外れた場合も遷移先に使わない。
  if (resolved.origin !== INTERNAL_URL_BASE) return fallback;
  if (resolved.pathname.startsWith("//")) return fallback;
  return resolved.pathname + resolved.search + resolved.hash;
}
