import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/seo";

/** /examples はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = publicPageMetadata({
  path: "/examples",
  title: "利用イメージ（モデルケース）",
  description:
    "カタヅケを使うと、どのように入札が集まり成約に至るのか。利用の流れがわかるモデルケース（架空の事例）をご紹介します。",
});

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
