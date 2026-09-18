import type { CSSProperties, ReactNode } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { Reveal } from "@/components/kdz/interactions";
import { FEATURED_CASES, caseName, MODEL_CASE_CHIP, MODEL_CASE_NOTE } from "@/lib/model-cases";
import { ILLUSTRATIONS, ILL_POSITIONS, ILL_THIN_ON_MOBILE, illSrc, type IllName } from "@/lib/illustrations";
import { LpChrome } from "./_components/LpChrome";
import { LpSlider, type LpSlide } from "./_components/LpSlider";
import { LpRibbon } from "./_components/LpRibbon";
import "./lp.css";

/** 検証用の別案ルート。本採用するまで検索結果に出さない。
 *  本採用時に外すもの: この robots、`alternates.canonical`（"/lp" のまま可）、robots.ts の Disallow。 */
export const metadata: Metadata = {
  title: "カタヅケ｜家まるごと、まとめて片付け買取",
  description:
    "家じゅうの不用品を、1点ずつ撮って、あとは待つだけ。登録業者が買取総額で競い合い、連絡が来るのはあなたが選んだ1社だけ。値がつかない物もまとめて回収。営業電話に追われない、家まるごとの片付け買取マッチング。",
  robots: { index: false, follow: false },
  alternates: { canonical: "/lp" },
};

/* ============================================================
   KV スライダー（参照 `.home-kv__slider` 4枚 → カタヅケは 4枚）
   2026-09-18 ユーザー指摘: 単一人物の3場面ストーリーは主役の年齢が実際より上に見えた。
   トップページの HeroCarousel と同じ思想（誰が使うサービスかを一人の像に固定しない）で、
   「片付けたい。でも、動けない」という困っている瞬間を 4 つのペルソナで回す構成に変更。
   ============================================================ */
const KV_SLIDES: LpSlide[] = [
  { id: "kv-single-woman", src: "/img/lp/kv-single-woman.webp", alt: "使わなくなった物に囲まれて、リビングの床に座り込む30代半ばの女性（イメージ）" },
  { id: "kv-single-man", src: "/img/lp/kv-single-man.webp", alt: "使わなくなった物に囲まれて、リビングの床に座り込む30代の男性（イメージ）" },
  { id: "kv-family", src: "/img/lp/kv-family.webp", alt: "使わなくなった物に囲まれて、子どもと一緒にリビングの床に座る30代の夫婦（イメージ）" },
  { id: "kv-couple-60s", src: "/img/lp/kv-couple-60s.webp", alt: "使わなくなった物に囲まれて、リビングの床に座る60代の夫婦（イメージ）" },
];

/** 循環イラスト帯（トップ `/` と同じ並び・同じ位置定義を共有する） */
const ILL_LOOP: IllName[] = ["box", "truck", "house-tree", "folding-hands", "books", "plant"];

/** 手描き風・多色のデコアイコン（/img/lp/deco）。ILL_LOOP 用の青系イラストとは別系統の彩り装飾。
 *  2026-09-18 ユーザー指摘: FEE 上部の余白（浮遊イラストの空）がスカスカでバランスが悪い。
 *  8 点に増やし、SP でも間引かず（hideSp を使わない）全域に散らす。 */
type DecoIll = { src: string; top: string; left: string; w: number; sway: 1 | 2; float: 1 | 2 | 3; spTop?: string; spLeft?: string };
const FEE_DECO: DecoIll[] = [
  { src: "/img/lp/deco/deco-box.webp", top: "10%", left: "8%", w: 88, sway: 1, float: 1 },
  { src: "/img/lp/deco/deco-camera.webp", top: "58%", left: "6%", w: 92, sway: 2, float: 2, spTop: "48%" },
  { src: "/img/lp/deco/deco-clock.webp", top: "18%", left: "90%", w: 78, sway: 1, float: 3, spLeft: "86%" },
  { src: "/img/lp/deco/deco-teacup.webp", top: "66%", left: "88%", w: 84, sway: 2, float: 1, spLeft: "84%", spTop: "70%" },
  { src: "/img/lp/deco/deco-gift.webp", top: "40%", left: "24%", w: 68, sway: 1, float: 2 },
  { src: "/img/lp/deco/deco-tote.webp", top: "80%", left: "42%", w: 82, sway: 2, float: 3, spTop: "84%" },
  { src: "/img/lp/deco/deco-lamp.webp", top: "8%", left: "50%", w: 74, sway: 1, float: 1, spLeft: "56%" },
  { src: "/img/lp/deco/deco-plant2.webp", top: "44%", left: "74%", w: 88, sway: 2, float: 2 },
];

/* ============================================================
   区画 3 ABOUT — 3 item の交互配置（参照 `.home-about__item` ×3）
   ============================================================ */
