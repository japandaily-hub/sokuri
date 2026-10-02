/**
 * 表示用自由記述欄（チャット本文・入札メッセージ・減額理由・キャンセル理由・
 * 業者プロフィールの文章・案件の住所詳細等、相手や公開画面に表示される自由記述欄）の
 * 送信前整形。backend/app/services/text_sanitize.py の「② 拒否（表示用自由記述欄）」と
 * 同じ文字集合を判定する（両者は必ず同じ結果になるよう範囲表の値を1:1で揃えている。
 * 範囲を変える場合は両方を同時に直すこと）。
 *
 * 判定には正規表現の Unicode プロパティエスケープ（\p{...} 相当の構文）や u フラグを
 * 使わず、UTF-16 コード単位を1回だけ走査するループ（O(n)・バックトラックなし）で
 * backend と同じ数値範囲を判定する。Next 15 の既定の対象ブラウザ（browserslist 未設定）
 * にはこれらの構文に未対応のものが含まれ、未対応のブラウザでは本ファイルを import する
 * katadzuke-api.ts ごと読み込みに失敗するため。
 *
 * このファイルは他モジュールを import しない（katadzuke-api.ts 等から安全に
 * 使える依存のない純関数だけで構成する）。
 *
 * 表記の注意: 対象文字はソース上、\u 形式のエスケープや実体（生の不可視文字）では
 * 書かず、0x.. の数値コードポイント・String.fromCharCode・String.fromCodePoint で表す
 * （編集時の変換でエスケープが本物の不可視文字に化けると、差分レビューで見えないまま
 * ソースに混入するため）。
 */

/**
 * 表示用自由記述欄で拒否する UTF-16 コード単位の範囲（両端含む・昇順）。
 * backend の DISALLOWED_DISPLAY_CHAR_RANGES と同じ集合:
 * - 0x0000–0x0009 / 0x000B–0x001F: C0 制御文字（改行 0x000A を除く。NUL・タブ・CR を含む）
 * - 0x007F–0x009F: DEL・C1 制御文字
 * - 0x061C: ALM（Arabic Letter Mark）
 * - 0x200E–0x200F: LRM・RLM
 * - 0x202A–0x202E: LRE・RLE・PDF・LRO・RLO
 * - 0x2066–0x2069: LRI・RLI・FSI・PDI
 * - 0xD800–0xDFFF: サロゲート（sanitizeDisplayText は正しいペアを先に判定して除外するため、
 *   この範囲に実際に当たるのは孤立した単位だけになる）
 * 根拠は backend/app/services/text_sanitize.py のモジュール docstring を参照
 * （Bidi_Control は並べ替えによる見た目偽装＝Trojan Source CVE-2021-42574 対策、
 * 改行以外の Cc は表示崩れ・ログ偽装・保存時 500 対策、孤立サロゲートは UTF-8 化できず
 * 保存時 500 になる対策。ZWJ・タグ文字・異体字セレクタ・ZWSP・BOM・ソフトハイフン・
 * Co・Cn 等はここに含めず許可する）。
 */
export const DISALLOWED_DISPLAY_CHAR_RANGES: ReadonlyArray<readonly [number, number]> = [
  [0x0000, 0x0009],
  [0x000b, 0x001f],
  [0x007f, 0x009f],
  [0x061c, 0x061c],
  [0x200e, 0x200f],
  [0x202a, 0x202e],
  [0x2066, 0x2069],
  [0xd800, 0xdfff],
];

/** UTF-16 コード単位が DISALLOWED_DISPLAY_CHAR_RANGES のいずれかの範囲に入るか（両端含む）。 */
function isDisallowedDisplayCodeUnit(code: number): boolean {
  for (const [lo, hi] of DISALLOWED_DISPLAY_CHAR_RANGES) {
    if (code >= lo && code <= hi) return true;
  }
  return false;
}

const HIGH_SURROGATE_MIN = 0xd800;
const HIGH_SURROGATE_MAX = 0xdbff;
const LOW_SURROGATE_MIN = 0xdc00;
const LOW_SURROGATE_MAX = 0xdfff;
const TAB = 0x09;
const LF = 0x0a;
const CR = 0x0d;

