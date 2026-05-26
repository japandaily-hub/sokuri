import type { Metadata } from "next";
import "./globals.css";
import { BrandMark, Icon } from "@/components/Icon";

export const metadata: Metadata = {
  title: "ソクウリ — 写真1枚で最高値査定",
  description:
    "写真を撮るだけでAIが商品を識別。メルカリ・ヤフオク・買取店など最適な売却チャネルと査定額を即時提案します。",
};

/** ヘッダーのナビゲーション項目 */
const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/#features", label: "特徴" },
  { href: "/#categories", label: "カテゴリ" },
  { href: "/#how-it-works", label: "使い方" },
  { href: "/#channels", label: "対応チャネル" },
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
                  AI査定
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
              無料で査定
            </a>
          </div>
        </header>

        {/* ===== MAIN ===== */}
        <main className="w-full">{children}</main>

        {/* ===== FOOTER ===== */}
        <footer className="bg-brand-950 text-slate-300">
          <div className="container-aw py-14">
            <div className="flex flex-col gap-10 md:flex-row md:items-start md:justify-between">
              <div className="max-w-sm">
                <div className="flex items-center gap-2.5">
                  <BrandMark className="h-8 w-8" />
                  <span className="text-lg font-bold tracking-tight text-white">ソクウリ</span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">
                  写真1枚でAIが商品を識別。メルカリ・ヤフオク・買取店など、あなたの商品が
                  最も高く売れるチャネルを即時に提案します。
                </p>
              </div>

              <div className="flex gap-14">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                    サービス
                  </p>
                  <ul className="mt-4 space-y-3 text-sm">
                    <li>
                      <a href="/#categories" className="text-slate-400 transition-colors hover:text-white">
                        カテゴリ一覧
                      </a>
                    </li>
                    <li>
                      <a href="/#how-it-works" className="text-slate-400 transition-colors hover:text-white">
                        使い方
                      </a>
                    </li>
                    <li>
                      <a href="/#channels" className="text-slate-400 transition-colors hover:text-white">
                        対応チャネル
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
                査定額はAIによる参考値であり、実際の売却価格を保証するものではありません。
                売却チャネルの提案には広告（PR）を含む場合があります。
              </p>
              <p className="mt-3 text-xs text-slate-500">© 2026 ソクウリ. All rights reserved.</p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
