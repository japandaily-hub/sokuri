/**
 * 確認モーダルの入力判定（React 非依存）。
 * 取り消せない操作で「社名をそのまま入力」させる一致判定と、理由必須の未入力判定。
 */

/** 前後の空白だけを無視した完全一致（大文字小文字・全半角は区別する。取り違え防止が目的のため緩めない）。 */
export function isTypedNameMatch(typed: string | null | undefined, expected: string | null | undefined): boolean {
  const target = (expected ?? "").trim();
  if (target === "") return false;
  return (typed ?? "").trim() === target;
}

/** 理由必須のモーダルで、理由が未入力（空・空白のみ）か。理由欄が無い・必須でないモーダルでは false。 */
export function isReasonMissing(withReason: boolean, reasonRequired: boolean, reason: string): boolean {
  return withReason && reasonRequired && reason.trim() === "";
}
