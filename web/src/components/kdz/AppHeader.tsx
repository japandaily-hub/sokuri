import Link from "next/link";
import { AppHeaderBell } from "./AppHeaderBell";
import { AppHeaderLogout } from "./AppHeaderLogout";
import { KdzLogo } from "./Logo";

/**
 * ログイン後アプリ画面の共通ヘッダー（マイページ/申し込み状況/通知/プロフィール等）。
 * マーケティングヘッダー（SiteHeader）とは別物。ロゴ + 通知ベル + マイページ導線。
 * これらのルートは SiteChrome の BARE_PREFIXES 対象で共通クロムが付かないため、各ページがこれを描く。
 * 未読ドットは AppHeaderBell が自前で成約データから取得して判定するため、
 * 呼び出し側が真偽値を渡す必要はない。
 * showBell=false で通知ベルごと非表示にできる（管理画面など、依頼者向けの
 * 成約データを取得すべきでない文脈で使う）。
 */
export function AppHeader({ showBell = true }: { showBell?: boolean } = {}) {
  return (
    <header className="header scrolled" style={{ position: "sticky" }}>
      <div className="container inner">
        <Link href="/" className="logo" aria-label="カタヅケ トップへ">
          <KdzLogo size={22} />
        </Link>
        <div className="app-actions">
          {showBell ? (
            <Link
              href="/notifications"
              aria-label="通知・お知らせ"
              style={{ position: "relative", color: "var(--navy)", display: "grid", placeItems: "center", width: 40, height: 40 }}
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.7 21a2 2 0 01-3.4 0" />
              </svg>
              <AppHeaderBell />
            </Link>
          ) : null}
          <Link
            href="/mypage"
            className="text-[14px] font-semibold text-kdz-ink transition-colors hover:text-kdz-blue"
          >
            マイページ
          </Link>
          <AppHeaderLogout />
        </div>
      </div>
    </header>
  );
}
