import type { Metadata } from "next";

/** /chat/[id] はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "交渉チャット",
  description: "成約した業者とのやり取りと日程調整。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
