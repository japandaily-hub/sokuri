import type { Metadata } from "next";

/**
 * /album: 「まとめてソクウリ」一括査定アルバム作成画面。
 * - Phase 1: 複数写真アップロード → AI 識別 + 個別見積もり → 合計表示
 * - Phase 2 以降: 業者へ匿名一括入札依頼（営業電話ゼロ）
 */
export const metadata: Metadata = {
  title: "まとめて査定（アルバム作成）",
  description:
    "家中の不用品をまとめて写真撮影。AIが商品を識別し、業者が匿名で一括入札。営業電話ゼロで最高額が分かります。",
  alternates: {
    canonical: "/album",
  },
};

export default function AlbumLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
