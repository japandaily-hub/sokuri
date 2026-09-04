import type { CaseMasked } from "./katadzuke-api";

/**
 * /create の目的選択肢（Literal 化）。
 * backend の purpose は現状 free string（str）で保存されるため、想定外の値
 * （旧データ・将来の選択肢変更・不正な直接APIコール等）が来ても表示が崩れないよう、
 * 表示は必ず formatPurposeLabel を経由させ、未知の値は「その他」にフォールバックする。
 */
export const CASE_PURPOSES = ["片付け整理", "遺品整理", "引っ越し", "その他"] as const;
export type CasePurpose = (typeof CASE_PURPOSES)[number];

/**
 * 案件の目的表示用ラベル。CASE_PURPOSES に含まれない値は「その他」にフォールバックする。
 * @param purpose 案件の purpose（未取得等で null/undefined になりうる）
 * @param fallbackWhenMissing purpose 自体が無い場合（案件未取得等）に表示する文言。既定は「その他」。
 */
export function formatPurposeLabel(
  purpose: string | null | undefined,
  fallbackWhenMissing: string = "その他",
): string {
  if (!purpose) return fallbackWhenMissing;
  return (CASE_PURPOSES as readonly string[]).includes(purpose) ? purpose : "その他";
}

/**
 * 案件カードの見出しに使う品目の要約ラベル。
 * 業者にとって案件IDのハッシュ（例: "c39c499a"）は意味を持たないため、
 * 商品アルバムの名前（無ければAI検出名）を先頭2件＋残り件数で表す。
 * 品目情報が無い場合は null を返し、呼び出し側でフォールバックする。
 */
export function caseItemsLabel(c: Pick<CaseMasked, "items" | "item_count">): string | null {
  const items = (c.items ?? [])
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order);
  const names = items
    .map((it) => (it.name ?? it.ai_detected_name ?? "").trim())
    .filter((n) => n.length > 0);
  const total = Math.max(c.item_count ?? 0, items.length);
  if (names.length === 0) return total > 0 ? `商品 ${total} 点` : null;
  const head = names.slice(0, 2).join("、");
  const rest = Math.max(0, total - Math.min(2, names.length));
  return rest > 0 ? `${head} ほか${rest}点` : head;
}
