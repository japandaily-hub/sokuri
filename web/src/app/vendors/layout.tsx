import type { Metadata } from "next";

/** /vendors はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "登録業者一覧",
  description: "カタヅケの登録業者の評価と口コミ。成約したユーザーの投稿をそのまま公開しています。",
  alternates: { canonical: "/vendors" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
