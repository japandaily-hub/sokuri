/**
 * 依頼者の案件詳細（/cases/[id]）で使う純関数。画面から切り出して単体テストできるようにしたもの。
 */

import type { CaseStatus, TransactionStatus } from "./katadzuke-api.ts";

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
 * 案件の説明（ai_summary）のうち、画面に出す価値があるものだけを返す（それ以外は null）。
 * AI が説明を作れなかったときの定型（backend の build_fallback_summary:
 * 「利用目的: …。住居: …（…）。写真 N 枚。詳細は写真を確認してください。」）は、利用目的・住居・
 * 写真枚数という他の欄と重複する事実の羅列で、「詳細は写真を確認してください」は説明の代わりに
 * ならない。説明と呼べる内容が無いので何も出さない（M-4）。空・空白だけも null。
 */
const FALLBACK_SUMMARY_PATTERN = /^利用目的:[^。]*。(住居:[^。]*。)?写真 \d+ 枚。詳細は写真を確認してください。$/;

export function meaningfulCaseSummary(summary: string | null | undefined): string | null {
  if (summary == null) return null;
  const text = summary.trim();
  if (text === "") return null;
  if (FALLBACK_SUMMARY_PATTERN.test(text)) return null;
  return text;
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

/** 進み具合の4段（見本 v12 ② 案件詳細）。short は幅の狭い画面で使う短い名前（同じなら全幅と同じ）。 */
export const CASE_PROGRESS_STEPS: ReadonlyArray<{ full: string; short: string }> = [
  { full: "出品", short: "出品" },
  { full: "業者を選ぶ", short: "業者選び" },
  { full: "日程を決める", short: "日程" },
  { full: "引き取り", short: "引き取り" },
];

/** 進み具合の「全部済み」を表す値（CASE_PROGRESS_STEPS.length）。 */
export const CASE_PROGRESS_ALL_DONE = CASE_PROGRESS_STEPS.length;

/**
 * 進み具合のうち「いま」の段（0=出品 / 1=業者を選ぶ / 2=日程を決める / 3=引き取り）を返す。
 * それより前は済み、後は未。4（CASE_PROGRESS_ALL_DONE）は全部済み。
 * 取り下げ・キャンセル（案件・取引のどちらも）は流れから外れたので null（進み具合を出さない）。
 * - 取引なし: draft=出品の途中 / open・bidding=業者を選ぶ / closed（取引が未取得）=日程を決める
 * - 取引あり（案件が draft/open でも取引が優先）: 日程未確定（visit_date が null・空文字・visiting でない）=日程を決める / 日程確定=引き取り / 完了=全部済み
 */
export function caseProgressStep(
  caseStatus: CaseStatus,
  txn: { status: TransactionStatus; visit_date: string | null } | null,
): number | null {
  if (txn) {
    if (txn.status === "cancelled") return null;
    if (txn.status === "completed") return CASE_PROGRESS_ALL_DONE;
    // 空文字・空白だけの visit_date は「未確定」と同じ扱い（null と区別しない）。
    const hasVisitDate = typeof txn.visit_date === "string" && txn.visit_date.trim() !== "";
    return hasVisitDate || txn.status === "visiting" ? 3 : 2;
  }
  switch (caseStatus) {
    case "draft":
      return 0;
    case "open":
    case "bidding":
      return 1;
    case "closed":
      return 2;
    case "cancelled":
      return null;
  }
}

/** 進み具合の1段の見た目の状態。 */
export type CaseProgressStepState = "done" | "now" | "todo";

/**
 * 段の添字 index の状態。currentStep は caseProgressStep の値（CASE_PROGRESS_ALL_DONE のときは
 * どの段も done になり、now は出ない）。
 */
export function caseProgressStepState(index: number, currentStep: number): CaseProgressStepState {
  if (index < currentStep) return "done";
  if (index === currentStep) return "now";
  return "todo";
}
