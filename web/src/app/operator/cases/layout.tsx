import type { Metadata } from "next";

/** /operator/cases はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "案件一覧",
  description: "入札を受け付けている片付け案件の一覧。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
