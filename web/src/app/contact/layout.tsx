import type { Metadata } from "next";

/** /contact はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "お問い合わせ",
  description: "カタヅケへのお問い合わせ窓口。サービス・業者登録・提携のご相談はこちら。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
