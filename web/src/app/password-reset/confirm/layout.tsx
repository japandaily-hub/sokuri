import type { Metadata } from "next";

/** /password-reset/confirm（再設定メールのリンク先）のメタデータ。
 *  URL のクエリに1回限りの token を含むため、
 *  - referrer: "no-referrer" … このページから読み込む資源・遷移先へ URL（token）を送らない
 *    （サイト全体の Referrer-Policy ヘッダより meta の指定がこの文書では優先される）
 *  - robots: noindex/nofollow … 検索に載せない
 *  canonical は付けない（token 付きの URL を正規 URL として扱わせない）。
 *  N-12（2周目監査・低）: 何も書かないと親（password-reset/layout.tsx）の canonical "/password-reset" を
 *  継承してしまうため、canonical: null で明示的に打ち消す。title も親のレイアウトが文字列の title を
 *  持つためルートの template（"%s | カタヅケ"）が届かず「| カタヅケ」が付かなかった。absolute で付ける。 */
export const metadata: Metadata = {
  title: { absolute: "新しいパスワードの設定 | カタヅケ" },
  alternates: { canonical: null },
  description: "メールでお送りしたリンクから、新しいパスワードを設定します。",
  referrer: "no-referrer",
  robots: { index: false, follow: false, nocache: true },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
