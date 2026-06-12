import type { Metadata, Viewport } from "next";
import Link from "next/link";
import Script from "next/script";
import "./globals.css";
import { BrandMark, Icon } from "@/components/Icon";
import { Providers } from "./providers";

/**
 * 本番公開 URL。
 * Vercel デプロイ URL を直接記述。独自ドメイン取得後に差し替え。
 */
const SITE_URL = "https://sokuri.vercel.app";

/**
 * Next.js 15 App Router の Metadata API による SEO/SNS シェア最適化。
 * - metadataBase: og:image / canonical を絶対 URL 化するベース
 * - openGraph / twitter: X・Slack・LINE シェア時のリッチプレビュー
 * - robots: 既定でインデックス許可（中間ページは個別で noindex）
 * - alternates.canonical: 重複コンテンツ対策
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "ソクウリ — 写真1枚でAI査定、メルカリ・ヤフオク含む最高値で売却",
    template: "%s | ソクウリ",
  },
  description:
    "写真を撮るだけでAIが商品を識別。メルカリ・ヤフオク・買取店など主要販売チャネルを横断比較し、最も高く売れる場所と査定額を30秒で提示します。完全無料・登録不要・営業電話ゼロ。",
  keywords: [
    "不用品 査定",
    "AI 査定",
    "メルカリ 比較",
    "ヤフオク 査定",
    "買取 比較",
    "リユース",
    "写真 査定",
  ],
  authors: [{ name: "ソクウリ" }],
  creator: "ソクウリ",
  publisher: "ソクウリ",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "ja_JP",
    url: SITE_URL,
    siteName: "ソクウリ",
    title: "ソクウリ — 写真1枚でAI査定、最高値で売却",
    description:
      "写真を撮るだけでAIが商品を識別。メルカリ・ヤフオク・買取店を横断比較し、最も高く売れる場所と査定額を30秒で提示。完全無料・登録不要。",
    images: [
      {
        url: "/opengraph-image",
        width: 1200,
        height: 630,
        alt: "ソクウリ — 写真1枚で最高値査定",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ソクウリ — 写真1枚でAI査定、最高値で売却",
    description:
      "写真を撮るだけでAIが商品を識別。最も高く売れる場所と査定額を30秒で提示。",
    images: ["/opengraph-image"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  formatDetection: {
    telephone: false,
    email: false,
    address: false,
  },
};

/**
 * Next.js 15 で metadata から分離された viewport / themeColor。
 * theme-color はモバイルブラウザのアドレスバー色（ブランド色）。
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#1f54de",
};

/** 構造化データ: Organization + WebSite（全ページ共通） */
const ORG_LD = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "ソクウリ",
  url: SITE_URL,
  logo: `${SITE_URL}/icon.svg`,
  sameAs: [],
};

const WEBSITE_LD = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "ソクウリ",
  url: SITE_URL,
  inLanguage: "ja-JP",
  description:
    "写真1枚でAIが商品を識別し、メルカリ・ヤフオク・買取店を横断比較して最も高く売れる場所を提示する無料の査定サービス。",
};

/** ヘッダーのナビゲーション項目 */
const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/album", label: "まとめて査定" },
  { href: "/#features", label: "特徴" },
  { href: "/#categories", label: "カテゴリ" },
  { href: "/#how-it-works", label: "使い方" },
  { href: "/#faq", label: "よくある質問" },
];

/**
 * フッターのリンク。
 * `href` が null のものは未実装のため、リンクとして扱わずプレーンテキスト化（a11y: 偽リンク禁止）。
 */
const FOOTER_LEGAL: { href: string | null; label: string }[] = [
  { href: null, label: "利用規約（準備中）" },
  { href: null, label: "プライバシーポリシー（準備中）" },
  { href: null, label: "お問い合わせ（準備中）" },
];

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body className="min-h-screen bg-slate-50 font-sans text-slate-900 antialiased">
        {/* スキップリンク（WCAG 2.4.1） */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-md focus:bg-brand-600 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
        >
          本文へスキップ
        </a>

        {/* ===== HEADER ===== */}
        <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur-md">
          <div className="container-aw flex h-16 items-center justify-between">
            <Link href="/" className="flex items-center gap-2.5" aria-label="ソクウリ トップへ">
              <BrandMark className="h-9 w-9" />
              <span className="flex items-baseline gap-1.5">
                <span className="text-lg font-bold tracking-tight text-slate-900">ソクウリ</span>
                <span className="hidden text-[11px] font-semibold text-slate-500 sm:inline">
                  AI査定
                </span>
              </span>
            </Link>

            <nav className="hidden items-center gap-7 lg:flex" aria-label="メインナビゲーション">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="text-sm font-medium text-slate-700 transition-colors hover:text-brand-700"
                >
                  {item.label}
                </Link>
              ))}
            </nav>

            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
            >
              <Icon name="camera" className="h-4 w-4" />
              無料で査定
            </Link>
          </div>
        </header>

        {/* ===== MAIN ===== */}
        <main id="main" className="w-full">
          <Providers>{children}</Providers>
        </main>

        {/* ===== FOOTER ===== */}
        <footer className="bg-brand-950 text-slate-300">
          <div className="container-aw py-14">
            <div className="flex flex-col gap-10 md:flex-row md:items-start md:justify-between">
              <div className="max-w-sm">
                <div className="flex items-center gap-2.5">
                  <BrandMark className="h-8 w-8" />
                  <span className="text-lg font-bold tracking-tight text-white">ソクウリ</span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-slate-300">
                  写真1枚でAIが商品を識別。メルカリ・ヤフオク・買取店など、あなたの商品が
                  最も高く売れるチャネルを即時に提案します。
                </p>
              </div>

              <div className="flex gap-14">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    サービス
                  </p>
                  <ul className="mt-4 space-y-3 text-sm">
                    <li>
                      <Link
                        href="/#categories"
                        className="text-slate-300 transition-colors hover:text-white"
                      >
                        カテゴリ一覧
                      </Link>
                    </li>
                    <li>
                      <Link
                        href="/#how-it-works"
                        className="text-slate-300 transition-colors hover:text-white"
                      >
                        使い方
                      </Link>
                    </li>
                    <li>
                      <Link
                        href="/#channels"
                        className="text-slate-300 transition-colors hover:text-white"
                      >
                        対応チャネル
                      </Link>
                    </li>
                  </ul>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    その他
                  </p>
                  <ul className="mt-4 space-y-3 text-sm">
                    {FOOTER_LEGAL.map((item) => (
                      <li key={item.label} className="text-slate-400">
                        {item.label}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            <div className="mt-12 border-t border-white/10 pt-6">
              <p className="text-xs leading-relaxed text-slate-400">
                査定額はAIによる参考値であり、実際の売却価格を保証するものではありません。
                売却チャネルの提案には広告（PR）を含む場合があります。
              </p>
              <p className="mt-3 text-xs text-slate-400">© 2026 ソクウリ. All rights reserved.</p>
            </div>
          </div>
        </footer>

        {/* JSON-LD: Organization */}
        <Script
          id="ld-organization"
          type="application/ld+json"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(ORG_LD) }}
        />
        {/* JSON-LD: WebSite */}
        <Script
          id="ld-website"
          type="application/ld+json"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(WEBSITE_LD) }}
        />
      </body>
    </html>
  );
}
