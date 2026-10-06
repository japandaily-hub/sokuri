/**
 * API の日時文字列を日本時間（Asia/Tokyo）で表示するための共通部品。
 *
 * 背景（PDCA V-02 / H-1）: API は `"2026-10-06T02:34:20"` のように時差情報（Z・+09:00 等）の
 * ない UTC の日時文字列を返すことがある。`new Date(...)` はこれを端末のローカル時刻として
 * 解釈するため、JST の端末では 9 時間手前に表示されていた。ここでは
 * 「時差情報のない日時は UTC」と解釈し、表示は端末の設定によらず常に日本時間にする。
 * チャット・入札更新時刻・管理画面など、API の日時を整形する全ての箇所でこれを使うこと。
 */

const JST_TIME_ZONE = "Asia/Tokyo";

/** 日付＋時刻（`YYYY-MM-DD` + `T` または空白 + `HH:MM` …）の形か。日付だけの文字列は対象外。 */
const DATE_TIME_PATTERN = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;
/** 末尾の時差情報（Z / +09:00 / +0900 / +09）。 */
const TZ_SUFFIX_PATTERN = /(Z|[+-]\d{2}(?::?\d{2})?)$/i;

/**
 * API の日時文字列を Date にする。時差情報のない日時は UTC として解釈する。
 * 解釈できない値（空・不正・非文字列）は null を返す（呼び出し側で表示を省く）。
 * @example parseApiDateTime("2026-10-06T02:34:20")       // 2026-10-06T02:34:20Z
 * @example parseApiDateTime("2026-10-06T11:34:20+09:00") // 2026-10-06T02:34:20Z
 */
export function parseApiDateTime(value: string | null | undefined): Date | null {
  if (typeof value !== "string") return null;
  let text = value.trim();
  if (text === "") return null;
  if (DATE_TIME_PATTERN.test(text)) {
    text = text.replace(" ", "T");
    const tz = TZ_SUFFIX_PATTERN.exec(text);
    if (!tz) {
      text += "Z";
    } else if (tz[1] !== "Z" && tz[1] !== "z") {
      // "+0900" / "+09" を ISO 8601 の "+09:00" に揃える（実装差を避ける）。
      const digits = tz[1].slice(1).replace(":", "");
      const hh = digits.slice(0, 2);
      const mm = digits.length >= 4 ? digits.slice(2, 4) : "00";
      text = `${text.slice(0, text.length - tz[1].length)}${tz[1][0]}${hh}:${mm}`;
    }
  }
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatWith(value: string | null | undefined, options: Intl.DateTimeFormatOptions): string {
  const date = parseApiDateTime(value);
  if (!date) return "";
  return new Intl.DateTimeFormat("ja-JP", { ...options, timeZone: JST_TIME_ZONE }).format(date);
}

/** 日本時間の時刻（例「11:34」）。解釈できなければ空文字。 */
export function formatJstTime(value: string | null | undefined): string {
  return formatWith(value, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

/** 日本時間の日付区切り（例「10月6日(火)」）。解釈できなければ空文字。 */
export function formatJstDateSeparator(value: string | null | undefined): string {
  return formatWith(value, { month: "long", day: "numeric", weekday: "short" });
}

/** 日本時間の日付（例「2026/10/6」）。解釈できなければ空文字。 */
export function formatJstDate(value: string | null | undefined): string {
  return formatWith(value, { year: "numeric", month: "numeric", day: "numeric" });
}

/** 日本時間の日付（例「2026年10月6日」）。解釈できなければ空文字。 */
export function formatJstDateLong(value: string | null | undefined): string {
  return formatWith(value, { year: "numeric", month: "long", day: "numeric" });
}

/** 日本時間の日付＋時刻（例「2026/10/6 11:34」）。解釈できなければ空文字。 */
export function formatJstDateTime(value: string | null | undefined): string {
  return formatWith(value, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hourCycle: "h23",
  });
}

/** 日本時間の日付＋時刻（秒つき。例「2026/10/6 11:34:18」）。運営画面の監査・活動表示用。解釈できなければ空文字。 */
export function formatJstDateTimeSeconds(value: string | null | undefined): string {
  return formatWith(value, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
}

/**
 * 日本時間（Asia/Tokyo）での「年-月」キー（例 "2026-10"）。月次集計の境界を端末の時刻帯に依らず JST で揃える。
 * 解釈できなければ null。
 */
export function jstYearMonthKey(value: string | Date | null | undefined): string | null {
  const date = value instanceof Date ? value : parseApiDateTime(value);
  if (!date || Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: JST_TIME_ZONE, year: "numeric", month: "2-digit" }).formatToParts(date);
  const year = parts.find((p) => p.type === "year")?.value;
  const month = parts.find((p) => p.type === "month")?.value;
  return year && month ? `${year}-${month}` : null;
}

/** 日本時間の月日＋時刻（例「10/6 11:34」）。入札の更新時刻など年を省く表示用。 */
export function formatJstMonthDayTime(value: string | null | undefined): string {
  return formatWith(value, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}
