import type { Metadata } from "next";

/** /operator/transactions/[id] はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "取引詳細",
  description: "取引の詳細・訪問日程・減額申請。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
