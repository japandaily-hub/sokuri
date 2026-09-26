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
 * 新規入力は backend が 422 で拒否するため、ここでの用途はあくまで
 * (1) 拒否導入前から保存済みだった値を表示する際の二重の防御と、
 * (2) 業者の候補日（自由入力だった頃に保存されたものを含む）をチャットで表示する際の整形に限る
 *     （業者の候補日の入力は日付＋時間帯の選択式になり、送信前の整形は不要になった）。
 * 複数行を許す項目（システムメッセージの表示・/schedule のひとこと等）には使わず
 * stripControlCharsKeepNewlines を使うこと。
 */
export function stripControlChars(text: string): string {
  return text.replace(/[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Zl}\p{Zp}]/gu, "");
}

/**
 * 複数行を許す項目用: stripControlChars と同じ Cc/Cf/Co/Cs を除去するが、改行（\n）
 * だけは残す（Zl/Zp はこの関数の対象外。改行として扱いたい複数行項目でそこまで
 * 除去する必要はないため）。運営名義システムメッセージの表示（ChatPanel.tsx /
 * operator/chat/[id]/page.tsx）、/schedule の「業者へのひとこと」の送信前整形に使う。
 * \r・\t・双方向制御・ゼロ幅（ZWJ含む）等は改行以外の Cc/Cf/Co/Cs として除去されるため、
 * 絵文字の結合（ZWJ）を前提にした表示が必要な依頼者・業者の通常メッセージ本文には使わない。
 */
export function stripControlCharsKeepNewlines(text: string): string {
  return text.replace(/(?!\n)[\p{Cc}\p{Cf}\p{Co}\p{Cs}]/gu, "");
}

/**
 * slot（候補日ラベル）から「◯月◯日」パターンを全て抽出し、月日の数値配列で返す
 * （backend の `_SLOT_DATE_PATTERN` と同じパターン）。`slot.normalize("NFKC")` してから
 * `/([0-9]+)\s*月\s*([0-9]+)\s*日/g` を当てるため、全角数字や月間ligature（例:
 * U+32C0台の「㋀」等）は NFKC で ASCII 数字＋「月」「日」に正規化されてから拾われる一方、
 * タイ数字等 NFKC で ASCII 数字に変換されないものは拾えない。「10月 1日」のように
 * 数字と月/日の間に空白が入っていても許容する。該当が無ければ空配列を返す
 * （呼び出し側で「日付を解析できない」扱いにする）。
 */
export function slotMonthDays(slot: string): { month: number; day: number }[] {
  const matches = [...slot.normalize("NFKC").matchAll(/([0-9]+)\s*月\s*([0-9]+)\s*日/g)];
  return matches.map((m) => ({ month: Number(m[1]), day: Number(m[2]) }));
}

/**
 * 訪問予定の表示。
 * - rawSlot（業者の自由入力）は stripControlChars で制御文字（双方向制御・ゼロ幅等）を
 *   除去してから使う。
 * - visitDate が無ければ、除去後の slot をそのまま返す（無ければ空文字）。
 * - 日付ラベルは `${M}月${D}日（曜）`（visitDate が不正な日付なら visitDate の文字列そのもの）。
 * - slot が空文字なら日付ラベルのみを返す。
 * - slot 内の「◯月◯日」を slotMonthDays() で拾い集め、1つ以上あって**すべて**
 *   visit_date の月日と一致する場合に限り slot のみを返す（日付を重ねて表示しない）。
 *   日付が1つも無い・1つでも visit_date と食い違う・visitDate 自体が不正な日付の場合は、
 *   通知・リマインドの基準である visit_date を正として先頭に出す
 *   （`${日付ラベル} ${slot}`）。依頼者が API を直接叩いて visit_date と食い違う
 *   日付文言を候補ラベルに仕込んでも、表示上は必ず visit_date が先頭に出るようにする
 *   ための2026-09-25セキュリティレビュー（Low）是正。
 */
export function formatVisitSchedule(visitDate: string | null | undefined, rawSlot: string | null | undefined): string {
  const slot = rawSlot ? stripControlChars(rawSlot) : rawSlot;
  if (!visitDate) return slot ?? "";
  const d = new Date(`${visitDate}T00:00:00`);
  const label = Number.isNaN(d.getTime())
    ? visitDate
    : `${d.getMonth() + 1}月${d.getDate()}日（${["日", "月", "火", "水", "木", "金", "土"][d.getDay()]}）`;
  if (!slot) return label;
  const dateMatches = slotMonthDays(slot);
  const matchesVisitDate =
    !Number.isNaN(d.getTime()) &&
    dateMatches.length > 0 &&
    dateMatches.every((m) => m.month === d.getMonth() + 1 && m.day === d.getDate());
  return matchesVisitDate ? slot : `${label} ${slot}`;
}
