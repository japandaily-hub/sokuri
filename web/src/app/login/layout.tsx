import type { Metadata } from "next";

/** /login はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "ログイン",
  description: "カタヅケにログインして、出品状況や業者とのやり取りを確認できます。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
