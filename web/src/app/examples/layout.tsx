import type { Metadata } from "next";

/** /examples はクライアントコンポーネントのため、メタデータはこのレイアウトで担保する。 */
export const metadata: Metadata = {
  title: "成約イメージ（モデルケース）",
  description:
    "カタヅケを使うと、どのように査定が集まり成約に至るのか。利用の流れがわかるモデルケース（架空の事例）をご紹介します。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
