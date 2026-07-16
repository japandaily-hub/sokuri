import type { Metadata } from "next";

/** /verify-email はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "メールアドレスの確認",
  description: "メールアドレス確認手続きのご案内。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
