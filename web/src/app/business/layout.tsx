import type { Metadata } from "next";

/** /business はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "業者向けのご案内",
  description: "写真だけで買取総額を入札。下見なし・一斉架電なしの効率的な仕入れルート。カタヅケの業者登録のご案内。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
