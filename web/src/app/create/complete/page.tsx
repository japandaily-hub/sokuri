/**
 * 出品完了（/create/complete）。
 * 実導線からは到達しない孤立ページで、受付番号・カウントダウン・LINE連携ボタンは
 * いずれもバックエンド未配線の虚偽表示だった。出品完了後の実際の遷移先である
 * /mypage へサーバー側でリダイレクトする。
 */

import { redirect } from "next/navigation";

export default function CreateCompletePage() {
  redirect("/mypage");
}
