/**
 * パスワード再設定まわりの純関数（React・fetch 非依存。単体テスト対象）。
 * 画面は /password-reset と /password-reset/confirm、API 呼び出しは app/password-reset/reset-api.ts。
 */

/** 再設定の対象アカウントの種別（backend の account_type と同じ値）。 */
export type ResetAccountType = "user" | "operator";

/** クエリ等から受け取った値を種別へ絞り込む。不明な値は依頼者（user）として扱う。 */
export function toResetAccountType(value: string | null | undefined): ResetAccountType {
  return value === "operator" ? "operator" : "user";
}

/** 再設定 token の形式（backend の発行値: URL セーフ文字 32〜128 字）。 */
export const RESET_TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;

export type ParsedResetLink =
  | { status: "ready"; token: string; accountType: ResetAccountType }
  | { status: "missing"; accountType: ResetAccountType };

/**
 * 再設定リンクのクエリ文字列（`location.search`）から token と種別を取り出す。
 * - あり: 形式に合う token → ready
 * - なし: token が無い／空 → missing
 * - 不正形式: 長さ・文字種が合わない → missing（値は結果に含めない）
 * 画面は読んだ直後に URL から token を消すため、再描画（開発モードの Strict Mode の 2 回目の effect 等）で
 * 読み直してはならない。結果は useRef／state に保持して使うこと（QA M1）。
 */
export function parseResetToken(search: string | null | undefined): ParsedResetLink {
  const params = new URLSearchParams(search ?? "");
  const accountType = toResetAccountType(params.get("type"));
  const token = params.get("token") ?? "";
  return RESET_TOKEN_PATTERN.test(token) ? { status: "ready", token, accountType } : { status: "missing", accountType };
}

/**
 * 再設定リンクを location から取り出す。メールのリンクは `#token=...&type=...`（フラグメント。サーバー・
 * 外部のログに送られない）形式。旧形式の `?token=...` も当面は受ける（フラグメントを優先）。
 * `search` は `location.search`、`hash` は `location.hash`（先頭の `#` は付いていても外してもよい）。
 */
export function parseResetLink(search: string | null | undefined, hash: string | null | undefined): ParsedResetLink {
  const fromHash = parseResetToken((hash ?? "").replace(/^#/, ""));
  if (fromHash.status === "ready") return fromHash;
  const fromSearch = parseResetToken(search);
  if (fromSearch.status === "ready") return fromSearch;
  // どちらにも token が無い: 種別だけはフラグメント側（あれば）を優先して返す。
  return new URLSearchParams((hash ?? "").replace(/^#/, "")).has("type") ? fromHash : fromSearch;
}

/** 利用者へ見せられない（内部事情・英語のまま）エラーのときの既定の案内。 */
export const RESET_DEFAULT_ERROR_MESSAGE = "ただいま処理できません。時間をおいてお試しください。";

const JAPANESE_CHAR = /[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Han}]/u;

/**
 * 失敗応答の利用者向け文言を決める。backend が日本語の文言を返した 4xx（404 を除く）だけをそのまま使い、
 * 404／5xx／日本語を含まない detail（"Not Found" "Internal Server Error" 等）／空は既定の文言に落とす（QA M3）。
 */
export function resolveResetErrorMessage(status: number, detailMessage: string | null | undefined): string {
  if (status === 404 || status >= 500) return RESET_DEFAULT_ERROR_MESSAGE;
  const text = (detailMessage ?? "").trim();
  if (text === "" || !JAPANESE_CHAR.test(text)) return RESET_DEFAULT_ERROR_MESSAGE;
  return text;
}
