import type { Metadata } from "next";

/** /schedule はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "訪問日程の調整",
  description: "引き取り日程の確認・確定。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
