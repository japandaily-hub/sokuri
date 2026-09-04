import type { Metadata } from "next";

/** /operator/signup はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "業者登録",
  description: "招待コードによる業者アカウントの作成。",
  alternates: { canonical: "/operator/signup" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
