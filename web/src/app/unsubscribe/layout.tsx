import type { Metadata } from "next";

/** /unsubscribe はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "メールの受け取りについて",
  description: "カタヅケからお送りするメールの種類と、通知設定・退会手続きのご案内。",
  // L-2: メール配信の案内は検索に載せない。
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
