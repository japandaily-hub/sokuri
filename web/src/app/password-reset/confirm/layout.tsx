import type { Metadata } from "next";

/** /password-reset/confirm（再設定メールのリンク先）のメタデータ。
 *  URL のクエリに1回限りの token を含むため、
 *  - referrer: "no-referrer" … このページから読み込む資源・遷移先へ URL（token）を送らない
 *    （サイト全体の Referrer-Policy ヘッダより meta の指定がこの文書では優先される）
 *  - robots: noindex/nofollow … 検索に載せない
 *  canonical は付けない（token 付きの URL を正規 URL として扱わせない）。 */
export const metadata: Metadata = {
  title: "新しいパスワードの設定",
  description: "メールでお送りしたリンクから、新しいパスワードを設定します。",
  referrer: "no-referrer",
  robots: { index: false, follow: false, nocache: true },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
