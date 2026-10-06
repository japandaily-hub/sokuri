/**
 * 文字数の数え方と、メッセージ本文の上限定数の唯一の定義（React・他モジュール非依存）。
 * チャット（message-length）・入札メッセージ（bid-input）・表示用テキストの整形（text-guard）が共用する（QA L2）。
 *
 * backend の上限（schemas_katadzuke.py: MessageCreateRequest.body / 入札 message は max_length=2000）は
 * Pydantic の「Unicode コードポイント数」で数える。`String#length`（UTF-16 コード単位）だと絵文字などの
 * サロゲートペアが 2 と数えられサーバーより早く弾くため、コードポイントで数える。
 * backend の上限を変えるときはここだけを変えること。
 */

/** メッセージ本文（チャット・入札メッセージ共通）の上限文字数。backend の max_length と一致。 */
export const MESSAGE_MAX_CHARS = 2000;

const HIGH_SURROGATE_MIN = 0xd800;
const HIGH_SURROGATE_MAX = 0xdbff;
const LOW_SURROGATE_MIN = 0xdc00;
const LOW_SURROGATE_MAX = 0xdfff;

export interface CountCharsOptions {
  /**
   * 前後の空白を除いてから数える。チャットのように送信時に trim 済みの本文を送る入力は true、
   * 生の値をそのまま送る入札メッセージは false（既定）。
   */
  trim?: boolean;
}

/**
 * 文字列のコードポイント数を数える（Python の len() と一致する単位。O(n)）。
 * 正しいサロゲートペアは 1 文字、孤立サロゲートもそれ自体を 1 文字として数える
 * （Python の str に孤立サロゲートが入っていても len() は 1 と数えるため一致する）。
 */
export function countChars(text: string, options: CountCharsOptions = {}): number {
  const target = options.trim ? text.trim() : text;
  const length = target.length;
  let count = 0;
  let i = 0;
  while (i < length) {
    const code = target.charCodeAt(i);
    if (code >= HIGH_SURROGATE_MIN && code <= HIGH_SURROGATE_MAX && i + 1 < length) {
      const next = target.charCodeAt(i + 1);
      if (next >= LOW_SURROGATE_MIN && next <= LOW_SURROGATE_MAX) {
        i += 2;
        count += 1;
        continue;
      }
    }
    i += 1;
    count += 1;
  }
  return count;
}
