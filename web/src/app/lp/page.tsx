import { redirect } from "next/navigation";

/** 2026-09-18 本採用: このデザインはトップページ（"/"）へ昇格した。
 *  検証中に共有した /lp のリンク・ブックマークが残っている場合に備え、恒久的に "/" へ転送する。
 *  _components・lp.css はトップページ（app/page.tsx）から相対パスで参照され続けるため残す。 */
export default function LpRedirect() {
  redirect("/");
}
