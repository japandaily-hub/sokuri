import type { Metadata } from "next";

/** /verify-email はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。
 *  本ページはバックエンド検証を伴わない完了表示のみで、?email= はクエリ由来の未検証値
 *  （コンテンツ・スプーフィングに悪用され得る）のため noindex とする。 */
export const metadata: Metadata = {
  title: "メールアドレスの確認",
  description: "メールアドレス確認手続きのご案内。",
  robots: { index: false, follow: false },
  alternates: { canonical: "/verify-email" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
