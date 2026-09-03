import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { Noto_Serif_JP, Noto_Sans_JP, Montserrat, Libre_Baskerville } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { KdzIconSprite } from "@/components/kdz/Icons";
import { SiteChrome } from "@/components/kdz/SiteChrome";
import { ScrollProgress } from "@/components/kdz/interactions";

/** 書体は next/font/google でビルド時に自己ホストする（外部オリジンへの実行時リクエストをゼロにし、
 *  CSP/SRI 不在の攻撃面と訪問者IPの第三者送信を同時に消す）。CSS 側は katazuke.css の
 *  --serif / --ui / --en / --en-display がこれらの変数を先頭で参照する。 */
const fontSerif = Noto_Serif_JP({ subsets: ["latin"], weight: ["400", "600"], display: "swap", variable: "--font-serif" });
const fontUi = Noto_Sans_JP({ subsets: ["latin"], weight: ["400", "500"], display: "swap", variable: "--font-ui" });
const fontEn = Montserrat({ subsets: ["latin"], weight: ["600"], display: "swap", variable: "--font-en" });
const fontEnDisplay = Libre_Baskerville({ subsets: ["latin"], weight: ["400"], display: "swap", variable: "--font-en-display" });

/**
 * 本番公開 URL。独自ドメイン取得後に差し替え。
 */
const SITE_URL = "https://sokuri.vercel.app";

/**
 * Next.js 15 App Router の Metadata API による SEO/SNS 最適化。
 * デザインハンドオフのメッセージング（家まるごと・まとめて片付け買取）に更新。
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "カタヅケ｜家まるごと、まとめて片付け買取。撮るだけ・待つだけ",
    template: "%s | カタヅケ",
  },
  description:
    "家じゅうの不用品を、まとめて撮って待つだけ。登録業者が買取総額で競い合い、連絡が来るのはあなたが選んだ1社だけ。値がつかない物もまとめて回収。営業電話に追われない、家まるごとの片付け買取マッチング。",
  keywords: [
    "片付け 買取",
    "不用品 買取",
    "まとめ 買取",
    "遺品整理 買取",
    "実家じまい",
    "リユース 業者",
    "買取 比較",
  ],
  authors: [{ name: "カタヅケ" }],
  creator: "カタヅケ",
  publisher: "カタヅケ",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    locale: "ja_JP",
    url: SITE_URL,
    siteName: "カタヅケ",
    title: "カタヅケ｜家まるごと、まとめて片付け買取",
    description:
      "まとめて撮って待つだけ。業者が買取総額で競い合います。連絡は選んだ1社だけ。値がつかない物もまとめて回収。",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "カタヅケ｜家まるごと片付け買取" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "カタヅケ｜家まるごと、まとめて片付け買取",
    description: "まとめて撮って待つだけ。業者が買取総額で競い合います。連絡は選んだ1社だけ。",
    images: ["/opengraph-image"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
  },
  formatDetection: { telephone: false, email: false, address: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#527e52",
};

/** 構造化データ: Organization + WebSite（全ページ共通） */
const ORG_LD = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "カタヅケ",
  url: SITE_URL,
  logo: `${SITE_URL}/icon.svg`,
  description:
    "家まるごと、まとめて片付け買取。業者が買取総額で競い合う、営業電話に追われない不用品買取マッチング。",
  areaServed: ["東京都", "千葉県", "埼玉県", "神奈川県"],
  sameAs: [],
};

const WEBSITE_LD = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "カタヅケ",
  url: SITE_URL,
  inLanguage: "ja-JP",
  description:
    "家じゅうの不用品を、まとめて撮って待つだけ。登録業者が買取総額で競い合う片付け買取マッチング。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja" className={`${fontSerif.variable} ${fontUi.variable} ${fontEn.variable} ${fontEnDisplay.variable}`}>
      <head>
        {/* 明朝は本文全面に効くため、CSS パース完了を待たずに書体取得を開始させる（LCP 対策） */}
      </head>
      {/* antialiased は明朝 400 で字画が痩せるため付与しない（globals.css @layer base も auto） */}
      <body className="min-h-screen">
        {/* スキップリンク（WCAG 2.4.1） */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[300] focus:rounded-md focus:bg-brand-600 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
        >
          本文へスキップ
        </a>

        {/* デザイン共通の SVG アイコンスプライト（一度だけ） */}
        <KdzIconSprite />
        <ScrollProgress />

        <Providers>
          <SiteChrome>{children}</SiteChrome>
        </Providers>

        {/* JSON-LD */}
        <Script
          id="ld-organization"
          type="application/ld+json"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(ORG_LD).replace(/</g, "\u003c") }}
        />
        <Script
          id="ld-website"
          type="application/ld+json"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(WEBSITE_LD).replace(/</g, "\u003c") }}
        />
      </body>
    </html>
  );
}
