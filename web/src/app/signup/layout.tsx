import type { Metadata } from "next";

/** /signup はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "会員登録",
  description: "カタヅケの無料会員登録。家じゅうの不用品をまとめて出品できます。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
