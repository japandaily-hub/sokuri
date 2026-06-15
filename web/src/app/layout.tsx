import type { Metadata, Viewport } from "next";
import Link from "next/link";
import Script from "next/script";
import "./globals.css";
import { BrandMark, Icon } from "@/components/Icon";
import { Providers } from "./providers";
import { HeaderNav } from "@/components/kdz/HeaderNav";

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
    default: "カタヅケ — 部屋ごと撮るだけ、片付けと買取の見積もりが届く",
    template: "%s | カタヅケ",
  },
  description:
    "家の中をスマホで撮るだけ。AIが案件化し、登録リユース業者が見積もりで競います。比べて選ぶだけで、片付け・買取がまとめて終わる片付けプラットフォーム。",
  keywords: [
    "片付け 見積もり",
    "AI 査定",
    "リユース 業者",
    "不用品 買取",
    "買取 比較",
    "リユース",
    "片付け 業者",
  ],
  authors: [{ name: "カタヅケ" }],
  creator: "カタヅケ",
  publisher: "カタヅケ",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "ja_JP",
    url: SITE_URL,
    siteName: "カタヅケ",
    title: "カタヅケ — 部屋ごと撮るだけ、片付けと買取の見積もりが届く",
    description:
      "家の中をスマホで撮るだけ。AIが案件化し、登録業者が見積もりで競います。片付け・買取がまとめて終わる。",
    images: [
      {
        url: "/opengraph-image",
        width: 1200,
        height: 630,
        alt: "カタヅケ — 部屋ごと撮るだけ",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "カタヅケ — 部屋ごと撮るだけ、片付けと買取の見積もりが届く",
    description:
      "家の中をスマホで撮るだけ。AIが案件化し、業者が見積もりで競います。",
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
  name: "カタヅケ",
  url: SITE_URL,
  logo: `${SITE_URL}/icon.svg`,
  sameAs: [],
};

const WEBSITE_LD = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "カタヅケ",
  url: SITE_URL,
  inLanguage: "ja-JP",
  description:
    "家の中をスマホで撮るだけでAIが案件化し、登録リユース業者が見積もりで競う片付けプラットフォーム。",
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
  { href: "/operator/login", label: "買取業者の方はこちら" },
  { href: "/terms", label: "利用規約" },
  { href: "/privacy", label: "プライバシーポリシー" },
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
            <Link href="/" className="flex items-center gap-2.5" aria-label="カタヅケ トップへ">
              <BrandMark className="h-9 w-9" />
              <span className="flex items-baseline gap-1.5">
                <span className="text-lg font-bold tracking-tight text-slate-900">カタヅケ</span>
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

            <HeaderNav />
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
                  <span className="text-lg font-bold tracking-tight text-white">カタヅケ</span>
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
                        {item.href ? (
                          <Link
                            href={item.href}
                            className="text-slate-300 transition-colors hover:text-white"
                          >
                            {item.label}
                          </Link>
                        ) : (
                          item.label
                        )}
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
              <p className="mt-3 text-xs text-slate-400">© 2026 カタヅケ. All rights reserved.</p>
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
 