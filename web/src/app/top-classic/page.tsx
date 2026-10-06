import { redirect } from "next/navigation";

/** 旧トップ（2026-09-18 に現トップへ置き換え・noindex で退避していたもの）。
 *
 *  M-13: 退避後も直接開ける状態で、「まとめて回収」「査定」などの旧い語と、廃棄物の扱いを断定する
 *  表現（「値がつかない物も、まとめて回収」）が残っていた。公開を続ける理由がないため、/lp と同じく
 *  トップ（"/"）へ転送する。旧デザインのソース（page.tsx・katazuke-top.css）は git の履歴に残る。
 *  転送先を検索エンジンが読めるよう、robots.ts の Disallow からは外した。 */
export default function TopClassicRedirect() {
  redirect("/");
}
