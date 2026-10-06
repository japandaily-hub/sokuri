import type { Metadata } from "next";

/**
 * 公開ページのメタデータ（タイトル・説明・canonical・OGP・Twitter カード）を1か所で組み立てる。
 *
 * M-10: 子ページの layout / page が openGraph を書いていなかったため、全ページで og:title・og:url が
 * トップのままになり、SNS で共有するとどのページもトップとして表示されていた。Next.js の metadata は
 * openGraph をキー単位ではなくオブジェクトごと上書きするので、子ページで url と title だけを渡すと
 * siteName・locale・images が落ちる。ここで毎回すべての項目を組み立てて渡す。
 *
 * 本番 URL（SITE_URL）は独自ドメイン取得後に差し替える。root layout・robots.ts・sitemap.ts の
 * SITE_URL と同じ値にしておくこと。
 */
export const SITE_URL = "https://sokuri.vercel.app";
export const SITE_NAME = "カタヅケ";

/** 既定の OGP 画像（app/opengraph-image.tsx が配信する）。 */
export const DEFAULT_OG_IMAGE = {
  url: "/opengraph-image",
  width: 1200,
  height: 630,
  alt: "カタヅケ｜家まるごと片付け買取",
} as const;

/** title.template（"%s | カタヅケ"）と同じ形の、SNS 用の表示タイトル。 */
export function socialTitle(pageTitle: string): string {
  return `${pageTitle} | ${SITE_NAME}`;
}

export type PublicPageMetaInput = {
  /** サイト内の絶対パス（"/" から始まり、クエリ・ハッシュ・"//" を含まない）。 */
  path: string;
  /** ページ名（"| カタヅケ" は付けない。root layout の title.template が付ける）。 */
  title: string;
  description: string;
};

/**
 * path の形を検査する。誤った値（外部 URL・プロトコル相対 URL・クエリ付き）を og:url や canonical に
 * 入れると、検索エンジンや SNS が別のページとして扱うため、ビルド時（モジュール評価時）に止める。
 *
 * @throws {Error} path が "/" から始まらない、"//" を含む、または ? / # を含むとき
 */
export function assertSitePath(path: string): void {
  if (!path.startsWith("/") || path.includes("//") || /[?#\s]/.test(path)) {
    throw new Error(`公開ページのパスが不正です: ${JSON.stringify(path)}`);
  }
}

/**
 * 公開ページ用の Metadata を返す。各ページは `export const metadata = publicPageMetadata({...})` と書く。
 * robots は指定しない（root layout の index/follow を継承する）。
 */
export function publicPageMetadata({ path, title, description }: PublicPageMetaInput): Metadata {
  assertSitePath(path);
  const shareTitle = socialTitle(title);
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      locale: "ja_JP",
      siteName: SITE_NAME,
      url: path,
      title: shareTitle,
      description,
      images: [{ ...DEFAULT_OG_IMAGE }],
    },
    twitter: {
      card: "summary_large_image",
      title: shareTitle,
      description,
      images: [DEFAULT_OG_IMAGE.url],
    },
  };
}