type AboutItem = {
  en: string;
  head: ReactNode;
  body: ReactNode;
  img: { src: string; alt: string; w: number; h: number; contain?: boolean };
};
const ABOUT_ITEMS: AboutItem[] = [
  {
    en: "about katazuke 01",
    head: (
      <>
        まとめて出すほど、
        <br />
        <em>有利</em>になる。
      </>
    ),
    body: (
      <>
        カタヅケは<span className="lp-mk">家まるごと</span>
        の片付け向け。1点ずつではなく、たまった不用品をまとめて査定に出すほど、買取総額が伸びやすく、値がつかない物まで一緒に手放せます。
      </>
    ),
    img: {
      src: "/img/real/bundle-3d.webp",
      alt: "さまざまな不用品がひとつの箱にまとまり、まとめて1つの価格がつくイメージ",
      w: 1536,
      h: 864,
      contain: true,
    },
  },
  {
    en: "about katazuke 02",
    head: (
      <>
        業者が<em>買取総額</em>で競うから、
        <br />
        高くなりやすい。
      </>
    ),
    body: <>あなたが出したのは写真だけ。あとは登録業者どうしが、あなたが出品した商品に買取総額で入札し合います。</>,
    img: {
      src: "/img/real/bid-3d.webp",
      alt: "複数の業者が、まとめた不用品に買取総額を提示して競り合うイメージ",
      w: 1536,
      h: 864,
      contain: true,
    },
  },
  {
    en: "about katazuke 03",
    head: (
      <>
        業者が<em>直接</em>、
        <br />
        引き取りに来ます
      </>
    ),
    body: (
      <>
        梱包も発送も、あなたはしなくていい。選んだ業者がまとめて引き取りに来ます。やりとりするのは、交渉が成立した相手とだけです。
      </>
    ),
    img: {
      src: "/img/v2/top-handover.webp",
      alt: "玄関先で、まとめた品物を業者に引き渡す場面（イメージ）",
      w: 1536,
      h: 1024,
    },
  },
];

/* ============================================================
   区画 4 POINT — 撮 / 選 / 安（参照 `.home-point__item` の -eating / -living / -cycle）
   ============================================================ */
