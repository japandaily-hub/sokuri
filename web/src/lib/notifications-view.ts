/**
 * 通知一覧（/notifications）の表示判定。React に依存しない純関数に切り出して単体テストする。
 *
 * - 案件・取引は別々のAPIで取るため、片方だけ失敗することがある（部分失敗）。
 *   部分失敗のとき「新しいお知らせはありません」と言い切らず、欠けた分があることを明示し、
 *   再読み込みを出す（N-3）。
 * - 既読の概念（S-5）は端末の localStorage に「既読にした通知の署名」を残すだけで表す。
 *   署名には対象の案件ID・入札数を含めるため、入札が増えたときは新着として再び出る。
 *   保存するのは署名の SHA-256 先頭16文字だけ（署名は件数に比例して長くなり、以前は500字超で
 *   読み戻し時に捨てられて既読が効かなかった）。キーには利用者のハッシュを含める
 *   （lib/user-local-state.ts。ログアウト時に消す。security L-5・L-6）。
 */

import { shortSha256 } from "./user-local-state.ts";

export type NotificationSource = "cases" | "transactions";

/** 取得に失敗した取得元の日本語ラベル。 */
const SOURCE_LABEL: Record<NotificationSource, string> = {
  cases: "案件（入札）",
  transactions: "取引",
};

export type ListViewState =
  | { kind: "rows"; partialFailure: boolean; missingLabels: string[] }
  | { kind: "empty" }
  | { kind: "error"; partialFailure: false; missingLabels: string[] };

/**
 * 一覧の表示状態を決める。
 * - 行がある: 行を出す。失敗した取得元があれば partialFailure=true（欠けた分の明示＋再読み込み）。
 * - 行が無く失敗した取得元がある: 空状態を出さず error（再読み込みのみ）。
 * - 行が無く失敗も無い: empty。
 */
export function decideListView(rowCount: number, failedSources: readonly NotificationSource[]): ListViewState {
  const missingLabels = failedSources.map((s) => SOURCE_LABEL[s]);
  if (rowCount > 0) {
    return { kind: "rows", partialFailure: missingLabels.length > 0, missingLabels };
  }
  if (missingLabels.length > 0) {
    return { kind: "error", partialFailure: false, missingLabels };
  }
  return { kind: "empty" };
}

/** 部分失敗の説明文。欠けた分を列挙し、お知らせが無くなったわけではないことを添える。 */
export function partialFailureMessage(missingLabels: readonly string[]): string {
  return `${missingLabels.join("・")}のお知らせを読み込めなかったため、表示されていない通知があります。再読み込みしてください。`;
}

/** 既読の署名を保存する localStorage のキー。 */
export const READ_STORAGE_KEY = "kdz.notifications.read.v2";

/** 既読署名の保存用ダイジェスト（SHA-256 の先頭16文字）。長さが署名の件数に依存しない。 */
export const readSignatureDigest: (signature: string) => Promise<string> = shortSha256;

/** 保存済みダイジェスト1件の最大長（読み戻し時の安全弁）。 */
const READ_DIGEST_MAX_LENGTH = 64;
/** 保存する既読署名の上限（古いものから捨てる）。 */
export const READ_MAX_ENTRIES = 100;

/** 保存済みの文字列から既読署名の配列を復元する。壊れた値・想定外の型は空配列にする。 */
export function parseReadSignatures(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string" && v.length > 0 && v.length <= READ_DIGEST_MAX_LENGTH);
  } catch {
    return [];
  }
}

/** 既読署名を追加する（重複なし・上限を超えたら古いものから捨てる）。 */
export function addReadSignatures(current: readonly string[], additions: readonly string[]): string[] {
  const merged = [...current.filter((s) => !additions.includes(s)), ...additions];
  return merged.length > READ_MAX_ENTRIES ? merged.slice(merged.length - READ_MAX_ENTRIES) : merged;
}

type CaseLike = { id: string | number; bid_count: number; status: string };
type TxnLike = { id: string | number; case_id: string | number; status: string; has_review?: boolean | null };

export type DerivedRow = {
  key: "bidding" | "negotiating" | "review";
  /** 既読判定に使う署名。対象と件数が変わると変わる。 */
  signature: string;
  count: number;
  /** 対象が1件のときのみ入る（遷移先の決定に使う）。 */
  singleCaseId?: string;
  singleTransactionId?: string;
};

/** 案件・取引から通知の行を導く（取得に失敗した側は null を渡す）。 */
export function deriveRows(cases: readonly CaseLike[] | null, transactions: readonly TxnLike[] | null): DerivedRow[] {
  const rows: DerivedRow[] = [];
  const bidding = (cases ?? []).filter((c) => c.bid_count > 0 && c.status !== "closed" && c.status !== "cancelled");
  if (bidding.length > 0) {
    rows.push({
      key: "bidding",
      signature: `bidding:${bidding.map((c) => `${c.id}#${c.bid_count}`).sort().join(",")}`,
      count: bidding.length,
    });
  }
  const negotiating = (transactions ?? []).filter((t) => t.status === "pending" || t.status === "visiting");
  if (negotiating.length > 0) {
    rows.push({
      key: "negotiating",
      signature: `negotiating:${negotiating.map((t) => `${t.id}@${t.status}`).sort().join(",")}`,
      count: negotiating.length,
      singleCaseId: negotiating.length === 1 ? String(negotiating[0].case_id) : undefined,
    });
  }
  const reviewWaiting = (transactions ?? []).filter((t) => t.status === "completed" && !t.has_review);
  if (reviewWaiting.length > 0) {
    rows.push({
      key: "review",
      signature: `review:${reviewWaiting.map((t) => String(t.id)).sort().join(",")}`,
      count: reviewWaiting.length,
      singleTransactionId: reviewWaiting.length === 1 ? String(reviewWaiting[0].id) : undefined,
    });
  }
  return rows;
}
