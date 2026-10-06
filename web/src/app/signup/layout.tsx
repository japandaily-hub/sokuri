import type { Metadata } from "next";

/** /signup はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "会員登録",
  description: "カタヅケの無料会員登録。家じゅうの不用品をまとめて出品できます。",
  // L-2: 認証画面は検索に載せない（業者ログインと同じ扱い）。
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