type PointCell = {
  n: string;
  h: string;
  p: ReactNode;
  img: { src: string; alt: string; w: number; h: number; contain?: boolean; pos?: string };
};
type PointBlock = {
  id: string;
  kanji: string;
  en: string;
  tone: "primary" | "deep" | "pale";
  title: string;
  main: PointCell;
  minors: { h: string; p: ReactNode }[];
  cells: [PointCell, PointCell];
};
const POINT_BLOCKS: PointBlock[] = [
  {
    id: "shoot",
    kanji: "撮",
    en: "- SHOOT -",
    tone: "primary",
    // legal M3: 02/03 が「選ぶ」工程なので、出典（page.tsx の #flow 見出し）どおりに戻す
    title: "あなたがするのは、「撮る」と「選ぶ」だけ",
    main: {
      n: "01",
      h: "1点ずつ撮る",
      p: <>家じゅうの不用品を1点ずつ撮影。写真と品目をまとめて登録するだけで出品完了です。</>,
      img: {
        src: "/img/v2/top-hero-woman-20s.webp",
        alt: "リビングの床で、不用品をスマートフォンで撮影する20代の女性（イメージ）",
        w: 900,
        h: 1350,
        pos: "50% 30%",
      },
    },
    minors: [
      {
        h: "仕分け・分別は不要",
        p: <>ジャンルが混ざっていてもOK。家じゅうの「どうしよう」を、思いついた物から撮ってまとめるだけ。あとは業者がまとめて査定します。</>,
      },
      {
        h: "値がつかない物も、まとめて回収",
        p: (
          <>
            業者は1点ごとではなく<strong className="lp-mk">出品した商品すべてに対する買取総額で入札</strong>
            します。だから単体では値がつきにくい物も、他の商品と一緒に引き取り。「これは売れないかも」も、一緒に手放せます。
          </>
        ),
      },
      {
        h: "梱包も発送も不要。玄関先で引き渡すだけ。",
        p: <>訪問日時は、あなたの都合で選べます。大型家具や大量の品も、まとめて相談OK。</>,
      },
    ],
    cells: [
      {
        n: "02",
        h: "査定が届く",
        p: <>買取業者があなたの出品した商品に入札。あなたは待つだけで査定が集まります。</>,
        img: { src: "/img/lp/bids-arrive.webp", alt: "食卓のスマートフォンに、届いた査定の通知が並ぶイメージ", w: 1024, h: 1024 },
      },
      {
        n: "03",
        h: "査定を見比べて選ぶ",
        p: <>届いた査定を一覧で見比べて、納得の1社を選ぶだけ。選ぶまで、業者から連絡は来ません。</>,
        img: {
          src: "/img/lp/compare-offers.webp",
          alt: "食卓でスマートフォンの査定一覧を見比べる40代の女性（イメージ）",
          w: 1024,
          h: 1536,
          pos: "50% 30%",
        },
      },
    ],
  },
  {
    id: "choose",
    kanji: "選",
    en: "- CHOOSE -",
    tone: "deep",
    title: "入札のしくみ",
    main: {
      n: "01",
      h: "連絡先を伏せて出品内容が届く",
      p: (
        <>
          業者に届くのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。あなたのお名前・電話・詳細住所は伏せたままです。
        </>
      ),
      img: {
        src: "/img/lp/buyer-views-listing.webp",
        alt: "買取店の事務所で、届いた出品内容（写真と品目）をタブレットで確認する店主（イメージ）",
        w: 1536,
        h: 1024,
      },
    },
    minors: [
      { h: "写真・品目・地域のみ", p: <>業者に届くのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。</> },
      {
        h: "氏名・電話は渡りません",
        p: <>お名前や電話番号が業者に渡ることはなく、詳細住所と連絡用のメールアドレスも交渉が成立した1社にのみ開示されます。</>,
      },
      { h: "詳細住所とメールは成立後", p: <>成立後に連絡先を開示し、引き取り日時を決めます。</> },
    ],
    cells: [
      {
        n: "02",
        h: "登録業者が買取総額で入札",
        p: <>複数の業者が、出品した商品すべてに対して買取総額を提示します。提示された総額は、すべて一覧で見比べられます。</>,
        img: {
          src: "/img/lp/buyers-bidding.webp",
          alt: "店舗・倉庫・車内で、それぞれの業者がタブレットから入札するイメージ",
          w: 1024,
          h: 1024,
        },
      },
      {
        n: "03",
        h: "連絡が来るのは選んだ1社だけ",
        p: <>選ぶまで、業者はあなたに連絡できません。選ばなかった業者には自動でお断りが入り、営業電話の一斉架電はありません。</>,
        img: {
          src: "/img/real/trust-illus-2.webp",
          alt: "連絡先が業者に開示されるのは交渉が成立した1社だけであることを示すイメージ",
          w: 1024,
          h: 768,
          contain: true,
        },
      },
    ],
  },
  {
    id: "trust",
    kanji: "安",
    en: "- TRUST -",
    tone: "pale",
    title: "はじめてでも、安心して任せられる",
    main: {
      n: "01",
      h: "登録事業者のみ",
      p: (
        <>
          査定に参加するのは登録された買取事業者だけ。古物営業に必要な古物商許可を、登録時・取引前に確認します。対応エリアは東京・千葉・埼玉・神奈川で、審査を通過した業者から順に参加します。
        </>
      ),
      img: {
        src: "/img/real/trust-illus-1.webp",
        alt: "登録事業者の古物商許可を確認するイメージ",
        w: 1024,
        h: 768,
        contain: true,
      },
    },
    minors: [
      { h: "古物商許可を確認", p: <>古物営業に必要な古物商許可を、登録時・取引前に確認します。</> },
      { h: "東京・千葉・埼玉・神奈川", p: <>順次エリア拡大中</> },
      { h: "審査を通過した業者から順に参加", p: <>査定に参加するのは登録された買取事業者だけ。</> },
    ],
    cells: [
      {
        n: "02",
        h: "連絡先は成立後に開示",
        p: (
          <>
            査定段階で業者に渡るのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。お名前や電話番号は業者に渡らず、詳細住所と連絡用のメールアドレスは交渉が成立するまで開示されません。
          </>
        ),
        img: {
          src: "/img/real/trust-illus-3.webp",
          alt: "連絡先の開示範囲を線引きしているイメージ",
          w: 1024,
          h: 768,
          contain: true,
        },
      },
      {
        n: "03",
        h: "訪問買取は特定商取引法の対象",
        p: (
          <>
            訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があります。一部の物品は法令により対象外とされています。お客様の品物が対象かどうかは、訪問した業者が交付する書面に記載されます。ご不明な場合は消費者ホットラインにご相談ください。
          </>
        ),
        img: {
          src: "/img/lp/doorstep-docs.webp",
          alt: "玄関先で、業者が依頼者に書面を手渡す場面（イメージ）",
          w: 1536,
          h: 1024,
        },
      },
    ],
  },
];

/* ============================================================
   区画 5 DAILY — 01〜09（build-brief §4-B で確定した文言・順序固定）
   size: 参照の「大小 3 段階」に対応（lg=50% / md=33% / sm=25%）。trail=足跡の破線を右下に出す。
   ============================================================ */
type DailyStep = {
  n: string;
  img: string;
  w: number;
  h: number;
  pos?: string;
  contain?: boolean;
  tag?: string;
  trail?: boolean;
  p: string;
};
const DAILY_STEPS: DailyStep[] = [
  { n: "01", img: "/img/v2/top-hero-woman-20s.webp", w: 900, h: 1350, pos: "50% 30%", tag: "撮る", trail: true, p: "家じゅうの不用品を1点ずつ撮影。" },
  { n: "02", img: "/img/lp/register-listing.webp", w: 1024, h: 1024, trail: true, p: "写真と品目をまとめて登録するだけで出品完了です。" },
  {
    n: "03",
    img: "/img/lp/buyer-views-listing.webp",
    w: 1536,
    h: 1024,
    p: "業者に届くのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。",
  },
  {
    n: "04",
    img: "/img/lp/buyers-bidding.webp",
    w: 1024,
    h: 1024,
    tag: "業者が競う",
    trail: true,
    p: "複数の業者が、出品した商品すべてに対して買取総額を提示します。",
  },
  { n: "05", img: "/img/lp/compare-offers.webp", w: 1024, h: 1536, pos: "50% 30%", tag: "見比べて選ぶ", trail: true, p: "提示された総額は、すべて一覧で見比べられます。" },
  {
    n: "06",
    img: "/img/lp/choose-one.webp",
    w: 1024,
    h: 1536,
    pos: "50% 45%",
    p: "提示を見比べて1社を選択。選ばなかった業者には自動でお断りが入ります。",
  },
  { n: "07", img: "/img/lp/schedule-visit.webp", w: 1024, h: 1024, trail: true, p: "成立後に連絡先を開示し、引き取り日時を決めます。" },
  {
    n: "08",
    img: "/img/lp/onsite-check.webp",
    w: 1536,
    h: 1024,
    trail: true,
    p: "訪問時の現物確認で写真と状態が違えば、業者から金額のご相談が届くことがあります。納得できなければお断りできます。",
  },
  { n: "09", img: "/img/v2/top-handover.webp", w: 1536, h: 1024, tag: "引き取り完了", p: "玄関先で渡すだけで、片付け完了です。" },
];

