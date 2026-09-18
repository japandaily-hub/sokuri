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
    name: "カタヅケ｜家まるごと、まとめて片付け買取",
    short_name: "カタヅケ",
    description:
      "家じゅうの不用品を、1点ずつ撮って、あとは待つだけ。登録業者が買取総額で競い合う、家まるごとの片付け買取マッチング。",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#1447e0",
    lang: "ja",
    orientation: "portrait",
    categories: ["shopping", "lifestyle", "utilities"],
    icons: [
      {
        src: "/icon.png",
        sizes: "32x32",
        type: "image/png",
      },
      {
        src: "/apple-icon.png",
        sizes: "180x180",
        type: "image/png",
        purpose: "any",
      },
    ],
    shortcuts: [
      {
        name: "出品する",
        short_name: "出品",
        description: "不用品を1点ずつ撮って、まとめて出品する",
        url: "/create",
      },
      {
        name: "マイページ",
        short_name: "マイページ",
        description: "届いた入札や取引の状況を確認する",
        url: "/mypage",
      },
    ],
  };
}
