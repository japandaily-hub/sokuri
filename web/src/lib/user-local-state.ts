/**
 * 端末に残す利用者ごとの状態（/create の下書き・/notifications の既読）のキー設計と消去（React 非依存）。
 *
 * 背景（security L-5・L-6）: キーが全利用者共通だと、共用端末でログアウト後に次の人へ前の人の下書き・既読が見える。
 * 対策は (1) キーに利用者の識別子（メールまたは id）の SHA-256 先頭16文字を含める
 * (2) ログアウト・退会・セッション失効の直前に該当キーをすべて消す。
 * 識別子そのものは保存しない（ハッシュのみ。衝突は実用上無視できる 64bit）。
 */

/** 消去対象のキー接頭辞（旧版・現行版とも。接頭辞一致で全利用者分を消す）。 */
export const USER_LOCAL_STATE_KEY_PREFIXES: readonly string[] = ["kdz:create-draft:", "kdz.notifications.read."];

/** キーに入れるハッシュの長さ（16進で16文字＝64bit）。 */
export const USER_HASH_LENGTH = 16;

/** 文字列の SHA-256 の先頭 {@link USER_HASH_LENGTH} 文字（小文字16進）。Web Crypto が無い環境では例外を投げる。 */
export async function shortSha256(text: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new Error("Web Crypto が使えません");
  const digest = await subtle.digest("SHA-256", new TextEncoder().encode(text));
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return hex.slice(0, USER_HASH_LENGTH);
}

/** 利用者ごとの保存キー（`{base}:{hash}`）。識別子が空なら null（保存・復元しない）。 */
export async function userScopedStorageKey(baseKey: string, identifier: string | null | undefined): Promise<string | null> {
  const normalized = typeof identifier === "string" ? identifier.trim().toLowerCase() : "";
  if (normalized === "") return null;
  return `${baseKey}:${await shortSha256(normalized)}`;
}

interface RemovableStorage {
  readonly length: number;
  key(index: number): string | null;
  removeItem(key: string): void;
}

/** 接頭辞に一致するキーをすべて消す。消した件数を返す。storage が使えない（例外）ときは 0。 */
export function clearUserLocalState(
  storage: RemovableStorage | null | undefined,
  prefixes: readonly string[] = USER_LOCAL_STATE_KEY_PREFIXES,
): number {
  if (!storage) return 0;
  try {
    const targets: string[] = [];
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i);
      if (key !== null && prefixes.some((prefix) => key.startsWith(prefix))) targets.push(key);
    }
    for (const key of targets) storage.removeItem(key);
    return targets.length;
  } catch (storageError) {
    console.warn("[user-local-state] 端末の保存状態を消せませんでした", storageError);
    return 0;
  }
}

/** ブラウザの sessionStorage・localStorage から利用者ごとの状態を消す（ログアウト・退会・失効の直前に呼ぶ）。 */
export function clearAllUserLocalState(): void {
  if (typeof window === "undefined") return;
  try {
    clearUserLocalState(window.sessionStorage);
    clearUserLocalState(window.localStorage);
  } catch {
    /* storage へのアクセス自体が拒否される環境では消すものも無い */
  }
}
