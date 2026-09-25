/**
 * 評価（よかった／伸びしろ）とコメント候補文の唯一の置き場所（React 非依存）。
 * ReviewComposer.tsx から利用する。デザイン正典: .agent-state/review-verdict/DESIGN.md (5)。
 *
 * 候補文は文末記号（。！？!?）で完結させ、区切りは必要なときだけ半角スペース1つを使う
 * （改行は backend の無害化 (text_sanitize.py) で消えるため使わない）。
 *
 * 不変条件: 同じ方向（to_operator/to_user）×同じ評価（good/improve）の候補文どうしは、
 * 互いに部分文字列にならない（hasPhrase の substring 判定が別候補と混同しないため。
 * review-verdict.test.mts で全組み合わせを固定する）。
 */

import type { ReviewVerdict } from "./katadzuke-api";

/** 評価の向き。to_operator=依頼者→業者／to_user=業者→依頼者。 */
export type ReviewDirection = "to_operator" | "to_user";

/** ReviewVerdict の表示ラベル。 */
export const REVIEW_VERDICT_LABEL: Record<ReviewVerdict, string> = {
  good: "よかった",
  improve: "伸びしろ",
};

/** コメント欄の最大文字数（ReviewComposer 共通。既存 /review ページの上限を踏襲）。 */
export const REVIEW_COMMENT_MAX = 300;

/** コメント欄のプレースホルダ（既存文言を維持）。 */
export const REVIEW_PLACEHOLDER: Record<ReviewDirection, string> = {
  to_operator: "業者の対応の感想（任意）",
  to_user: "取引の感想（任意）",
};

/** ワンタップ入力用の候補文（確定文言。文言そのものを変える場合はここだけを直す）。 */
export const REVIEW_PHRASES: Record<ReviewDirection, Record<ReviewVerdict, readonly string[]>> = {
  to_operator: {
    good: [
      "安心して取引できました！",
      "スムーズでした！",
      "対応が早くて助かりました！",
      "説明が丁寧でわかりやすかったです！",
      "運び出しが丁寧でした！",
      "買取総額に満足しています！",
      "またお願いしたいです！",
    ],
    improve: [
      "連絡がもう少し早いと助かります。",
      "時間どおりに来ていただけるとさらに安心です。",
      "金額の説明がもう少し詳しいとうれしいです。",
      "運び出しがもう少し丁寧だとさらに安心です。",
      "減額の理由をもう少し詳しく知りたかったです。",
    ],
  },
  to_user: {
    good: [
      "安心して取引できました！",
      "スムーズでした！",
      "事前の写真と説明が正確で助かりました！",
      "引き取りの準備をしていただき助かりました！",
      "連絡が早くて助かりました！",
      "またよろしくお願いします！",
    ],
    improve: [
      "連絡がもう少し早いと助かります。",
      "事前の写真と実物がそろっているとさらに助かります。",
      "日程の変更は早めにご連絡いただけると助かります。",
      "運び出しの経路を空けていただけると助かります。",
    ],
  },
};

/** 文末とみなす記号。直前がこれらの場合、候補文の追記時に区切りの半角スペースを入れない。 */
const SENTENCE_END_CHARS = new Set(["。", "！", "？", "!", "?"]);

/** text の中に候補文 phrase がすでに含まれるか（チップの選択状態の判定に使う）。 */
export function hasPhrase(text: string, phrase: string): boolean {
  return text.includes(phrase);
}

/**
 * text の末尾に候補文 phrase を追記する。末尾の空白は除いてから追記し、
 * 直前の文字が文末記号（。！？!?）のいずれでもなければ半角スペース1つを挟む。
 * text が空（または空白のみ）の場合は phrase をそのまま返す。
 */
export function appendPhrase(text: string, phrase: string): string {
  const base = text.replace(/\s+$/u, "");
  if (base.length === 0) return phrase;
  const lastChar = base.slice(-1);
  const separator = SENTENCE_END_CHARS.has(lastChar) ? "" : " ";
  return `${base}${separator}${phrase}`;
}

/**
 * text から候補文 phrase の最初の出現を取り除く。appendPhrase が挟んだ半角スペース1つも
 * （直前に存在すれば）合わせて取り除くが、それ以外の本文には一切触れない
 * （appendPhrase の逆操作。review-verdict.test.mts で往復一致を固定する）。
 */
export function removePhrase(text: string, phrase: string): string {
  const index = text.indexOf(phrase);
  if (index === -1) return text;
  const hasPrecedingSpace = index > 0 && text[index - 1] === " ";
  const start = hasPrecedingSpace ? index - 1 : index;
  return text.slice(0, start) + text.slice(index + phrase.length);
}

/** phrase を追記しても、区切り込みで REVIEW_COMMENT_MAX 字以内に収まるか。 */
export function canAppend(text: string, phrase: string): boolean {
  return appendPhrase(text, phrase).length <= REVIEW_COMMENT_MAX;
}

/** 業者一覧・公開プロフィール等の件数表示（例:「よかった 3・伸びしろ 1」）。 */
export function formatVerdictCounts(good: number, improve: number): string {
  return `${REVIEW_VERDICT_LABEL.good} ${good}・${REVIEW_VERDICT_LABEL.improve} ${improve}`;
}
