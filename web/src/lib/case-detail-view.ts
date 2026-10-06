/**
 * 依頼者の案件詳細（/cases/[id]）で使う純関数。画面から切り出して単体テストできるようにしたもの。
 */

/** 案件 ID（UUID）の形式。形式違いは API を叩かず専用表示にする。 */
export const CASE_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isCaseIdFormat(value: unknown): value is string {
  return typeof value === "string" && CASE_ID_PATTERN.test(value);
}

/**
 * 住居情報の表示用パーツ。未入力（null/空）は出さない（生のダッシュや「EVなし」の断定を避ける）。
 */
export function buildHousingAttributes(input: {
  housing_type: string | null;
  floor_plan: string | null;
  floor_number: number | null;
  has_elevator: boolean | null;
}): string[] {
  return [
    input.housing_type,
    input.floor_plan,
    input.floor_number != null ? `${input.floor_number}階` : null,
    input.has_elevator == null ? null : input.has_elevator ? "エレベーターあり" : "エレベーターなし",
  ].filter((v): v is string => Boolean(v));
}

/**
 * 作業完了の確定が「訪問予定日より前」または「訪問日が未定」か。
 * visitDate・todayJst はどちらも "YYYY-MM-DD"（日本時間の今日）。ISO 日付は文字列比較で大小が付く。
 * 形式が不正な訪問日は安全側（警告を出す側）に倒す。
 */
export function isCompletionBeforeVisit(visitDate: string | null, todayJst: string): boolean {
  if (visitDate == null) return true;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(visitDate)) return true;
  return visitDate > todayJst;
}
