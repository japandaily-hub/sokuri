import type { NextConfig } from "next";

/**
 * Next.js 設定。
 * セキュリティヘッダ・フィンガープリント抑制・将来の画像最適化基盤。
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,

  // `X-Powered-By: Next.js` を抑制（フィンガープリント対策）
  poweredByHeader: false,

  // 静的画像最適化対象の許可ドメイン（外部画像追加時に拡張）
  images: {
    formats: ["image/avif", "image/webp"],
  },

  /**
   * 旧「アルバム一括査定」導線（/album, /album/submitted）の恒久リダイレクト。
   * 現行プロダクトは「カタヅケ（部屋ごと撮影 → /create）」へ移行済みで、
   * album フローは廃止。直URL・ブックマーク・検索/キャッシュ流入での迷い込みを塞ぐ。
   * - `permanent: true`（308）: 検索エンジンへ旧URL消滅を通知し評価を `/` へ集約する
   * - `/album/:path*`: submitted 等の配下も含めて一括で `/` へ寄せる
   * 注意: バックエンド（/api/v1/albums・albums テーブル）は本番適用済みのため不変更。
   */
  async redirects() {
    return [
      { source: "/album", destination: "/", permanent: true },
      { source: "/album/:path*", destination: "/", permanent: true },
    ];
  },

  /**
   * 全レスポンスへ付与するセキュリティヘッダ。
   * - HSTS: HTTPS 強制（subdomain 含む、preload 候補）
   * - nosniff: MIME スニッフィング抑止
   * - Referrer-Policy: クロスサイトリーク低減
   * - Permissions-Policy: camera は同一オリジンに限定（capture="environment" 使用のため）
   * - X-Frame-Options: clickjacking 対策（DENY）
   */
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(self), microphone=(), geolocation=()",
          },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
