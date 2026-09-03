import type { Metadata } from "next";

/** /operator はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "業者ダッシュボード",
  description: "登録業者向けの管理画面。入札中の案件・交渉中の取引・成約状況を確認できます。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
