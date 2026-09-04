import type { Metadata } from "next";

/** /mypage はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  // 配下（プロフィール設定・退会）にも「| カタヅケ」を継承させる
  title: { default: "マイページ", template: "%s | カタヅケ" },
  description: "出品状況・入札・取引の確認。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
