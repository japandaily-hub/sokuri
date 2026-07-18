"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Ic } from "./Icons";
import { KdzLogo } from "./Logo";

export type NavItem = { href: string; label: string };

const DEFAULT_NAV: NavItem[] = [
  { href: "/#flow", label: "使い方" },
  { href: "/examples", label: "成約イメージ" },
  { href: "/photo-guide", label: "撮影ガイド" },
  { href: "/faq", label: "よくある質問" },
];

const DEFAULT_MOBILE: NavItem[] = [
  { href: "/#flow", label: "使い方" },
  { href: "/#auction", label: "仕組み" },
  { href: "/#trust", label: "安心" },
  { href: "/#cats", label: "対応カテゴリ" },
  { href: "/faq", label: "よくある質問" },
  { href: "/login", label: "ログイン" },
  { href: "/mypage", label: "マイページ" },
];

/**
 * 共通サイトヘッダー（デザイン .header / .mobile-menu）。
 * - スクロールで .scrolled を付与し境界線・影を出す
 * - ハンバーガーで .menu-open をトグル（隣接 .mobile-menu が display:flex）
 * CTA は出品導線（/create）、ログインは /login に接続。
 */
export function SiteHeader({
  nav = DEFAULT_NAV,
  mobileNav = DEFAULT_MOBILE,
  ctaHref = "/create",
  ctaLabel = "LINEではじめる",
}: {
  nav?: NavItem[];
  mobileNav?: NavItem[];
  ctaHref?: string;
  ctaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      <header className={`header${scrolled ? " scrolled" : ""}${open ? " menu-open" : ""}`}>
        <div className="container inner">
          <Link href="/" className="logo" aria-label="カタヅケ トップへ">
            <KdzLogo size={23} />
          </Link>
          <nav className="nav" aria-label="メインナビゲーション">
            {nav.map((n) => (
              <Link key={n.href} href={n.href}>
                {n.label}
              </Link>
            ))}
          </nav>
          <Link
            href="/login"
            className="hidden md:inline text-[14px] font-semibold text-kdz-ink transition-colors hover:text-kdz-blue"
          >
            ログイン
          </Link>
          <Link href={ctaHref} className="btn btn-line h-cta">
            <Ic name="chat" />
            {ctaLabel}
          </Link>
          <button
            type="button"
            className="hamburger"
            aria-label="メニュー"
            aria-controls="mobile-menu"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <Ic name={open ? "x" : "menu"} />
          </button>
        </div>
      </header>

      <div className="mobile-menu" id="mobile-menu" aria-hidden={!open}>
        {mobileNav.map((n) => (
          <Link key={n.href} href={n.href} onClick={() => setOpen(false)}>
            {n.label}
          </Link>
        ))}
        <Link href={ctaHref} className="btn btn-line btn-block mm-cta" onClick={() => setOpen(false)}>
          <Ic name="chat" />
          {ctaLabel}
        </Link>
      </div>
    </>
  );
}
