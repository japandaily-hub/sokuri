import type { Metadata } from "next";

/** /cases はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。 */
export const metadata: Metadata = {
  // 配下（案件詳細）にも「| カタヅケ」を継承させる
  title: { default: "マイ案件", template: "%s | カタヅケ" },
  description: "依頼した片付け案件の一覧。",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
