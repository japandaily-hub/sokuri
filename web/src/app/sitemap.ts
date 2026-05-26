import type { MetadataRoute } from "next";

/**
 * Next.js 15 File Convention: /sitemap.ts
 * 検索エンジン向けインデックス対象ページを列挙。
 * 中間ページは noindex 扱いのため含めない。
 */
const SITE_URL = "https://sokuri.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: `${SITE_URL}/`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1.0,
    },
  ];
}
