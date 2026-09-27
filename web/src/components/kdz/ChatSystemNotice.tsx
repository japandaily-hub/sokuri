/**
 * チャットの運営名義（sender_type="system"）メッセージのお知らせ枠（共通部品）。
 * 依頼者チャット（components/kdz/ChatPanel.tsx）と業者チャット（app/operator/chat/[id]/page.tsx）で使う。
 *
 * 吹き出し（左右寄せ・アバター付き）とは形を変え、中央寄せの枠に「カタヅケからのお知らせ」の
 * ラベルを付ける。依頼者・業者はこの形を作れないため、「（運営補足）…」のような発言をしても
 * 運営のお知らせには見えない（日程検証レビュー SEC-I8）。日程確定メッセージで業者が書いた候補の
 * 文言（meta.operator_slot_label）は、運営の本文とは別の枠に「業者が提示した候補」として出す
 * （同 SEC-L1）。判定と文言は lib/chat-system-notice.ts。
 */

import "./chat-system-notice.css";

import { stripControlChars, stripControlCharsKeepNewlines } from "@/lib/categories";
import {
  OPERATOR_SLOT_LABEL_HEADING,
  SYSTEM_NOTICE_LABEL,
  operatorSlotLabelOf,
  type SystemNoticeSource,
} from "@/lib/chat-system-notice";

/* ---- 情報アイコン（スプライト未収録のため inline。絵文字は使わない） ---- */
function InfoIc() {
  return (
    <svg className="ic kdz-chat-notice__icon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7.5v.5" />
    </svg>
  );
}

export interface ChatSystemNoticeProps {
  /** 表示する運営名義のメッセージ（sender_type="system"）。 */
  message: SystemNoticeSource & { body: string };
  /** 表示用に整形済みの送信時刻（例「14:02」）。 */
  time: string;
}

export function ChatSystemNotice({ message, time }: ChatSystemNoticeProps) {
  // 日程検証レビュー SEC-L5: 本対応前に保存された運営名義メッセージへの二重の防御として、
  // 表示直前に制御文字（改行以外）を除去する。業者の候補の文言は1行の項目なので改行も除く。
  const body = stripControlCharsKeepNewlines(message.body);
  const rawOperatorLabel = operatorSlotLabelOf(message);
  const operatorLabel = rawOperatorLabel ? stripControlChars(rawOperatorLabel).trim() : "";
  // role="note"（補足の区画）にする。<section aria-label> だとメッセージごとにランドマークが
  // 増え、スクリーンリーダーのランドマーク移動が埋もれる。ラベルは枠内の見出しとして読まれる。
  return (
    <div className="kdz-chat-notice" role="note">
      <div className="kdz-chat-notice__head">
        <InfoIc />
        <span className="kdz-chat-notice__label">{SYSTEM_NOTICE_LABEL}</span>
        <span className="kdz-chat-notice__time">{time}</span>
      </div>
      <p className="kdz-chat-notice__body">{body}</p>
      {operatorLabel ? (
        <div className="kdz-chat-notice__quote">
          <div className="kdz-chat-notice__quote-heading">{OPERATOR_SLOT_LABEL_HEADING}</div>
          <div className="kdz-chat-notice__quote-text">{operatorLabel}</div>
        </div>
      ) : null}
    </div>
  );
}
