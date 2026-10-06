import type { Metadata } from "next";

/** /verify-email はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "メールアドレスの確認",
  description: "メールアドレス確認手続きのご案内。",
  // H-1/L-2: 認証まわりの案内画面は検索に載せない。
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
