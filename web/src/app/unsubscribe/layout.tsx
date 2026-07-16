import type { Metadata } from "next";

/** /unsubscribe はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "メール配信停止",
  description: "カタヅケからのお知らせメールの配信停止手続き。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
