import { redirect } from "next/navigation";

/** 2026-09-18 本採用: このデザインはトップページ（"/"）へ昇格した。
 *  検証中に共有した /lp のリンク・ブックマークが残っている場合に備え、恒久的に "/" へ転送する。
 *  旧トップの部品（_components・lp.css）は 2026-11-19 のトップ作り直しで削除した（git の履歴に残る）。 */
export default function LpRedirect() {
  redirect("/");
}
