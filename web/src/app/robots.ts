import type { MetadataRoute } from "next";

/**
 * Next.js 15 File Convention: /robots.ts
 * クローラに対する許可方針とサイトマップ位置を提示する。
 *
 * - 中間ページ (/analyzing, /condition, /result) は sessionStorage 依存のため
 *   直接アクセス時に意味あるコンテンツが無い → クロール禁止。
 * - /top-classic（旧トップ）は 2026-10-06 から "/" へ転送する（M-13）。転送を検索エンジンが
 *   読めるよう、クロール禁止の対象から外した。
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
