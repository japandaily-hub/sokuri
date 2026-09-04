import type { Metadata } from "next";

/** /review はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "業者の評価",
  description: "取引完了後の評価・口コミ投稿。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
