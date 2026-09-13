import type { Metadata } from "next";
import Link from "next/link";
import "./terms.css";
import { TermsTabs } from "./TermsTabs";

export const metadata: Metadata = {
  title: "利用規約",
  description:
    "カタヅケの利用規約です。ユーザー利用規約・業者利用規約について定めています。",
  alternates: { canonical: "/terms" },
};

/** 冒頭の「要点3つ」。本文（TermsTabs）の要約であり、根拠となる条を併記する。
 *  ref は該当条の見出し文字列。TermsTabs 側に id が無いためリンクにはせず、
 *  探す手がかりとしてのみ表示する（無効なアンカーを作らない）。 */
const POINTS: { no: string; lead: string; body: string; ref: string }[] = [
  {
    no: "01",
    lead: "ユーザーの費用は0円です。",
    body: "出品・査定・お断りまで、ユーザーに費用の請求はありません。",
    ref: "ユーザー利用規約 第6条",
  },
  {
    no: "02",
    lead: "連絡が来るのは、選んだ1社だけです。",
    body: "詳細住所と連絡用のメールアドレスは、交渉が成立した業者にのみ開示されます。氏名・電話番号を業者に開示することはありません。",
    ref: "ユーザー利用規約 第5条",
  },
  {
    no: "03",
    lead: "業者を選ぶ前なら、取り下げできます。",
    body: "入札の受付は、ユーザーが業者を選んだ時点で終了します。それまでは出品を取り下げることができます。",
    ref: "ユーザー利用規約 第4条",
  },
];

export default function TermsPage() {
  return (
    <main id="main">
      {/* 法務3ページ共通の無文字帯（高さ固定・文字は置かない。.tab-wrap の sticky に影響させない） */}
      <section className="hero-band hero-band--fixed hero-band--quiet hero-band--pos-l">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/img/v2/lg-band.webp"
          width="1920"
          height="1080"
          alt=""
          loading="lazy"
          decoding="async"
        />
        <div className="hero-band__veil" aria-hidden="true" />
      </section>

      <section className="legal-head">
        <div className="legal-head__inner">
          <span className="legal-head__en">TERMS</span>
          <h1>利用規約</h1>
          <p className="legal-head__meta">
            制定・施行：2026年4月1日　最終改定：2026年9月4日
          </p>
        </div>
      </section>

      <section className="terms-points" aria-labelledby="terms-points-title">
        <div className="terms-points__inner">
          <h2 className="terms-points__title" id="terms-points-title">
            ユーザーの方へ　この規約の要点
          </h2>
          <ol className="terms-points__list">
            {POINTS.map((p) => (
              <li key={p.no}>
                <span className="terms-points__no" aria-hidden="true">
                  {p.no}
                </span>
                <span className="terms-points__body">
                  <strong>{p.lead}</strong>
                  {p.body}
                  <span className="terms-points__ref">{p.ref}</span>
                </span>
              </li>
            ))}
          </ol>
          <p className="terms-points__note">
            上記は本文の要約です。条件の詳細は以下の各条をご確認ください。取引のお取りやめ・クーリング・オフについては
            <Link href="/legal">特定商取引法に基づく表記</Link>
            もあわせてご確認ください。
          </p>
        </div>
      </section>

      <TermsTabs />
    </main>
  );
}
