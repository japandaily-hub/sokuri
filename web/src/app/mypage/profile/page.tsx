/**
 * 会員情報・設定（/mypage/profile）— 一時的に /mypage へリダイレクト。
 *
 * デザインハンドオフ版の実装（モック: 山田花子・未配線のプロフィール編集/通知設定/
 * パスワード変更フォーム）は git 履歴に保存されている（redirect化前のコミットを参照）。
 * ユーザー情報の更新系バックエンドAPI（プロフィール編集・パスワード変更）が
 * 実装されたら、履歴から復元して実配線すること。
 * 未配線のままだとログインユーザーに架空の氏名（山田花子）を表示し、保存も
 * 効かないため、本番公開前にリダイレクト化した（2026-07-16）。
 */
import { redirect } from "next/navigation";

export default function MypageProfileRedirect() {
  redirect("/mypage");
}
