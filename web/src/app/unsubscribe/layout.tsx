import type { Metadata } from "next";

/** /unsubscribe はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "メールの受け取りについて",
  description: "カタヅケからお送りするメールの種類と、通知設定・退会手続きのご案内。",
  alternates: { canonical: "/unsubscribe" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
