import type { Metadata } from "next";

/** /password-reset はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "パスワード再設定",
  description: "パスワードをお忘れの方の再設定手続き。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
