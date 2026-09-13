"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Ic } from "./Icons";
import { KdzLogo } from "./Logo";

/** 共通フッター（デザイン .footer / 4カラム）。リンクは本番ルートへ接続。 */
export function SiteFooter() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer-grid">
          <div>
            {/* フッターは白地のため反転しない（ワードマークはそのままの緑＋墨） */}
            <Link href="/" className="logo footer-logo" aria-label="カタヅケ">
              <KdzLogo size={22} />
            </Link>
            <p className="about">
              家まるごと、まとめて片付け買取。業者が買取総額で競い合う、営業電話に追われない不用品買取マッチング。東京・千葉・埼玉・神奈川対応。
            </p>
          </div>
          <div>
            <h5>サービス</h5>
            <ul>
              <li><Link href="/#flow">使い方</Link></li>
              <li><Link href="/create">出品する</Link></li>
              <li><Link href="/photo-guide">撮影ガイド</Link></li>
              <li><Link href="/examples">成約イメージ</Link></li>
            </ul>
          </div>
          <div>
            <h5>安心・サポート</h5>
            <ul>
              <li><Link href="/#trust">安心の取り組み</Link></li>
              <li><Link href="/#fee">料金</Link></li>
              <li><Link href="/faq">よくある質問</Link></li>
            </ul>
          </div>
          <div>
            <h5>カタヅケについて</h5>
            <ul>
              <li><Link href="/#founder">運営者メッセージ</Link></li>
              <li><Link href="/company">会社概要</Link></li>
              <li><Link href="/business">業者登録</Link></li>
              <li><Link href="/legal">特定商取引法に基づく表記</Link></li>
              <li><Link href="/privacy">プライバシーポリシー</Link></li>
              <li><Link href="/terms">利用規約</Link></li>
              <li><Link href="/contact">お問い合わせ</Link></li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© 2026 カタヅケ</span>
          <span>東京都・千葉県・埼玉県・神奈川県（順次拡大）</span>
        </div>
      </div>
    </footer>
  );
}

/**
 * モバイル追従CTA（デザイン .dock）。860px 以下で表示。
 * ヒーロー CTA（.hero-cta）が画面内にある間は同じ導線が二重に見えるため .dock--hidden で隠す（BRIEF §1.8）。
 * 対象が無いページでは常時表示。表示/非表示のみなので reduced-motion でも動作させる。
 * ルート遷移でリセットするため SiteChrome 側は key={pathname} で再マウントする（effect 内 setState を避ける）。
 */
export function Dock({ href = "/login?callbackUrl=%2Fcreate", label = "LINEで無料ではじめる" }: { href?: string; label?: string }) {
  const [heroCtaInView, setHeroCtaInView] = useState(false);
  useEffect(() => {
    const target = document.querySelector(".hero-cta");
    if (!target || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(
      (entries) => setHeroCtaInView(entries[entries.length - 1].isIntersecting),
      { threshold: 0 }
    );
    io.observe(target);
    return () => io.disconnect();
  }, []);
  return (
    <div className={`dock${heroCtaInView ? " dock--hidden" : ""}`}>
      <Link href={href} className="btn btn-line">
        <Ic name="chat" />
        {label}
      </Link>
    </div>
  );
}
