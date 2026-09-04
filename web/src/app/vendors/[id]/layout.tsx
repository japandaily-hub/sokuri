import type { Metadata } from "next";

/**
 * /vendors/[id] はクライアントコンポーネントのため、タブ名・説明はこのレイアウトで担保する。
 * 動的ルートのため canonical は generateMetadata で params から組み立てる
 * （静的な export const metadata では自ページの id を埋め込めない）。
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  return {
    title: "業者プロフィール",
    description: "登録業者の公開プロフィール。",
    alternates: { canonical: `/vendors/${encodeURIComponent(id)}` },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
