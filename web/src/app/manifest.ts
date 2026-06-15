import type { MetadataRoute } from "next";

/**
 * Next.js 15 File Convention: /manifest.webmanifest
 *
 * PWA 化: ホーム画面追加可能化、theme-color によるネイティブ風表示。
 * Service Worker は別途実装（Phase 2 で next-pwa or 手書き Workbox）。
 *
 * 採用判断（React Native vs PWA）:
 *   - 既存 Next.js を破棄せず、ホーム画面アイコン・theme-color・standalone 表示で
 *     ネイティブ風 UX を実現する
 *   - 業者ダッシュボードは PC 操作前提のため Web 必須。フロント層を統一できる
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "カタヅケ — 部屋ごと撮るだけAI片付け査定",
    short_name: "カタヅケ",
    description:
      "部屋ごと撮るだけ。AIが片付け・不用品を案件化し、リユース業者の見積もりが届くマッチングサービス。",
    start_url: "/",
    display: "standalone",
    background_color: "#f8fafc",
    theme_color: "#1f54de",
    lang: "ja",
    orientation: "portrait",
    categories: ["shopping", "lifestyle", "utilities"],
    icons: [
      {
        src: "/icon",
        sizes: "32x32",
        type: "image/png",
      },
      {
        src: "/opengraph-image",
        sizes: "1200x630",
        type: "image/png",
        purpose: "any",
      },
    ],
    shortcuts: [
      {
        name: "1点を査定",
        short_name: "単品査定",
        description: "1 点の不用品を撮影して即時査定",
        url: "/",
      },
      {
        name: "まとめて査定",
        short_name: "まとめて",
        description: "部屋ごと撮影して片付け・不用品をまとめて依頼",
        url: "/create",
      },
    ],
  };
}
