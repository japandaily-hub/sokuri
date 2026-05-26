import Link from "next/link";

/**
 * Next.js 15 App Router: 404 ページ。
 * 既定の英語 404 を回避し、ブランド一貫した日本語画面を提示。
 */
export const metadata = {
  title: "ページが見つかりません",
};

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6">
      <div className="max-w-md text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
          404
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          ページが見つかりません
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">
          URL が正しいかご確認ください。お探しのページは移動・削除された可能性があります。
        </p>
        <div className="mt-6">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700"
          >
            トップへ戻る
          </Link>
        </div>
      </div>
    </div>
  );
}
