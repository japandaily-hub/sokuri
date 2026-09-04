import type { Metadata } from "next";

/** /vendors/[id] はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "業者プロフィール",
  description: "登録業者の公開プロフィール。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
