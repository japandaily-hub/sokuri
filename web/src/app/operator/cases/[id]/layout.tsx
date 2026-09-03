import type { Metadata } from "next";

/** /operator/cases/[id] はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "案件詳細",
  description: "案件の写真・品目・AI要約を確認して入札します。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
