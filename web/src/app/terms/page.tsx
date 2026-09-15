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

/** 冒頭の「要点」。本文（TermsTabs）の要約であり、根拠となる条を併記する。
 *  ラウンド5 指摘（12）で本文の各条に id（ユーザー側 tu-N／業者側 tb-N）を振ったため、
 *  ref を該当条へのページ内リンクにする（tb-* は TermsTabs が業者ペインを開いてから送る）。 */
const POINTS: { no: string; lead: string; body: string; ref: string; href: string }[] = [
  {
    no: "01",
    lead: "ユーザーの費用は0円です。",
    body: "出品・査定・お断りまで、ユーザーに費用の請求はありません。",
    ref: "ユーザー利用規約 第6条",
    href: "#tu-6",
  },
  {
    no: "02",
    lead: "連絡が来るのは、選んだ1社だけです。",
    body: "詳細住所と連絡用のメールアドレスは、交渉が成立した業者にのみ開示されます。氏名・電話番号を業者に開示することはありません。",
    ref: "ユーザー利用規約 第5条",
    href: "#tu-5",
  },
  {
    no: "03",
    lead: "業者を選ぶ前なら、取り下げできます。",
    body: "入札の受付は、ユーザーが業者を選んだ時点で終了します。それまでは出品を取り下げることができます。",
    ref: "ユーザー利用規約 第4条",
    href: "#tu-4",
  },
  {
    /* ラウンド5 指摘（15）: 一番不安な「来てもらった後に断れるか」が要点に無く、条文と
       /legal を読まないと分からなかった。文言はトップの料金節（page.tsx の .fz-caution）と
       /faq の既存文言と同じ範囲に留める（無条件の解約権を新たに書かない）。根拠は
       「ユーザーの同意なく一方的に減額できない」＝業者利用規約 第5条。 */
    no: "04",
    lead: "金額のご相談に納得できなければ、お断りできます。",
    body: "訪問時の現物確認で写真と状態が違えば、業者から金額のご相談が届くことがあります。同意しない場合は取引をお断りでき、お断りに費用はかかりません。",
    ref: "業者利用規約 第5条",
    href: "#tb-5",
  },
];

export default function TermsPage() {
  return (
    <main id="main">
      {/* 法務3ページ共通の無文字帯（高さ固定・文字は置かない。.tab-wrap の sticky に影響させない）。
          R6 指摘 2/12: /terms=--pos-l、/legal=--pos-r、/privacy=既定 と修飾子が3ページで
          バラバラだったため「並べると1ページだけ絵が違う＝壊れて見える」判定が続いていた。
          素材 lg-band（1920x1080）に対し帯は PC・SP とも常にそれより横長にトリミングされ、
          object-position の横成分は効かない（core の katazuke-pages.css の幾何コメント参照）＝
          --pos-* は見た目を変えないまま「ページごとに違う指定がある」という誤解だけを残す。
          3ページとも修飾子をこの1組（--fixed --quiet）に揃え、縦位置と高さは core の
          .hero-band--fixed（--band-pos:50% 53% / 186px・SP 120px）1本だけが持つ形にする。 */}
      <section className="hero-band hero-band--fixed hero-band--quiet">
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
          {/* ラウンド4 指摘（Med・業者視点）: 本ページは着地時にユーザー利用規約のペインが
              開くため、/business の同意チェックから来た業者が「同意対象の業者利用規約」に
              たどり着けたか分からなかった。冒頭に相互リンクを置く。href="#biz" は
              TermsTabs が hashchange を見て業者ペインを開き、タブ列まで送る。 */}
          <p className="legal-head__cross">
            業者の方の規約はこちら <a href="#biz">業者利用規約</a>
          </p>
        </div>
      </section>

      <section className="terms-points" aria-labelledby="terms-points-title">
        <div className="terms-points__inner">
          <h2 className="doc-section-title" id="terms-points-title">
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
                  <a className="terms-points__ref" href={p.href}>
                    {p.ref}
                  </a>
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
