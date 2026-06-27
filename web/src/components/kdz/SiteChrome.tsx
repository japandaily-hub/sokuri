"use client";

import { usePathname } from "next/navigation";
import { SiteHeader } from "./SiteHeader";
import { SiteFooter, Dock } from "./chrome";

/**
 * ルートに応じて共通ヘッダー/フッターを出し分ける。
 * 認証・フロー系（独自の最小ヘッダーを持つ画面）では共通クロムを抑止し、
 * 各ページが自前のヘッダーを描く。コンテンツ系は自動で共通クロムを得る。
 */
const BARE_PREFIXES = [
  "/login",
  "/signup",
  "/operator",
  "/create",
  "/password-reset",
  "/verify-email",
];

export function SiteChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const bare = BARE_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (bare) return <>{children}</>;

  return (
    <>
      <SiteHeader />
      {children}
      <SiteFooter />
      <Dock />
    </>
  );
}
