import type { Metadata } from "next";

/** /login はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "ログイン",
  description: "カタヅケにログインして、出品状況や業者とのやり取りを確認できます。",
  // L-2: 認証画面は検索に載せない（業者ログインと同じ扱い）。
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
