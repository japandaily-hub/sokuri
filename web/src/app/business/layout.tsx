import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/seo";

/** /business はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = publicPageMetadata({
  path: "/business",
  title: "業者向けのご案内",
  description: "写真だけで買取総額を入札。下見なし・一斉の営業電話なしの効率的な仕入れルート。カタヅケの業者登録のご案内。",
});

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
