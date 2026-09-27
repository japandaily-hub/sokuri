/**
 * チャットの運営名義（sender_type="system"）メッセージを「お知らせ枠」で表示するための純関数と文言。
 *
 * 2026-09-27 ユーザー決定（日程検証レビュー SEC-L1/SEC-I8）:
 * - 運営名義のメッセージは、依頼者チャット（ChatPanel）・業者チャットの両方で、吹き出し
 *   （左右寄せ・アバター付き）ではなく中央寄せの枠に「カタヅケからのお知らせ」のラベルを付けて出す
 *   （相手の発言と形で区別する。以前はアバターの1文字「運」だけが違い、日程確定の直後に並ぶ
 *   依頼者のひとことが運営の続きに見え得た）。
 * - 旧形式の日程確定メッセージ（kind="schedule_confirmed"・meta v2 でないもの）の本文は運営の
 *   定型文だけで、業者が書いた候補の文言は meta.operator_slot_label に入っている。画面はそれを
 *   「業者が提示した候補」の別枠として、運営の本文と分けて表示する。2026-09-27 より前の
 *   日程確定メッセージには operator_slot_label が無く、本文（業者の文言を含み得る）をそのまま出す。
 *   日程構造化（DESIGN §13）以降の確定メッセージ（meta v2）は本文・meta ともサーバーが日付・時刻から
 *   作り、業者の文言を含まないため operator_slot_label は付かず、画面は ScheduleConfirmedBand の帯で出す。
 *
 * @/ の import を持たない純関数のみを置く（node --test でアプリ全体を起動せず単体検証するため）。
 * 単体テスト: src/lib/chat-system-notice.test.mts。
 */

/** お知らせ枠のラベル（2026-09-27 ユーザー決定）。 */
export const SYSTEM_NOTICE_LABEL = "カタヅケからのお知らせ";

/** 日程確定メッセージで、業者が書いた候補の文言を出す別枠の見出し。 */
export const OPERATOR_SLOT_LABEL_HEADING = "業者が提示した候補";

/** お知らせ枠の判定と別枠の文言の取り出しに必要な MessageOut の部分。 */
export interface SystemNoticeSource {
  sender_type: string;
  kind: string;
  meta: Record<string, unknown> | null;
}

/** 運営名義（お知らせ枠で出す）メッセージか。 */
export function isSystemNotice(message: Pick<SystemNoticeSource, "sender_type">): boolean {
  return message.sender_type === "system";
}

/**
 * 日程確定メッセージの別枠に出す、業者が書いた候補の文言を返す。
 * 運営名義の schedule_confirmed で、meta.operator_slot_label が空白以外を含む文字列のときだけ
 * その値を返し、それ以外（固定時間帯で確定した・2026-09-27 より前のメッセージ・壊れた meta）は null。
 * 表示の前の制御文字の除去は呼び出し側（ChatSystemNotice）で行う。
 */
export function operatorSlotLabelOf(message: SystemNoticeSource): string | null {
  if (!isSystemNotice(message) || message.kind !== "schedule_confirmed") return null;
  const label = message.meta?.operator_slot_label;
  return typeof label === "string" && label.trim() !== "" ? label : null;
}
