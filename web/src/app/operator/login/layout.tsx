import type { Metadata } from "next";

/** /operator/login はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "業者ログイン",
  description: "登録業者向けのログイン画面。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
