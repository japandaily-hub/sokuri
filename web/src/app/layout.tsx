import type { Metadata } from "next";
import "./globals.css";
import { BrandMark, Icon } from "@/components/Icon";

export const metadata: Metadata = {
  title: "ソクウリ — 撮るだけ・待つだけ、買取業者から査定が届く",
  description:
    "不用品を1点ずつ撮るだけ。AIが1点ずつ仮査定し、たまった品物をまとめて登録業者へ。業者が競うから査定が伸びやすく、連絡が来るのは上位3社だけ。対応エリアは東京・千葉・埼玉・神奈川。",
  openGraph: {
    title: "ソクウリ — 撮るだけ・待つだけ、買取業者から査定が届く",
    description:
      "片付けたいのに動けないあなたへ。品物を1点ずつ撮るだけで、登録業者が査定額で競い、連絡が来るのは上位3社だけ。対応エリアは東京・千葉・埼玉・神奈川。",
    type: "website",
    locale: "ja_JP",
    siteName: "ソクウリ",
    images: [
      {
        url: "/img/og.png",
        width: 1200,
        height: 630,
        alt: "ソクウリ — 撮るだけ・待つだけ、買取業者から査定が届く",
      },
    ],
  },
};

/** ヘッダーのナビゲーション項目 */
const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/#story", label: "ご利用の物語" },
  { href: "/#how-it-works", label: "仕組み" },
  { href: "/#nego", label: "上位3社交渉" },
  { href: "/#area", label: "対応エリア" },
  { href: "/#safety", label: "安心・個人情報" },
  { href: "/#faq", label: "よくある質問" },
];

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body className="min-h-screen bg-slate-50 font-sans text-slate-900 antialiased">
        {/* ===== HEADER ===== */}
        <header className="sticky top-0 z-50 border-b border-slate-200/80 bg-white/85 backdrop-blur-md">
          <div className="container-aw flex h-16 items-center justify-between">
            <a href="/" className="flex items-center gap-2.5" aria-label="ソクウリ トップへ">
              <BrandMark className="h-9 w-9" />
              <span className="flex items-baseline gap-1.5">
                <span className="text-lg font-bold tracking-tight text-slate-900">ソクウリ</span>
                <span className="hidden text-[11px] font-semibold text-slate-400 sm:inline">
                  買取マッチング
                </span>
              </span>
            </a>

            <nav className="hidden items-center gap-7 lg:flex" aria-label="メインナビゲーション">
              {NAV_ITEMS.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  className="text-sm font-medium text-slate-600 transition-colors hover:text-brand-700"
                >
                  {item.label}
                </a>
              ))}
            </nav>

            <a
              href="/"
              className="inline-flex items-center gap-1.5 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
            >
              <Icon name="camera" className="h-4 w-4" />
              査定を依頼
            </a>
          </div>
        </header>

        {/* ===== MAIN ===== */}
        <main className="w-full">{children}</main>

        {/* ===== FOOTER ===== */}
        <footer className="bg-brand-950 pb-20 text-slate-300 lg:pb-0">
          <div className="container-aw py-14">
            <div className="flex flex-col gap-10 md:flex-row md:items-start md:justify-between">
              <div className="max-w-sm">
                <div className="flex items-center gap-2.5">
                  <BrandMark className="h-8 w-8" />
                  <span className="text-lg font-bold tracking-tight text-white">ソクウリ</span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">
                  不用品を1点ずつ撮るだけで、登録買取業者から査定が届く買取マッチングサービス。
                  ソクウリは取引の「場」を提供し、買取・回収・運搬は各業者が行います。
                </p>
              </div>

              <div className="flex gap-14">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                    サービス
                  </p>
                  <ul className="mt-4 space-y-3 text-sm">
                    <li>
                      <a href="/#how-it-works" className="text-slate-400 transition-colors hover:text-white">
                        ご利用の流れ
                      </a>
                    </li>
                    <li>
                      <a href="/#nego" className="text-slate-400 transition-colors hover:text-white">
                        上位3社交渉
                      </a>
                    </li>
                    <li>
                      <a href="/#area" className="text-slate-400 transition-colors hover:text-white">
                        対応エリア
                      </a>
                    </li>
                  </ul>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                    その他
                  </p>
                  <ul className="mt-4 space-y-3 text-sm">
                    <li>
                      <a href="#" className="text-slate-400 transition-colors hover:text-white">
                        利用規約
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-slate-400 transition-colors hover:text-white">
                        プライバシーポリシー
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-slate-400 transition-colors hover:text-white">
                        お問い合わせ
                      </a>
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            <div className="mt-12 border-t border-white/10 pt-6">
              <p className="text-xs leading-relaxed text-slate-500">
                査定額はAIと業者による参考値であり、最終的な買取額は業者の現物査定により決定します。
                業者紹介・手数料が絡む表示には広告（PR）を含む場合があります。
              </p>
              <p className="mt-3 text-xs text-slate-500">© 2026 ソクウリ. All rights reserved.</p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
