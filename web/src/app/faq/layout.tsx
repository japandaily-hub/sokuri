import type { Metadata } from "next";

/** /faq はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "よくある質問",
  description: "カタヅケの使い方・料金・入札・訪問買取に関するよくある質問と回答。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
