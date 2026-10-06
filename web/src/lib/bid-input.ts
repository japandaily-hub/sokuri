/**
 * 業者の入札入力まわりの純関数（案件詳細・ダッシュボードのカード入札で共有）。
 * 他モジュールを import しない。backend の message は Pydantic max_length=2000（コードポイント数）。
 */

/** 入札メッセージ（初回・引き上げ共通）の上限文字数。backend schemas の message max_length と同値。 */
export const BID_MESSAGE_MAX_CHARS = 2000;

/** Unicode コードポイント数（Pydantic max_length と同じ数え方。絵文字などのサロゲートペアを1と数える）。 */
export function countCodePoints(value: string): number {
  return Array.from(value).length;
}

/** 入札メッセージが上限を超えていないか。 */
export function isBidMessageWithinLimit(value: string): boolean {
  return countCodePoints(value) <= BID_MESSAGE_MAX_CHARS;
}

/**
 * 金額を「¥50,000（5万円）」形式にする。桁の打ち間違い（50,000 と 500,000 など）に
 * 気づけるよう、千円区切りに加えて万・億単位の読みを併記する。1万円未満は読みを併記しない。
 */
export function formatBidAmountWithUnit(amount: number): string {
  const grouped = `¥${amount.toLocaleString("ja-JP")}`;
  if (!Number.isFinite(amount) || amount < 10_000) return grouped;
  const oku = Math.floor(amount / 100_000_000);
  const man = Math.floor((amount % 100_000_000) / 10_000);
  const rest = amount % 10_000;
  let reading = "";
  if (oku > 0) reading += `${oku}億`;
  if (man > 0) reading += `${man}万`;
  if (rest > 0) reading += rest.toLocaleString("ja-JP");
  return `${grouped}（${reading}円）`;
}

/**
 * 自社入札と首位額の関係。同額（他社と並んでいる）を「首位」と区別するための判定。
 * - "top": 自社が単独の最高額
 * - "tied": 他社と同額で並んでいる
 * - "behind": 他社が上回っている
 * - null: 判定材料なし
 * topAmount は最高額、otherAmounts は他社の入札額の一覧（匿名開示された分）。
 * 他社額が取得できない場合（一覧が空）は同額かどうか断定できないため "top" とする
 * （他社分は open/bidding の間だけ backend が返す。受付中の通常経路では一覧が使える）。
 */
export function classifyBidPosition(
  myAmount: number,
  topAmount: number | null,
  otherAmounts: readonly number[],
): "top" | "tied" | "behind" | null {
  if (topAmount == null) return null;
  if (myAmount < topAmount) return "behind";
  if (otherAmounts.some((a) => a === myAmount)) return "tied";
  return "top";
}
