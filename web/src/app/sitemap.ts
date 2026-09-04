import type { MetadataRoute } from "next";

/**
 * Next.js 15 File Convention: /sitemap.ts
 * 検索エンジン向けインデックス対象ページを列挙。
 * 中間ページは noindex 扱いのため含めない。
 */
const SITE_URL = "https://sokuri.vercel.app";

/** 静的な公開ページ（動的ルート /vendors/[id] は対象外）。 */
const STATIC_PUBLIC_PATHS = [
  "/company",
  "/faq",
  "/contact",
  "/legal",
  "/privacy",
  "/terms",
  "/business",
  "/examples",
  "/photo-guide",
  "/vendors",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return [
    {
      url: `${SITE_URL}/`,
      lastModified,
      changeFrequency: "weekly",
      priority: 1.0,
    },
    ...STATIC_PUBLIC_PATHS.map((path) => ({
      url: `${SITE_URL}${path}`,
      lastModified,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
