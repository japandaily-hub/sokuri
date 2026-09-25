/**
 * 口コミの報告導線（vendors/[id] → /contact → /admin/contacts）で使う件名・本文の
 * 組み立てと読み取りをまとめた唯一の置き場所（React 非依存）。
 * vendors/[id]/page.tsx が報告リンクの件名生成に、/contact が件名の読み取りと送信時の
 * 本文加工に、/admin/contacts が本文からの口コミ ID 抽出（「該当の口コミを開く」導線）に、
 * それぞれこれを使う（表記が複製されて食い違うのを防ぐ）。
 * デザイン正典: .agent-state/review-verdict/DESIGN-admin.md（段3 web）。
 */

/** 口コミ ID（UUID・ハイフン区切り表記）の形式。厳密一致の判定にのみ使う。 */
const UUID_SOURCE = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";

/** vendors/[id] の「この口コミを報告する」リンクが `/contact?subject=` に渡す件名。 */
export function buildReviewReportSubject(reviewId: string): string {
  return `口コミの報告（${reviewId}）`;
}

/**
 * buildReviewReportSubject の逆変換。件名全体が完全一致したときだけ口コミ ID を返す
 * （末尾に別の文字が続く・UUID の形式が崩れている等、無関係な subject は無視して null にする。
 * 「事業者情報の開示請求」等、他の /contact 導線に誤反応しないための厳密一致）。
 */
const REVIEW_REPORT_SUBJECT_RE = new RegExp(`^口コミの報告（(${UUID_SOURCE})）$`);
export function parseReviewReportSubject(subject: string | null | undefined): string | null {
  if (!subject) return null;
  const matched = REVIEW_REPORT_SUBJECT_RE.exec(subject);
  return matched ? matched[1] : null;
}

/**
 * /contact が送信直前に本文の先頭へ付ける件名行（既存 DISCLOSURE_PREFIX と同じ
 * 「前置して本文へ混ぜる」方式。backend にフィールド追加をしないための暫定策）。
 * 運営の受信箱（/admin/contacts）ではこの行がそのまま見えるため、隠しメタデータにはしない。
 */
export function buildReviewReportMessagePrefix(reviewId: string): string {
  return `報告する口コミ: ${reviewId}`;
}

/** message の先頭に件名行を付けて返す（/contact の送信直前に呼ぶ）。 */
export function withReviewReportPrefix(reviewId: string, message: string): string {
  const prefix = buildReviewReportMessagePrefix(reviewId);
  return message ? `${prefix}\n${message}` : prefix;
}

/**
 * withReviewReportPrefix の逆変換。本文の先頭行が完全一致のときだけ口コミ ID を返す
 * （/admin/contacts の「該当の口コミを開く」導線）。先頭行以外に同じ文言が現れても無視する。
 */
const REVIEW_REPORT_MESSAGE_RE = new RegExp(`^報告する口コミ: (${UUID_SOURCE})(?:\\n|$)`);
export function extractReviewIdFromMessage(message: string): string | null {
  const matched = REVIEW_REPORT_MESSAGE_RE.exec(message);
  return matched ? matched[1] : null;
}
