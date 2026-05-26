import type { Metadata } from "next";

/**
 * /condition は AI 識別結果からコンディション選択を行う中間ページ。
 * sessionStorage 依存のため noindex。
 */
export const metadata: Metadata = {
  title: "コンディションを選択",
  robots: { index: false, follow: false },
};

export default function ConditionLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
