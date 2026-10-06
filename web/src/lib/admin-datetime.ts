/**
 * 運営画面の日時整形（React 非依存）。
 *
 * API の日時は SQLite 等で時差情報を落とした素の ISO 文字列（"2026-10-06T02:34:18"）で返ることがある。
 * `new Date()` はこれを端末のローカル時刻として解釈するため、UTC の値がそのまま日本時間として出て
 * 約9時間ずれる（ペルソナ監査 H-1）。ここでは「時差情報のない日時文字列は UTC」とみなし、
 * 端末の設定に依らず常に日本時間（Asia/Tokyo）で表示する。
 * 統合時は FA 担当の共通関数へ寄せる（この関数の契約は同じ）。
 */

const TZ_DESIGNATOR = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i;
const DATE_TIME_LIKE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/** 時差情報のない日時文字列は UTC として解釈した Date を返す。解釈できなければ null。 */
export function parseApiDateTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const text = value.trim();
  if (!text) return null;
  let normalized = text;
  if (DATE_TIME_LIKE.test(text)) {
    normalized = text.replace(" ", "T");
    if (!TZ_DESIGNATOR.test(normalized)) normalized += "Z";
  }
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

const DATE_TIME_FORMAT = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const DATE_FORMAT = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "numeric",
  day: "numeric",
});

/** 日本時間の「2026/10/6 11:34:18」。空・不正値は "—"。 */
export function formatAdminDateTime(value: string | null | undefined): string {
  const date = parseApiDateTime(value);
  return date ? DATE_TIME_FORMAT.format(date) : "—";
}

/** 日本時間の「2026/10/6」。空・不正値は "—"。 */
export function formatAdminDate(value: string | null | undefined): string {
  const date = parseApiDateTime(value);
  return date ? DATE_FORMAT.format(date) : "—";
}
