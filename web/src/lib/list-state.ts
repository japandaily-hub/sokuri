/**
 * 一覧画面の表示状態の判定（React 非依存）。
 * 「取得に失敗した」と「0 件」を取り違えると、出品が消えたと誤解して二重出品へ誘導してしまう。
 * 失敗は 0 件より優先し、取得前（null・読み込み中）は loading にする（QA L5）。
 */

export type ListViewState = "loading" | "failed" | "empty" | "list";

export interface ListViewInput {
  /** 認証トークンの読み込み中など、取得を始められない間。 */
  pending?: boolean;
  /** 取得に失敗したか（エラー文言の有無・専用フラグ）。 */
  failed: boolean;
  /** 取得結果。未取得は null/undefined。 */
  items: readonly unknown[] | null | undefined;
}

/**
 * - 失敗していなければ、読み込み中 or 未取得 → "loading"
 * - 失敗 → "failed"（0 件の空状態や集計は出さず、再読み込みの導線を出す）
 * - 取得済みで 0 件 → "empty"、1 件以上 → "list"
 * ただし失敗しても pending の間は loading のまま（再取得の開始待ち）。
 */
export function resolveListViewState({ pending = false, failed, items }: ListViewInput): ListViewState {
  if (failed) return "failed";
  if (pending || items == null) return "loading";
  return items.length === 0 ? "empty" : "list";
}
