import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/seo";

/** /vendors はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = publicPageMetadata({
  path: "/vendors",
  title: "登録業者一覧",
  description: "カタヅケの登録業者の評価と口コミ。成約したユーザーの投稿をそのまま公開しています。",
});

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
