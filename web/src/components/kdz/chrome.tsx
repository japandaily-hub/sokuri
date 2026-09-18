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
              {/* 2026-09-18 本採用: 新トップ(/lp移植)には旧 #flow が無いため、使い方に相当する
                  #daily（出品から引き取りまでのタイムライン）へ retarget */}
              <li><Link href="/#daily">使い方</Link></li>
              <li><Link href="/create">出品する</Link></li>
              <li><Link href="/photo-guide">撮影ガイド</Link></li>
              <li><Link href="/examples">利用イメージ</Link></li>
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
              <li><Link href="/legal">特定商取引法に基づく表記</Link></li>
              <li><Link href="/privacy">プライバシーポリシー</Link></li>
              <li><Link href="/terms">利用規約</Link></li>
              <li><Link href="/contact">お問い合わせ</Link></li>
            </ul>
          </div>
          {/* ラウンド5 指摘（1/2/3・3視点が同一指摘）: 業者向けの入口が「カタヅケについて」に
              紛れ、業者利用規約（/terms#biz）への導線がサイト内のどのページにも無かった
              （/terms 本文の相互リンクだけが唯一の入口）。業者の列として独立させる。 */}
          <div>
            <h5>業者の方へ</h5>
            <ul>
              <li><Link href="/business">業者登録</Link></li>
              <li><Link href="/operator/login">業者ログイン</Link></li>
              <li><Link href="/terms#biz">業者利用規約</Link></li>
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
 * ヒーロー CTA（.hero-cta）とページ内の LINE ボタン（.btn-line）のいずれかが画面内にある間は
 * 同じ CTA が上下に二枚並ぶため .dock--hidden で隠す（BRIEF §1.8／/contact で二重表示を実測）。
 * 対象が無いページでは常時表示。表示/非表示のみなので reduced-motion でも動作させる。
 * ルート遷移でリセットするため SiteChrome 側は key={pathname} で再マウントする（effect 内 setState を避ける）。
 */
export function Dock({
  // 2026-09-15 ユーザー指示: LINEログイン後の着地先を /create から /mypage へ変更
  // （page.tsx のヒーロー/中段/下部CTAと同じ理由）。
  href = "/login?callbackUrl=%2Fmypage",
  label = "LINEで無料ではじめる",
  sub = "LINEアカウントでログインできます",
}: { href?: string; label?: string; sub?: string }) {
  const [ctaInView, setCtaInView] = useState(false);
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    // .dock 自身の中の .btn-line は対象外（自分を見て自分を隠す無限往復を避ける）
    const targets = Array.from(
      document.querySelectorAll<HTMLElement>(".hero-cta, .btn-line")
    ).filter((el) => !el.closest(".dock"));
    if (targets.length === 0) return;
    const inView = new Set<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) inView.add(e.target);
          else inView.delete(e.target);
        });
        setCtaInView(inView.size > 0);
      },
      { threshold: 0 }
    );
    targets.forEach((t) => io.observe(t));
    return () => io.disconnect();
  }, []);
  return (
    <div className={`dock${ctaInView ? " dock--hidden" : ""}`}>
      <Link href={href} className="btn btn-line">
        {/* 緑タイルは意味を持たない装飾（アクセシブル名はラベル＋補足のテキストが担う） */}
        <span className="btn-line__tile" aria-hidden="true" />
        <span className="btn-line__body">
          <span className="btn-line__label">{label}</span>
          <span className="btn-line__sub">{sub}</span>
        </span>
        <Ic name="arrow" className="btn-line__arr" />
      </Link>
    </div>
  );
}
