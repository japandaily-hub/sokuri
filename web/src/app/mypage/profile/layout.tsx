import type { Metadata } from "next";

/** /mypage/profile はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "プロフィール設定",
  description: "お名前・連絡先・住所の設定。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
