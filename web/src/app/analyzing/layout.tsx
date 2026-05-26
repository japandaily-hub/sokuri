import type { Metadata } from "next";

/**
 * /analyzing 配下は sessionStorage 依存の中間状態画面。
 * 直接アクセスや検索流入を想定しないため noindex。
 */
export const metadata: Metadata = {
  title: "解析中…",
  robots: { index: false, follow: false },
};

export default function AnalyzingLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
