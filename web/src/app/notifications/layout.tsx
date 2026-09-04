import type { Metadata } from "next";

/** /notifications はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "通知設定",
  description: "メール・LINE通知の設定。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
