import type { MetadataRoute } from "next";

/**
 * Next.js 15 File Convention: /robots.ts
 * クローラに対する許可方針とサイトマップ位置を提示する。
 *
 * - 中間ページ (/analyzing, /condition, /result) は sessionStorage 依存のため
 *   直接アクセス時に意味あるコンテンツが無い → クロール禁止。
 */
const SITE_URL = "https://sokuri.vercel.app";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/analyzing", "/condition", "/result"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
