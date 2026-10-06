/**
 * 運営画面の日時整形（React 非依存）。`datetime.ts` の薄いラッパー。
 *
 * 解釈（時差情報のない日時文字列は UTC・`+0900`/`+09` の正規化）と日本時間（Asia/Tokyo）での整形は
 * `datetime.ts` が唯一の実装。ここは「空・不正値は '—' で表示する」運営画面向けの規約だけを足す
 * （ペルソナ監査 H-1。QA L1 で parseApiDateTime の重複を解消）。
 */

import { formatJstDate, formatJstDateTimeSeconds, parseApiDateTime } from "./datetime.ts";

export { parseApiDateTime };

/** 空・不正値の表示。 */
const EMPTY_LABEL = "—";

/** 日本時間の「2026/10/6 11:34:18」。空・不正値は "—"。 */
export function formatAdminDateTime(value: string | null | undefined): string {
  return formatJstDateTimeSeconds(value) || EMPTY_LABEL;
}

/** 日本時間の「2026/10/6」。空・不正値は "—"。 */
export function formatAdminDate(value: string | null | undefined): string {
  return formatJstDate(value) || EMPTY_LABEL;
}
