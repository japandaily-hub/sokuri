"use client";

import { useEffect } from "react";

/**
 * Next.js 15 App Router: グローバルエラー境界。
 * レンダリングエラー時に英語デフォルト画面を出さず、日本語のブランド一貫した
 * リカバリ画面を提示する。`reset()` で同一ページを再試行可能。
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 本番監視を導入後、ここで Sentry 等にレポート送信する
    // 現状は console.error のみ（ブラウザ側で見える）
    console.error("[ソクウリ] レンダリングエラー", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6">
      <div className="max-w-md text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
          Error
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          ページの表示中に問題が発生しました
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">
          一時的な不具合の可能性があります。お手数ですが、もう一度お試しください。
          解決しない場合はトップへ戻ってからアクセスし直してください。
        </p>
        {error.digest && (
          <p className="mt-4 text-[11px] font-mono text-slate-400">
            ref: {error.digest}
          </p>
        )}
        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => reset()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
          >
            もう一度試す
          </button>
          <a
            href="/"
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50"
          >
            トップへ戻る
          </a>
        </div>
      </div>
    </div>
  );
}
