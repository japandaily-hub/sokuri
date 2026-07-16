import type { Metadata } from "next";

/** /examples はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "成約事例",
  description: "カタヅケで成約した片付け買取の事例を紹介します。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
