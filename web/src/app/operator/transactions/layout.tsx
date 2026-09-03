import type { Metadata } from "next";

/** /operator/transactions はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "取引一覧",
  description: "成約した取引の一覧と対応状況。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
