"use client";

import { useEffect } from "react";
import "./not-found.css";

/**
 * Next.js 15 App Router: グローバルエラー境界。
 *
 * デザインレビュー A-1 対応: 旧 slate 意匠を廃し、404（not-found.css の .nf-*）と
 * 同じブランド意匠のカードに統一する。共通クロム（SiteHeader/SiteFooter/Dock）の
 * 外側で描画されるため、404 同様カード中身のみを .nf-main/.nf-card で構成する。
 * `reset()` で同一ページを再試行可能な点は変更していない。
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
    console.error("[カタヅケ] レンダリングエラー", error);
  }, [error]);

  return (
    <main className="nf-main">
      <div className="nf-card">
        <div className="nf-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="44" height="44" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7.5v5M12 16h.01" />
          </svg>
        </div>
        <h1 className="nf-title">ページの表示中に問題が発生しました</h1>
        <p className="nf-sub">
          一時的な不具合の可能性があります。お手数ですが、もう一度お試しください。
          <br />
          解決しない場合はトップへ戻ってからアクセスし直してください。
        </p>
        {error.digest ? (
          <p style={{ fontSize: 11, fontFamily: "ui-monospace,Menlo,Consolas,monospace", color: "var(--body-soft)", marginBottom: 20 }}>
            ref: {error.digest}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
          <button type="button" onClick={() => reset()} className="btn btn-primary">
            もう一度試す
          </button>
          <a href="/" className="btn btn-ghost">
            トップへ戻る
          </a>
        </div>
      </div>
    </main>
  );
}
