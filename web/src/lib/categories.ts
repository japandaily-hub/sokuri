/** 業者の取扱カテゴリ（id はバックエンド保存値・name は表示名）。業者プロフィール編集画面と公開プロフィールで共有する。 */
export const VENDOR_CATEGORY_NAMES: Record<string, string> = {
  kaden: "家電・PC",
  brand: "ブランド品",
  camera: "カメラ",
  watch: "時計・宝飾",
  fashion: "衣類・靴",
  furniture: "家具",
  game: "ゲーム・玩具",
  hobby: "楽器・趣味",
  other: "その他",
};

/** id → 表示名。未知の id はそのまま返す（表示が空になるより保守的）。 */
export function vendorCategoryName(id: string): string {
  return VENDOR_CATEGORY_NAMES[id] ?? id;
}

/**
 * 1行表示・1行入力用: 表示・入力を乱す制御文字を除去する。対象は Unicode カテゴリ
 * Cc/Cf/Co/Cs（backend/app/schemas_katadzuke.py の `_REJECTED_CONTROL_CATEGORIES` と同じ）
 * に加え Zl/Zp（backend も候補日・訪問時間帯などの1行項目では拒否する。
 * 日程検証レビュー SEC-L3）。
 * - Cc（制御）: 改行・タブを含む C0/C1 制御文字
 * - Cf（書式）: 双方向制御（U+202A–202E の LRE/RLE/PDF/LRO/RLO、U+2066–2069 の
 *   LRI/RLI/FSI/PDI）、ゼロ幅（U+200B–200F、U+2060–2064）、U+061C（ALM）、
 *   U+FEFF（BOM/ZWNBSP）、U+00AD（ソフトハイフン）等
 * - Co（私用領域）
 * - Cs（孤立サロゲート）
 * - Zl（行区切り U+2028）・Zp（段落区切り U+2029）: 改行と同じ見た目・効果を持つため、
 *   複数行を許さない1行項目に紛れ込むと表示・入力を崩す
 * 日程構造化 DESIGN §13 以降、候補日のラベル・確定値はサーバーが構造化データから作るため、
 * ここでの用途は表示時の二重の防御に限る: (1) 旧形式（v1）の提示に残る業者の自由記述の候補、
 * (2) サーバーが作った候補日ラベル（meta の label）、(3) visitDate が不正な場合のそのままの表示。
 * 複数行を許す項目（旧形式の確定メッセージ本文・/schedule のひとこと等）には使わず
 * stripControlCharsKeepNewlines を使うこと。
 */
export function stripControlChars(text: string): string {
  return text.replace(/[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Zl}\p{Zp}]/gu, "");
}

/**
 * 複数行を許す項目用: stripControlChars と同じ Cc/Cf/Co/Cs を除去するが、改行（\n）
 * だけは残す（Zl/Zp はこの関数の対象外。改行として扱いたい複数行項目でそこまで
 * 除去する必要はないため）。運営名義システムメッセージの表示（components/kdz/ChatSystemNotice.tsx）、
 * 旧形式の確定メッセージ本文の表示（components/kdz/ScheduleConfirmedBand.tsx）、/schedule の
 * 「業者へのひとこと」の送信前整形に使う。
 * \r・\t・双方向制御・ゼロ幅（ZWJ含む）等は改行以外の Cc/Cf/Co/Cs として除去されるため、
 * 絵文字の結合（ZWJ）を前提にした表示が必要な依頼者・業者の通常メッセージ本文には使わない。
 */
export function stripControlCharsKeepNewlines(text: string): string {
  return text.replace(/(?!\n)[\p{Cc}\p{Cf}\p{Co}\p{Cs}]/gu, "");
}

const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"] as const;

/**
 * 時間帯のうち「時間指定なし」（visit-slots.ts の VISIT_TIME_SLOTS の固定値の写し。
 * node --test で単体検証するため categories.ts は visit-slots.ts を import できない。
 * 固定5種がすべて表示されることは categories.test.mts で VISIT_TIME_SLOTS と照合する）。
 */
const NO_TIME_PREFERENCE_SLOT = "時間指定なし";

/** 時刻の範囲の時間帯（例: "9:00〜12:00"・"10:30〜12:00"。波ダッシュは U+301C）。日程構造化 DESIGN §13.4。 */
const TIME_RANGE_SLOT_PATTERN = /^\d{1,2}:\d{2}〜\d{1,2}:\d{2}$/;

/**
 * visitDate（"YYYY-MM-DD"）を `${M}月${D}日（曜）` にする。Date.UTC と getUTC* で求めるため
 * ブラウザのタイムゾーンに依存しない。形式違い・実在しない日付なら、制御文字を除去した
 * visitDate の文字列そのものを返す（表示が消えるより保守的）。
 */
function formatVisitDateLabel(visitDate: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(visitDate);
  if (m) {
    const year = Number(m[1]);
    const month = Number(m[2]);
    const day = Number(m[3]);
    const d = new Date(Date.UTC(year, month - 1, day));
    if (d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day) {
      return `${month}月${day}日（${DOW_LABELS[d.getUTCDay()]}）`;
    }
  }
  return stripControlChars(visitDate);
}

/**
 * 訪問予定の表示（日程構造化 DESIGN §13.4）。
 * - 日付は常に visitDate から作る（`${M}月${D}日（曜）`）。visitDate が無ければ空文字
 *   （時間帯だけを出しても訪問予定にならないため）。
 * - rawSlot（visit_time_slot）は、固定値（「時間指定なし」または時刻の範囲）か
 *   `^\d{1,2}:\d{2}〜\d{1,2}:\d{2}$` に一致するときだけ半角空白を挟んで後ろに付ける。
 *   日付入りの旧ラベル・業者の自由記述・制御文字入り・書式違い（"10:00-12:00" 等）は付けない
 *   （ラベルを解析せず、業者の文字列を訪問予定の表示に載せない。SEC-N1 / N2 / L1）。
 */
export function formatVisitSchedule(visitDate: string | null | undefined, rawSlot: string | null | undefined): string {
  if (!visitDate) return "";
  const dateLabel = formatVisitDateLabel(visitDate);
  const slot = rawSlot ?? "";
  const showSlot = slot === NO_TIME_PREFERENCE_SLOT || TIME_RANGE_SLOT_PATTERN.test(slot);
  return showSlot ? `${dateLabel} ${slot}` : dateLabel;
}
