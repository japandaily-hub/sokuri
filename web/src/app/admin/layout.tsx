import type { Metadata } from "next";

/** /admin はクライアントコンポーネントのため、タブ名・noindex はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "管理画面",
  description: "カタヅケ運営用の管理画面。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