/* ============================================================
   区画 8 BIZ — カード3枚（参照 `.home-farm__card`）。
   legal M8: 出典 `.biz-banner-tags` の 4 本は並列のチップなので、見出しだけの並列カード＋注記に戻す
   （h/p に組み替えると「初期費用無料だから長く続く」のような新しい因果が生まれる）。
   ============================================================ */
const BIZ_CARDS: { h: string; img: string }[] = [
  { h: "初期費用・月額費用 無料", img: "biz-reason-bulk" },
  { h: "成約時8%（税別）のみ", img: "biz-reason-photo" },
  { h: "下見なし・一斉架電なし", img: "biz-reason-route" },
];

/** フッターのリンク（電話番号・住所は書かない） */
const FOOTER_LINKS: { href: string; label: string }[][] = [
  [
    { href: "/#flow", label: "使い方" },
    { href: "/faq", label: "よくある質問" },
    { href: "/photo-guide", label: "撮影ガイド" },
    { href: "/company", label: "会社概要" },
    { href: "/contact", label: "お問い合わせ" },
  ],
  [
    { href: "/legal", label: "特定商取引法に基づく表記" },
    { href: "/privacy", label: "プライバシーポリシー" },
    { href: "/terms", label: "利用規約" },
    { href: "/business", label: "業者登録" },
    { href: "/operator/login", label: "業者ログイン" },
  ],
];

/** 浮遊デコアイコン1点（外側が translate、内側の img が rotate。2つの transform を別要素に分ける） */
function FloatDeco({ ill }: { ill: DecoIll }) {
  return (
    <span
      className={`lp-ill lp-ill--f${ill.float}`}
      style={
        {
          "--lp-ill-top": ill.top,
          "--lp-ill-left": ill.left,
          "--lp-ill-sp-top": ill.spTop ?? ill.top,
          "--lp-ill-sp-left": ill.spLeft ?? ill.left,
          "--lp-ill-w": `${ill.w}px`,
        } as CSSProperties
      }
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className={`lp-ill__img lp-ill__img--s${ill.sway}`} src={ill.src} alt="" width={512} height={512} loading="lazy" decoding="async" />
    </span>
  );
}

