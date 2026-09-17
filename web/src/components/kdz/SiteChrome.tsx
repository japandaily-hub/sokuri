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
  // ログイン後のアプリ画面（独自のアプリヘッダー=ロゴ+通知ベル等をページ側で描く）
  "/mypage",
  "/applications",
  "/notifications",
  "/business",
  "/vendors",
  "/chat",
  "/schedule",
  "/review",
  "/result",
  // デザインレビュー H-1 対応: /cases も他のログイン後アプリ画面と同様に
  // 独自 AppHeader を描くため、マーケ用 SiteHeader/Dock/フッターを抑止する。
  "/cases",
  // デザインレビュー C-1 対応: /admin も内部ツール画面としてマーケ用
  // SiteHeader/Dock/フッター（LINEではじめる CTA）を抑止する。
  "/admin",
  // /lp は独自クロム（ヘッダー・全画面メニュー・浮遊CTA・pagetop・フッター）を自前で描く
  "/lp",
];

/**
 * 法務文書ページ。ヘッダー（CTA を含む）とフッターは共通のまま描くが、
 * 追従する営業 CTA（Dock）は描かない。規約・ポリシーを確認しに来た読者に
 * マーケティング CTA が追従するのは印象が悪く、本文も 74px せり上がるため
 * （R4 ラウンド4 指摘 10）。下余白は katazuke.css の body:not(:has(.dock)) が外す。
 */
const DOCKLESS_PREFIXES = ["/terms", "/privacy", "/legal"];

export { BARE_PREFIXES, DOCKLESS_PREFIXES };

export function SiteChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const bare = BARE_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const dockless = DOCKLESS_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (bare) return <>{children}</>;

  // 額装フレーム（.site-frame）はヘッダーの外側に描く。
  // ランディング(/)だけは page.tsx 側が額を複数枚に割って描くため、ここでは包まない。
  const framed = pathname !== "/";

  return (
    <>
      <SiteHeader />
      {framed ? <div className="site-frame">{children}</div> : children}
      <SiteFooter />
      {/* key でルート毎に再マウントし、.hero-cta 監視の表示状態を必ずリセットする */}
      {dockless ? null : <Dock key={pathname} />}
    </>
  );
}
