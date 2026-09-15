"use client";

/**
 * 依頼者/業者向け（非admin）画面の共通通知バナー。
 * katazuke-pages.css の `.notice`/`.notice--*` に対応するReactラッパー。
 * デザイン監査(2026-09-15)是正: エラーバナーがmypage/operator配下で
 * ページごと・関数ごとに重複実装（rgba直書き・独自パレット）されていた問題への対処。
 * admin配下は別レイヤー（Tailwind）の components/kdz/Ui.tsx の Notice を使うこと。
 */

import type { ReactNode } from "react";

const ICONS: Record<NoticeTone, ReactNode> = {
  danger: (
    <svg viewBox="0 0 24 24" className="notice-ic" aria-hidden="true" style={{ stroke: "currentColor", fill: "none", strokeWidth: 2, strokeLinecap: "round" }}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4M12 16h.01" />
    </svg>
  ),
  warn: (
    <svg viewBox="0 0 24 24" className="notice-ic" aria-hidden="true" style={{ stroke: "currentColor", fill: "none", strokeWidth: 2, strokeLinecap: "round" }}>
      <path d="M12 3l9 16H3l9-16z" />
      <path d="M12 10v4M12 17h.01" />
    </svg>
  ),
  success: (
    <svg viewBox="0 0 24 24" className="notice-ic" aria-hidden="true" style={{ stroke: "currentColor", fill: "none", strokeWidth: 2, strokeLinecap: "round" }}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.5 2.5L16 9" />
    </svg>
  ),
  info: (
    <svg viewBox="0 0 24 24" className="notice-ic" aria-hidden="true" style={{ stroke: "currentColor", fill: "none", strokeWidth: 2, strokeLinecap: "round" }}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </svg>
  ),
};

export type NoticeTone = "danger" | "warn" | "success" | "info";

export function Notice({
  tone = "danger",
  role,
  children,
  className,
}: {
  tone?: NoticeTone;
  /** role="alert"（エラー等・即時通知） or role="status"（結果報告）。省略時はtoneから既定値を選ぶ。 */
  role?: "alert" | "status";
  children: ReactNode;
  className?: string;
}) {
  const resolvedRole = role ?? (tone === "danger" || tone === "warn" ? "alert" : "status");
  return (
    <div className={`notice notice--${tone}${className ? ` ${className}` : ""}`} role={resolvedRole}>
      {ICONS[tone]}
      <span>{children}</span>
    </div>
  );
}