/**
 * 表示用自由記述欄をサーバー送信前に整形する（backend の reject_disallowed_display_chars と
 * 対になる関数。backend は拒否＝422 を返すだけで整形はしないため、web 側でここで
 * 落として 422 を未然に防ぐ。422 の理由が画面に出ないための対策でもある）。
 *
 * 走査規則（UTF-16 コード単位を1回だけ走査。区間を配列に積んで最後に join するため
 * O(n)・バックトラックなし）:
 * 1. 上位サロゲート（0xD800–0xDBFF）の直後が下位サロゲート（0xDC00–0xDFFF）なら、
 *    正しいペア（補助面の文字）として2単位ともそのまま残す
 *    （DISALLOWED_DISPLAY_CHAR_RANGES はすべて基本多言語面内の範囲なので、
 *    補助面の文字は常に許可される）。
 * 2. それ以外のサロゲート単位（孤立した上位・下位）は除去する。
 * 3. CR（0x0D）: 直後が LF（0x0A）なら2単位をまとめて LF 1つに、単独でも LF に置換する
 *    （古い改行コードのまま連結させない）。
 * 4. タブ（0x09）は半角空白（0x20）に置換する（表計算等からの貼り付けで隣接する語が
 *    くっついてしまわないようにする）。
 * 5. LF（0x0A）はそのまま残す。
 * 6. それ以外で DISALLOWED_DISPLAY_CHAR_RANGES に入る単位（NUL・0x01–0x08・0x0B・0x0C・
 *    0x0E–0x1F・0x7F–0x9F・Bidi_Control 12字）は除去する。
 * 7. それ以外はそのまま残す。
 *
 * 整形結果が必ずサーバーに受理されることの論証（backend の表示用自由記述欄の
 * field validator が拒否集合 R = DISALLOWED_DISPLAY_CHAR_RANGES と1:1対応する前提）:
 * - 出力に新たに現れる文字は LF と半角空白だけで、どちらも R に含まれない。
 * - 孤立サロゲートは元の位置でそのまま除去されるので、除去によって新しいサロゲート
 *   ペアや新しい R の文字が生じることはない。
 * - 出力の長さは入力より増えない（CRLF の2単位が LF 1単位になる場合のみ短くなり、
 *   それ以外は1対1の置換か除去なので長さは変わらないか減る）。したがって
 *   max_length を満たしていた入力は整形後も満たす。
 * - 孤立サロゲートが残らないため、JSON.stringify や UTF-8 化で情報が失われたり
 *   例外が発生したりしない。
 * - backend の表示用自由記述欄の検証は入力に NFKC 等の正規化を掛けないため、
 *   ここで整形した結果がそのままサーバーで検証される（整形後にサーバー側で別の
 *   文字が生成されて再度 R に触れる、ということが起きない）。
 * 以上により、この関数の出力は R に属する文字を一切含まず、常に backend の
 * 表示用自由記述欄の検証を通過する。
 *
 * @param text 整形対象の文字列
 * @returns 整形後の文字列（コード単位長は text 以下）
 */
export function sanitizeDisplayText(text: string): string {
  const length = text.length;
  const parts: string[] = [];
  let runStart = 0;

  /** [runStart, end) をそのまま残す区間として積む（区間が空なら何もしない）。 */
  const flushRun = (end: number): void => {
    if (end > runStart) parts.push(text.slice(runStart, end));
  };

  let i = 0;
  while (i < length) {
    const code = text.charCodeAt(i);

    if (code >= HIGH_SURROGATE_MIN && code <= HIGH_SURROGATE_MAX) {
      const next = i + 1 < length ? text.charCodeAt(i + 1) : 0;
      if (next >= LOW_SURROGATE_MIN && next <= LOW_SURROGATE_MAX) {
        // 正しいサロゲートペア（補助面の文字）。2単位ともランに含めたまま進む。
        i += 2;
        continue;
      }
      // ペアにならない孤立した上位サロゲート。除去する。
      flushRun(i);
      i += 1;
      runStart = i;
      continue;
    }
    if (code >= LOW_SURROGATE_MIN && code <= LOW_SURROGATE_MAX) {
      // 直前で正しいペアとして消費されなかった孤立した下位サロゲート。除去する。
      flushRun(i);
      i += 1;
      runStart = i;
      continue;
    }
    if (code === CR) {
      flushRun(i);
      const hasFollowingLf = i + 1 < length && text.charCodeAt(i + 1) === LF;
      i += hasFollowingLf ? 2 : 1;
      parts.push("\n");
      runStart = i;
      continue;
    }
    if (code === TAB) {
      flushRun(i);
      parts.push(" ");
      i += 1;
      runStart = i;
      continue;
    }
    if (code === LF) {
      // 改行はそのまま残す（ランに含めたまま進む）。
      i += 1;
      continue;
    }
    if (isDisallowedDisplayCodeUnit(code)) {
      flushRun(i);
      i += 1;
      runStart = i;
      continue;
    }
    // 許可文字。ランに含めたまま進む。
    i += 1;
  }
  flushRun(length);
  return parts.join("");
}

