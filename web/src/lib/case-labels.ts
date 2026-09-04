import type { CaseMasked } from "./katadzuke-api";

/**
 * /create の目的選択肢。
 * backend は CasePurpose（Literal・6値固定）で検証する。web の**選択肢**はこの4値、
 * 残り2値（LEGACY_CASE_PURPOSES）は既存データ用のレガシー値で新規選択はさせない。
 * 表示は必ず formatPurposeLabel を経由させ、未知の値は「その他」にフォールバックする。
 */
export const CASE_PURPOSES = ["片付け整理", "遺品整理", "引っ越し", "その他"] as const;
export type CasePurpose = (typeof CASE_PURPOSES)[number];

/**
 * 既存データにのみ存在する目的（backend の CasePurpose には含まれるが、web の選択肢には出さない）。
 * これらを「その他」に畳むと、既存案件の一覧・詳細・運営画面で本来の目的が失われる（r8-review M-2）。
 */
export const LEGACY_CASE_PURPOSES = ["不用品処分", "断捨離"] as const;

const KNOWN_CASE_PURPOSES: ReadonlySet<string> = new Set<string>([
  ...CASE_PURPOSES,
  ...LEGACY_CASE_PURPOSES,
]);

/**
 * 案件の目的表示用ラベル。CASE_PURPOSES ∪ LEGACY_CASE_PURPOSES に含まれる値はそのまま返し、
 * それ以外（不正な直接APIコール・将来の未知値）のみ「その他」にフォールバックする。
 * @param purpose 案件の purpose（未取得等で null/undefined になりうる）
 * @param fallbackWhenMissing purpose 自体が無い場合（案件未取得等）に表示する文言。既定は「その他」。
 */
export function formatPurposeLabel(
  purpose: string | null | undefined,
  fallbackWhenMissing: string = "その他",
): string {
  if (!purpose) return fallbackWhenMissing;
  return KNOWN_CASE_PURPOSES.has(purpose) ? purpose : "その他";
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