export default function LpPage() {
  return (
    /* r1 A-5: <footer> を <main> の外へ出して contentinfo ランドマークを取り戻す。
       lp.css のスコープは根の .lp-page が引き続き担う。 */
    <div className="lp-page">
      <LpChrome />

      <main id="main">
        {/* ============ 1. KV（参照 .home-kv・フルブリード写真スライダー） ============
            r2 A-3: 写真を KV 全面に敷き、キャッチは写真の上。可読性は上部だけの淡色グラデ veil で作る
            （文字色は --ink / 主色のまま）。DOM 順 = 写真 → veil → 浮遊装飾 → キャッチ → 下端の白波形。 */}
        <section id="top" className="lp-kv">
          <LpSlider slides={KV_SLIDES} />
          <div className="lp-kv__veil" aria-hidden="true" />
          {/* ユーザー指摘（2026-09-18）: 箱・本・トラック・セーターのイラストに続き、
              ドットのひし形クラスタも被写体に重なって見づらいため撤去。写真のみのシンプルな構成にする。 */}
          <div className="lp-container lp-kv__inner">
            <div className="lp-kv__catch">
              <h1>
                片付けたい。でも、
                <br />
                <span className="hl">動けない</span>あなたへ。
              </h1>
              <p className="lp-kv__sub">
                家じゅうの不用品を、
                <strong>
                  1点ずつ撮って、
                  <br className="sp-br" />
                  あとは待つだけ
                </strong>
                。
              </p>
            </div>
          </div>
          <div className="lp-wave lp-wave--bottom lp-wave--white" aria-hidden="true" />
        </section>

        {/* ============ 2. MESSAGE（参照 .home-message） ============ */}
        {/* qa r2 L-7: 英字キャプションを region 名にすると読み上げが「message from katazuke」だけになるため和文で与える */}
        <section className="lp-message" aria-label="運営事務局からのメッセージ">
          {/* 2026-09-18 ユーザー指摘: ページ全体に手描き風アイコンを散りばめて彩りを出す（FEE で
              生成した素材を再利用・追加コストなし）。上下の余白（padding）の中に収め、写真・文章には重ねない。 */}
          {/* スクロール連動の 3 曲線（水・新緑・星）。写真の後ろ・右下へ抜ける */}
          <LpRibbon variant="a" className="lp-ribbon--message" />
          <div className="lp-message__deco" aria-hidden="true">
            <FloatDeco ill={{ src: "/img/lp/deco/deco-clock.webp", top: "4%", left: "84%", w: 64, sway: 2, float: 3 }} />
            <FloatDeco ill={{ src: "/img/lp/deco/deco-teacup.webp", top: "94%", left: "8%", w: 70, sway: 1, float: 1, spLeft: "78%" }} />
          </div>
          <div className="lp-container lp-message__inner">
            <div className="lp-message__figs">
              {/* 2026-09-18 ユーザー指摘: 60代夫婦の写真がKVの新ペルソナ構成と重複して見えるため、
                  年代を特定しない一般的な情景写真（手元・部屋の一角）に差し替え */}
              <figure className="lp-message__fig lp-message__fig--a img-frame img-frame--1x1">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/lp/message-hands.webp" alt="" width={1024} height={1024} loading="lazy" decoding="async" />
              </figure>
              <figure className="lp-message__fig lp-message__fig--b img-frame img-frame--4x5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/img/lp/message-corner.webp"
                  alt=""
                  width={1024}
                  height={1536}
                  loading="lazy"
                  decoding="async"
                />
              </figure>
            </div>
            <Reveal className="lp-message__txt" variant="up">
              <p className="lp-en lp-message__en">message from katazuke</p>
              <p>
                片付けが進まないのは、やる気の問題ではありません。出品の手間、営業電話の不安、何から手をつけるかの迷い。その一つひとつが、最初の一歩を重くしています。
              </p>
              <p>
                カタヅケは、それを「撮って待つだけ」に変えるために生まれました。業者が競い、値がつかない物まで引き取り、連絡は選んだ1社だけ。あなたが背負うものを、できる限り減らします。
              </p>
              <p>
                カタヅケが目指すのは、顧客と業者を結ぶ、無駄のない場所です。<strong>顧客・業者・社会の三者に喜びと安心を</strong>
                。それが、カタヅケの根にある考え方です。
              </p>
              {/* legal L10: 署名は出典（.founder-sign）と同じ 2 段構造で全文を出す */}
              <p className="lp-message__sign">
                <span>カタヅケ 運営事務局</span>顧客にも業者にも、社会にも。三方よしの場所をつくります。
              </p>
            </Reveal>
          </div>
          {/* 参照は丘のような二重波形。白を 2 枚、位相と不透明度をずらして重ねる（r1 C-2） */}
          <div className="lp-wave lp-wave--bottom lp-wave--white lp-wave--back" aria-hidden="true" />
          <div className="lp-wave lp-wave--bottom lp-wave--white" aria-hidden="true" />
        </section>

        {/* ============ 3. ABOUT（参照 .home-about・主色帯＋波形上端＋テクスチャ） ============ */}
        <section id="about" className="lp-band lp-about">
          <div className="lp-wave lp-wave--top lp-wave--white" aria-hidden="true" />
          <div className="lp-texture" aria-hidden="true" />
          <LpRibbon variant="b" className="lp-ribbon--about" stars={false} />
          <div className="lp-container lp-about__inner">
            <Reveal className="lp-band__head" variant="up">
              <p className="lp-en">about katazuke</p>
              <h2>カタヅケは、まとめ売りの買取マッチングです。</h2>
            </Reveal>
            {ABOUT_ITEMS.map((it, i) => (
              <Reveal as="article" className="lp-about__item" variant="up" key={it.en} stagger={i}>
                <div className={`lp-about__fig img-frame img-frame--3x2${it.img.contain ? " img-frame--contain" : ""}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={it.img.src} alt={it.img.alt} width={it.img.w} height={it.img.h} loading="lazy" decoding="async" />
                </div>
                <div className="lp-about__body">
                  <p className="lp-en">{it.en}</p>
                  <h3>{it.head}</h3>
                  <p className="lp-about__p">{it.body}</p>
                </div>
                <span className="lp-trail" aria-hidden="true" />
              </Reveal>
            ))}
            {/* legal H2/M4: 「値がつかない物も回収」に対応する出典の打消しを併記し、強調と同じ本文サイズで置く */}
            <p className="lp-about__note">※ 最終的な買取額は業者の現物査定により決まります。</p>
            <p className="lp-about__note">
              ※ 引き取りの可否・条件は品物や業者により異なります。一部、引き取りが難しい物は手放す導線をご案内します。
            </p>
          </div>
          {/* 波形は「次の面の色」で塗る（次は淡色地の POINT） */}
          <div className="lp-wave lp-wave--bottom lp-wave--pale" aria-hidden="true" />
        </section>

        {/* ============ 4. POINT（参照 .home-point・撮/選/安 の3ブロック＋循環図） ============ */}
        <div id="point" className="lp-point">
          {POINT_BLOCKS.map((b) => (
            <section className={`lp-point__block lp-point__block--${b.tone}`} key={b.id} aria-labelledby={`lp-point-${b.id}`}>
              <div className="lp-point__plate" aria-hidden="true" />
              <div className="lp-container lp-point__inner">
                {/* r2 B-1: 見出しは色面の「中」（バッジの右・縦中央）。色面の下に置くと 670px の無地が残るため */}
                <Reveal className="lp-point__head" variant="up">
                  <span className="lp-point__badge">
                    <span className="lp-point__badge-ja" aria-hidden="true">
                      {b.kanji}
                    </span>
                    <span className="lp-en lp-point__badge-en" aria-hidden="true">
                      {b.en}
                    </span>
                  </span>
                  <h2 id={`lp-point-${b.id}`}>{b.title}</h2>
                </Reveal>


                <Reveal className="lp-point__main" variant="up">
                  <div className="lp-point__main-copy">
                    <h3>
                      {b.main.h}
                      <span className="lp-num" aria-hidden="true">
                        {b.main.n}
                      </span>
                    </h3>
                    <p>{b.main.p}</p>
                  </div>
                  <div
                    className={`lp-point__main-fig img-frame img-frame--3x2${b.main.img.contain ? " img-frame--contain" : ""}`}
                    style={b.main.img.pos ? ({ "--pos": b.main.img.pos } as CSSProperties) : undefined}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={b.main.img.src}
                      alt={b.main.img.alt}
                      width={b.main.img.w}
                      height={b.main.img.h}
                      loading="lazy"
                      decoding="async"
                    />
                  </div>
                </Reveal>

                <div className="lp-point__minors">
                  {b.minors.map((m, i) => (
                    <Reveal as="article" className="lp-minor" variant="up" stagger={i} key={m.h}>
                      <h4>{m.h}</h4>
                      <p>{m.p}</p>
                    </Reveal>
                  ))}
                </div>

                <div className="lp-point__cells">
                  {b.cells.map((c, i) => (
                    <Reveal as="article" className="lp-cell" variant="up" stagger={i} key={c.n}>
                      <div
                        className={`lp-cell__fig img-frame img-frame--3x2${c.img.contain ? " img-frame--contain" : ""}`}
                        style={c.img.pos ? ({ "--pos": c.img.pos } as CSSProperties) : undefined}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={c.img.src} alt={c.img.alt} width={c.img.w} height={c.img.h} loading="lazy" decoding="async" />
                      </div>
                      <h3>
                        {c.h}
                        <span className="lp-num" aria-hidden="true">
                          {c.n}
                        </span>
                      </h3>
                      <p>{c.p}</p>
                    </Reveal>
                  ))}
                </div>
              </div>
            </section>
          ))}

          {/* 参照 -cycle と同じ「主色の色帯」。見出しは出典（運営者メッセージの strong）に揃える（r1 B-2） */}
          <section className="lp-cycle" aria-labelledby="lp-cycle-h">
            <div className="lp-wave lp-wave--top lp-wave--pale" aria-hidden="true" />
            <div className="lp-texture" aria-hidden="true" />
            <div className="lp-container lp-cycle__inner">
              <Reveal className="lp-band__head" variant="up">
                <p className="lp-en">three-way satisfaction</p>
                <h2 id="lp-cycle-h">顧客・業者・社会の三者に喜びと安心を。</h2>
              </Reveal>
            </div>
            <div className="ill-loop" aria-hidden="true">
              <div className="lp-container">
                <div className="ill-loop-inner ill-scope">
                  {ILL_LOOP.map((name, i) => {
                    const meta = ILLUSTRATIONS[name];
                    const pos = ILL_POSITIONS[name];
                    return (
                      <Reveal
                        key={name}
                        className={`ill-item ill-item--${name}`}
                        stagger={i}
                        style={{ "--ill-top": pos.top, "--ill-left": pos.left } as CSSProperties}
                        data-ill-thin={ILL_THIN_ON_MOBILE.includes(name) ? "" : undefined}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={illSrc(name)} alt={meta.alt} width={meta.w} height={meta.h} loading="lazy" decoding="async" />
                      </Reveal>
                    );
                  })}
                </div>
              </div>
            </div>
          </section>
        </div>

        {/* ============ 5. DAILY（参照 .home-daily・主色帯の 01〜09 タイムライン） ============ */}
        <section id="daily" className="lp-band lp-daily">
          {/* 循環帯と同じ主色が続くため、区切りは淡色の波形リボンで作る */}
          <div className="lp-wave lp-wave--top lp-wave--pale" aria-hidden="true" />
          <div className="lp-texture" aria-hidden="true" />
          <LpRibbon variant="b" className="lp-ribbon--daily" stars={false} />
          <div className="lp-container lp-daily__inner">
            <Reveal className="lp-band__head" variant="up">
              <p className="lp-en">from listing to pickup</p>
              <h2>カタヅケの、出品から引き取りまで。</h2>
            </Reveal>
            <ol className="lp-daily__list">
              {DAILY_STEPS.map((s) => (
                <Reveal as="li" className="lp-daily__item" variant="up" key={s.n}>
                  <div
                    className={`lp-daily__fig img-frame img-frame--1x1${s.contain ? " img-frame--contain" : ""}`}
                    style={s.pos ? ({ "--pos": s.pos } as CSSProperties) : undefined}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={s.img} alt="" width={s.w} height={s.h} loading="lazy" decoding="async" />
                    <span className="lp-daily__n" aria-hidden="true">
                      {s.n}
                    </span>
                    {s.tag ? <span className="lp-daily__tag">{s.tag}</span> : null}
                  </div>
                  <p className="lp-daily__cap">{s.p}</p>
                  {s.trail ? <span className="lp-trail lp-trail--daily" aria-hidden="true" /> : null}
                </Reveal>
              ))}
            </ol>
          </div>
          <div className="lp-wave lp-wave--bottom lp-wave--white" aria-hidden="true" />
        </section>

        {/* ============ 6. FEE（参照 .home-kome・巨大パネル＋CTA2本） ============ */}
        <section id="fee" className="lp-fee">
          <div className="lp-fee__sky" aria-hidden="true">
            <LpRibbon variant="a" className="lp-ribbon--fee" />
            {FEE_DECO.map((ill) => (
              <FloatDeco key={ill.src} ill={ill} />
            ))}
          </div>
          <div className="lp-container">
            <Reveal className="lp-fee__panel" variant="up">
              <span className="eyebrow">料金について</span>
              <h2>費用は、一切かかりません</h2>
              <p className="lp-en">price / free of charge</p>
              <p className="lp-fee__lead">出品・査定・成約まで、すべて無料です。</p>

              <div className="lp-fee__zero">
                <span className="lp-fee__label">お客様のお支払い</span>
                <strong className="lp-fee__num">¥0</strong>
                <span className="lp-fee__note">出品・査定・お断り・引き取りまで、費用は一切かかりません。</span>
                {/* 打消し表示は ¥0 と同一視野・本文サイズで置く（最小級の※にしない） */}
                <span className="lp-fee__caution">
                  訪問時の現物確認で写真と状態が違えば、業者から金額のご相談が届くことがあります。納得できなければお断りできます（お断りにも費用はかかりません）。
                </span>
              </div>

              <div className="lp-fee__fig img-frame img-frame--3x2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/lp/fee-empty-room.webp" alt="" width={1536} height={1024} loading="lazy" decoding="async" />
              </div>

              <span className="lp-marks" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>

              <div className="lp-fee__cta">
                <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line btn-lg">
                  <span className="btn-line__tile" aria-hidden="true" />
                  <span className="btn-line__body">
                    <span className="btn-line__label">LINEではじめる（無料）</span>
                    <span className="btn-line__sub">LINEアカウントでログインできます</span>
                  </span>
                  <Ic name="arrow" className="btn-line__arr" />
                </Link>
                <Link href="/examples" className="btn btn-ghost btn-lg">
                  6件のモデルケース（買取額の例を含む）を見る
                  <Ic name="arrow" />
                </Link>
              </div>
            </Reveal>
          </div>
          <div className="lp-wave lp-wave--bottom lp-wave--primary" aria-hidden="true" />
        </section>

        {/* ============ 7. CASES（参照 .home-coco・水色 intro/outro ＋ 3件の縦積みカード） ============ */}
        <section id="cases" className="lp-cases">
          <div className="lp-cases__intro">
            <div className="lp-wave lp-wave--top lp-wave--primary" aria-hidden="true" />
            <div className="lp-container">
              {/* r2 B-2: 中身は増やさない（見出し＋その下の極小英字だけ） */}
              <Reveal className="lp-cases__introbody" variant="up">
                <h2>こんなふうに使えます</h2>
                <p className="lp-en">usage images</p>
              </Reveal>
            </div>
          </div>

          <div className="lp-cases__main">
            <div className="lp-container">
              <Reveal className="lp-cases__head" variant="up">
                {/* qa r2 L-6: 2 行目が intro 帯の h2 と同文だったため、同一視野の反復を解消する */}
                <p className="lp-cases__catch">
                  家まるごとの片付けを、
                  <br />
                  <span>撮るところから。</span>
                </p>
                <p className="lp-cases__sub">サービスの流れをイメージしていただくための、架空のモデルケースです。</p>
              </Reveal>
              {/* 景表法: 打消し表示はカード群より手前（省略不可） */}
              <p className="model-note" role="note">
                {MODEL_CASE_NOTE}
              </p>
              <div className="lp-cases__list">
                {FEATURED_CASES.map((c, i) => (
                  <Reveal as="article" className="lp-case" variant="up" stagger={i} key={c.id}>
                    {/* 打消し表示はカードの先頭（肖像・数値より DOM 順で手前） */}
                    <span className="model-chip lp-case__chip">{MODEL_CASE_CHIP}</span>
                    <div className="lp-case__fig img-frame img-frame--1x1">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={`/img/v2/${c.portrait}.webp`}
                        alt={c.portraitAlt}
                        width={800}
                        height={800}
                        loading="lazy"
                        decoding="async"
                      />
                    </div>
                    <div className="lp-case__body">
                      <h3>{caseName(c)}</h3>
                      <p className="lp-case__attr">
                        {c.persona}／{c.tag}
                      </p>
                      <p className="lp-case__quote">「{c.quoteShort}」</p>
                      <dl className="lp-case__facts">
                        <div>
                          <dt>まとめて出品</dt>
                          <dd>
                            <b>{c.count}</b>
                            <span>点</span>
                          </dd>
                        </div>
                        <div>
                          <dt>入札</dt>
                          <dd>
                            <b>{c.bidCount}</b>
                            <span>社</span>
                          </dd>
                        </div>
                        <div>
                          <dt>成約まで</dt>
                          <dd>
                            <b>{c.days}</b>
                            <span>日</span>
                          </dd>
                        </div>
                      </dl>
                    </div>
                    <Link href="/examples" className="btn btn-ghost lp-case__more">
                      詳しく見る
                      <Ic name="arrow" />
                    </Link>
                  </Reveal>
                ))}
              </div>
            </div>
          </div>

          <div className="lp-cases__outro">
            <div className="lp-wave lp-wave--top lp-wave--white" aria-hidden="true" />
            <div className="lp-container">
              <Reveal className="lp-cases__area" variant="up">
                <p>対応エリア: 東京都・千葉県・埼玉県・神奈川県（順次拡大）</p>
                <Link href="/company" className="lp-textlink">
                  会社概要を見る
                  <Ic name="arrow" />
                </Link>
              </Reveal>
            </div>
          </div>
        </section>

        {/* ============ 8. BIZ（参照 .home-farm・淡色帯＋全幅写真＋カード3枚） ============ */}
        <section id="biz" className="lp-biz">
          <div className="lp-wave lp-wave--top lp-wave--sky" aria-hidden="true" />
          <div className="lp-texture" aria-hidden="true" />
          <div className="lp-container lp-biz__inner">
            <Reveal className="lp-biz__band img-frame img-frame--3x2" variant="up">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/img/v2/biz-band-sorting.webp" alt="" width={1920} height={1088} loading="lazy" decoding="async" />
            </Reveal>
            <div className="lp-biz__lead">
              <Reveal className="lp-biz__copy" variant="up">
                <p className="lp-en">for buyers</p>
                <h2>
                  買取業者の方へ。
                  <br />
                  カタヅケに<em>参加</em>しませんか。
                </h2>
              </Reveal>
              {/* qa r2 L-8: β 手数料の 1 文はカード群直前の .lp-biz__note が担うため、
                  リードは出典 `.biz-banner-copy p`（<br /> 区切り 3 文）のうち前 2 文だけにする */}
              <Reveal className="lp-biz__text" variant="up">
                <p>顧客と業者、双方に無駄がない。だから長く続く。</p>
                <p>一括出品への入札で、効率的な仕入れルートを開拓できます。</p>
              </Reveal>
            </div>
            {/* legal M5: 期間限定の条件はカード群の直前・本文サイズで置く */}
            <p className="lp-biz__note">β期間中は手数料0円（期間限定・請求開始は事前にお知らせします）</p>
            <div className="lp-biz__cards">
              {BIZ_CARDS.map((c, i) => (
                <Reveal as="article" className="lp-biz__card" variant="up" stagger={i} key={c.img}>
                  <div className="lp-biz__card-fig img-frame img-frame--1x1">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/img/v2/${c.img}.webp`} alt="" width={800} height={800} loading="lazy" decoding="async" />
                  </div>
                  <h3>{c.h}</h3>
                </Reveal>
              ))}
            </div>
            <p className="lp-biz__req">古物商許可が必要</p>
            <div className="lp-biz__cta">
              <Link href="/business" className="btn btn-primary btn-lg">
                業者登録の詳細を見る
                <Ic name="arrow" />
              </Link>
              <span className="lp-biz__chip">審査制・登録無料</span>
            </div>
          </div>
        </section>
      </main>

      {/* ============ 9. FOOTER（参照 l-footer・主色の波形上端＋淡色地＋右端の pagetop） ============ */}
      <footer className="lp-footer">
        <div className="lp-wave lp-wave--top lp-wave--primary" aria-hidden="true" />
        <div className="lp-container lp-footer__inner">
          <div className="lp-footer__brand">
            <KdzLogo size={24} />
            <p>東京都・千葉県・埼玉県・神奈川県（順次拡大）</p>
          </div>
          <nav className="lp-footer__nav" aria-label="フッターナビゲーション">
            {FOOTER_LINKS.map((col, i) => (
              <ul key={i}>
                {col.map((l) => (
                  <li key={l.href}>
                    <Link href={l.href}>
                      <span className="lp-menu__mark" aria-hidden="true">
                        <Ic name="arrow" />
                      </span>
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            ))}
          </nav>
        </div>
        {/* r1 A-1: 参照どおり footer 内の absolute ブロック（画面に追従させない） */}
        <a href="#top" className="lp-pagetop" aria-label="ページの先頭へ">
          <Ic name="up" />
          <span>PAGE TOP</span>
        </a>
        <p className="lp-footer__copy">© 2026 カタヅケ</p>
      </footer>
    </div>
  );
}
