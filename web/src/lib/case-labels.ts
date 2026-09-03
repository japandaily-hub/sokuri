import type { CaseMasked } from "./katadzuke-api";

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
