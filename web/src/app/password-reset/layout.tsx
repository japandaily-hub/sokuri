import type { Metadata } from "next";

/** /password-reset はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "パスワード再設定",
  description: "パスワードをお忘れの方の再設定手続き。",
  alternates: { canonical: "/password-reset" },
  // H-6/L-2（2周目監査）: 認証まわりの手続き画面は検索に載せない（/login・/signup・confirm と揃える）。
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
