import type { Metadata } from "next";

/**
 * /result は査定結果の表示画面。assessment_id 付きでのアクセスを想定。
 * 個別結果は SEO 対象外のため noindex。
 */
export const metadata: Metadata = {
  title: "査定結果",
  robots: { index: false, follow: false },
};

export default function ResultLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
