"use client";

import Link from "next/link";
import { useState } from "react";
import { Ic } from "./Icons";
import { KdzLogo } from "./Logo";

import "./operator-header.css";

export type OperatorNavKey = "dashboard" | "cases" | "transactions" | "profile";

const NAV: { key: OperatorNavKey; href: string; label: string }[] = [
  { key: "dashboard", href: "/operator", label: "ダッシュボード" },
  { key: "cases", href: "/operator/cases", label: "案件一覧" },
  { key: "transactions", href: "/operator/transactions", label: "取引" },
  { key: "profile", href: "/operator/profile", label: "プロフィール" },
];

/**
 * 業者向けアプリ画面の共通ヘッダー。
 *
 * デザインレビュー B-1 対応: 旧 slate 実装だった案件一覧・案件詳細・落札管理・
 * 取引詳細の4画面にヘッダー（ナビゲーション手段）自体が無かった問題を解消。
 * デザインレビュー B-5 対応: ダッシュボード(.biz-header)とプロフィール(.op-header)で
 * 別々に実装されていたヘッダーを本コンポーネントへ統合（両ページもこれを使うよう移行済み）。
 * デザインレビュー B-4 対応: 通知ベルがユーザー専用 /notifications にリンクしており
 * 業者セッションでは middleware に弾かれ導線が壊れていた問題を修正。業者向けの
 * 通知専用フィードは無いため、「対応が必要な取引」がまとまる /operator/transactions
 * へリンクし直した（hasAttention は各ページが把握している範囲でのみ渡す任意プロップ）。
 */
export function OperatorHeader({
  active,
  companyName,
  hasAttention = false,
}: {
  active: OperatorNavKey;
  companyName?: string | null;
  hasAttention?: boolean;
}) {
  const [navOpen, setNavOpen] = useState(false);
  const avatarInitial = (companyName ?? "").trim().charAt(0) || "業";

  return (
    <header className="op-header">
      <div className="container op-header-inner">
        <Link href="/operator" className="op-brand" aria-label="カタヅケ 業者ダッシュボードへ">
          <KdzLogo size={20} />
          <span className="op-brand-tag">BUYER</span>
        </Link>

        <nav className={`op-nav${navOpen ? " open" : ""}`} aria-label="業者メニュー">
          {NAV.map((n) => (
            <Link
              key={n.key}
              href={n.href}
              className={n.key === active ? "active" : undefined}
              aria-current={n.key === active ? "page" : undefined}
              onClick={() => setNavOpen(false)}
            >
              {n.label}
            </Link>
          ))}
        </nav>

        <div className="op-header-right">
          <Link href="/operator/transactions" aria-label="対応が必要な取引" className="op-notif">
            <svg
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.9}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.7 21a2 2 0 01-3.4 0" />
            </svg>
            {hasAttention ? <span className="op-notif-dot" aria-hidden="true" /> : null}
          </Link>

          {companyName ? (
            <span className="op-user">
              <span className="op-user-avatar" aria-hidden="true">
                {avatarInitial}
              </span>
              <span className="op-user-name">{companyName}</span>
            </span>
          ) : null}

          <Link href="/operator/login" className="op-logout">
            ログアウト
          </Link>

          <button
            type="button"
            className="op-nav-toggle"
            aria-label="メニュー"
            aria-expanded={navOpen}
            onClick={() => setNavOpen((v) => !v)}
          >
            <Ic name="menu" />
          </button>
        </div>
      </div>
    </header>
  );
}
