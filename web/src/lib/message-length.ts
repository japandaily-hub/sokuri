/**
 * メッセージ本文（チャット・入札メッセージ）の文字数上限と数え方の共通部品。
 *
 * backend の上限（schemas_katadzuke.py: MessageCreateRequest.body / 入札 message は
 * max_length=2000。Pydantic は Unicode コードポイント数で数える）と値・数え方を一致させる。
 * `String#length`（UTF-16 コード単位）だと絵文字などのサロゲートペアが 2 と数えられ、
 * サーバーより早く弾いてしまうため、コードポイントで数える。
 * backend の上限を変えるときはここも変えること。
 */

/** メッセージ本文の上限文字数（backend の max_length と一致）。 */
export const MESSAGE_MAX_LENGTH = 2000;

/** 文字数をコードポイント単位で数える。 */
export function countMessageChars(text: string): number {
  return Array.from(text).length;
}

export interface MessageLengthState {
  /** 前後の空白を除いた文字数（サーバーへ送る本文の文字数）。 */
  count: number;
  /** 上限を超えているか。 */
  over: boolean;
  /** 超過した文字数（超えていなければ 0）。 */
  excess: number;
  /** カウンタ表示（例「1,234 / 2,000」）。 */
  counterLabel: string;
  /** 超過時の案内（超えていなければ null）。 */
  overMessage: string | null;
}

/**
 * 入力中の本文の文字数状態を返す。送信する本文は trim 済みなので、数えるのも trim 後。
 * @param max 上限（既定は MESSAGE_MAX_LENGTH）
 */
export function messageLengthState(text: string, max: number = MESSAGE_MAX_LENGTH): MessageLengthState {
  const count = countMessageChars(text.trim());
  const excess = Math.max(0, count - max);
  const maxLabel = max.toLocaleString("ja-JP");
  return {
    count,
    over: excess > 0,
    excess,
    counterLabel: `${count.toLocaleString("ja-JP")} / ${maxLabel}`,
    overMessage:
      excess > 0
        ? `${maxLabel}字を超えているため送信できません（${excess.toLocaleString("ja-JP")}字減らしてください）`
        : null,
  };
}

/** keydown イベントのうち IME 判定に使う部分（React の KeyboardEvent も満たす）。 */
interface ImeKeyEventLike {
  isComposing?: boolean;
  keyCode?: number;
  nativeEvent?: { isComposing?: boolean; keyCode?: number };
}

/**
 * IME の変換確定中の keydown か。確定の Enter を送信と取り違えないために使う。
 * `isComposing` に加え、Safari 等で確定の keydown が isComposing=false で来る場合の keyCode 229 も見る。
 */
export function isImeComposingKey(event: ImeKeyEventLike): boolean {
  const native = event.nativeEvent;
  return (
    event.isComposing === true ||
    native?.isComposing === true ||
    event.keyCode === 229 ||
    native?.keyCode === 229
  );
}
