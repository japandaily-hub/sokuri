/**
 * 退会・アカウント削除（/mypage/withdraw）— 一時的に /mypage へリダイレクト。
 *
 * デザインハンドオフ版の実装（削除確認UI。実削除APIは未実装で、完了パネルは
 * デモ表示のみ・件数もモック値）は git 履歴に保存されている（redirect化前の
 * コミットを参照）。アカウント削除バックエンドAPIが実装されたら、履歴から
 * 復元して実配線すること。
 * 「削除完了」を装うデモ挙動が本番に露出するのを防ぐためリダイレクト化した
 * （2026-07-16）。アカウント削除の依頼は当面サポート窓口（/contact）で受ける。
 */
import { redirect } from "next/navigation";

export default function MypageWithdrawRedirect() {
  redirect("/mypage");
}
