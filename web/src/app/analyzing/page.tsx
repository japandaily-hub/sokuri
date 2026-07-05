import { redirect } from "next/navigation";

/**
 * デザインレビュー A-3 対応: 旧査定ファネル（/analyzing → /condition → /result）は
 * 流入ゼロの孤立レガシー（PROJECT_STATE.md 確認済み）。URL 直打ち・古いブックマーク経由で
 * 旧デザインが露出するのを防ぐため、現行の出品導線 /create へリダイレクトする。
 */
export default function AnalyzingPage() {
  redirect("/create");
}