/**
 * 文字列のコードポイント数を数える（UTF-16 コード単位数＝String#length ではなく、
 * Python の len() と一致する単位）。正しいサロゲートペアは1文字として数え、孤立
 * サロゲートはそれ自体を1文字として数える（Python の str に孤立サロゲートが
 * 入っている場合も len() は1として数えるため、挙動が一致する）。
 */
export function countCodePoints(text: string): number {
  const length = text.length;
  let count = 0;
  let i = 0;
  while (i < length) {
    const code = text.charCodeAt(i);
    if (code >= HIGH_SURROGATE_MIN && code <= HIGH_SURROGATE_MAX && i + 1 < length) {
      const next = text.charCodeAt(i + 1);
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

/** prepareDisplayText の判定結果。 */
export type PreparedDisplayText =
  | { ok: true; value: string }
  | { ok: false; reason: "only_disallowed" }
  | { ok: false; reason: "too_short"; minLength: number };

/**
 * 表示用自由記述欄を整形し、送信可能かどうかを判定する（sanitizeDisplayText の
 * 呼び出し元がまとめて使う想定の上位関数。katadzuke-api.ts の guardDisplayText から
 * 呼ばれる）。
 * - 元の文字列が空白のみでない（trim() が空でない）のに、整形後を trim() したものが
 *   空になった場合（拒否文字だけが入力されていた場合）は "only_disallowed"
 *   （この判定を minLength の判定より先に行い、拒否文字だけの入力では
 *   "too_short" ではなく "only_disallowed" の文言を優先する）。
 * - opts.minLength 指定時、整形後を trim() したもののコードポイント数がそれ未満なら
 *   "too_short"。元の文字列が空白のみか（hasContent）に関係なく判定するため、
 *   タブ・改行・空白だけの入力（整形後は半角空白・LF だけになる）もここで
 *   "too_short" になる（QAレビュー是正: 従来は hasContent が false の場合に
 *   この判定自体をスキップしていたため、タブだけの入力等が minLength をすり抜けて
 *   "ok" になっていた）。
 * - それ以外は "ok"（value は整形後の文字列。trim はしない）。minLength 未指定時は、
 *   空文字・空白のみの入力も "ok" として返す（必須入力かどうかの判定は呼び出し側の
 *   既存の画面チェックに委ねる）。
 *
 * trim() した上で数える理由と、trim しない value を返しても安全なことの論証:
 * 呼び出し側の画面（例: 減額申請フォーム）の必須文字数チェックは見た目の文字数
 * （trim 後）で判定しているため、ここでの判定もそれと揃える。一方 backend の
 * min_length 制約は受け取った文字列を trim せずに数える。trim は文字を取り除く
 * だけの操作なので、trim 後のコードポイント数は trim 前（sanitized）のコードポイント数
 * を超えない。したがってこの関数が "too_short" にならず "ok" を返した入力は、
 * value（= 整形後の文字列。trim していない）のコードポイント数が
 * 「trim 後のコードポイント数（>= minLength が確認済み）」以上になり、
 * 結果として value のコードポイント数も必ず minLength 以上になる。
 * よって web がここで "ok" を返した入力を送信すれば、backend の min_length も必ず満たす。
 */
export function prepareDisplayText(
  text: string,
  opts?: { minLength?: number },
): PreparedDisplayText {
  const sanitized = sanitizeDisplayText(text);
  const trimmedSanitized = sanitized.trim();
  const hasContent = text.trim() !== "";
  if (hasContent && trimmedSanitized === "") {
    return { ok: false, reason: "only_disallowed" };
  }
  const minLength = opts?.minLength;
  if (minLength != null && countCodePoints(trimmedSanitized) < minLength) {
    return { ok: false, reason: "too_short", minLength };
  }
  return { ok: true, value: sanitized };
}
