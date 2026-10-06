/**
 * メッセージ入力欄の近くに置く文字数カウンタ（共通部品）。
 * 上限と数え方は lib/message-length.ts（backend の max_length=2000 と一致）。
 * 超過時は赤字で理由を出す（role="status"）。呼び出し側は、超過時に送信ボタンを無効化し、
 * 入力欄に aria-describedby={id} を付けること。スタイルは呼び出し側の CSS 基盤（chat.css /
 * Tailwind）に依存しないようインラインで持つ。
 */

import { messageLengthState } from "@/lib/message-length";

export interface MessageLengthCounterProps {
  /** 入力中の本文（未 trim でよい）。 */
  text: string;
  /** 入力欄の aria-describedby から参照する id。 */
  id: string;
  /** 追加クラス（配置用）。 */
  className?: string;
}

export function MessageLengthCounter({ text, id, className }: MessageLengthCounterProps) {
  const state = messageLengthState(text);
  return (
    <div
      id={id}
      className={className}
      style={{
        flexBasis: "100%",
        fontSize: 12,
        lineHeight: 1.5,
        textAlign: "right",
        color: state.over ? "var(--danger, #d70035)" : "var(--body-soft, #6b7280)",
        fontWeight: state.over ? 600 : 400,
      }}
    >
      {state.over ? <span role="status">{state.overMessage} </span> : null}
      <span>{state.counterLabel}</span>
    </div>
  );
}
