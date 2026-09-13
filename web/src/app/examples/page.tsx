"use client";

/** 成約イメージ（カードグリッド・金額/カテゴリ）。
 *  デザイン handoff: docs/design_handoff_katazuke/成約事例.html を移植。
 *  ヘッダー/フッターは共通 SiteChrome が付与するため、ここでは <main id="main"> の中身のみ描画する。
 *  カテゴリフィルターはクライアント側の状態で切り替える（元デザインの filterCases 相当）。
 *  ビジュアル再構築 v2（BRIEF §2.3）: 帯は置かず、6件の主役画像でリズムを作る。
 *  主役画像は /img/v2/ex-lot-*.webp（1536x1024 生成 → 1600×1067 表示・.img-frame--3x2）、
 *  小2枚は既存 3D シリーズ /img/real/cat-*.webp（512x512・.img-frame--1x1）。
 *  奇数番目=画像左／偶数番目=画像右（.media-split--rev）で交互に置く。
 *
 *  【景品表示法（優良誤認）対応】掲載する事例は handoff 由来の架空データであり、実際の
 *  取引実績ではない。よって本ページでは (1)「実際の」等の実在を示す表現を使わない
 *  (2) 全カード・金額表示に「モデルケース／イメージ」を明示する (3) 計測実績風の統計値
 *  （平均入札件数等）は実データ集計が配線されるまで掲載しない。実データへの差し替え時に
 *  この注記類を外すこと。 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { Reveal } from "@/components/kdz/interactions";
import "./examples.css";

type CaseItem = {
  id: number;
  tag: string;
  persona: string;
  avatar: string;
  name: string;
  amount: number;
  bidCount: number;
  days: number;
  cats: string[];
  count: number;
  quote: string;
  /** 主役画像の id（/img/v2/<lot>.webp・1536x1024 → 1600×1067）。 */
  lot: string;
  /** 主役画像の alt（images.json の値をそのまま使う）。 */
  lotAlt: string;
  /** 主役画像に添える小2枚（既存 3D シリーズ /img/real/cat-*.webp）。 */
  thumbs: [string, string];
};

const CASES: CaseItem[] = [
  {
    id: 1,
    tag: "実家整理",
    persona: "60代・女性（東京都練馬区）",
    avatar: "田",
    name: "田中さん",
    amount: 148000,
    bidCount: 11,
    days: 2,
    cats: ["家電・PC", "家具", "ブランド品", "時計", "カメラ"],
    count: 32,
    quote:
      "実家の片付けで途方に暮れていましたが、まとめて撮影するだけで業者さんが競ってくれるとは。引越し業者への追加依頼もなく、スタッフ2名で丁寧に運んでくれました。",
    lot: "ex-lot-jikka",
    lotAlt: "実家整理のモデルケース。まとめて出す品物を和室に並べたイメージ",
    thumbs: ["cat-kaden", "cat-watch"],
  },
  {
    id: 2,
    tag: "引越し",
    persona: "30代・男性（東京都渋谷区）",
    avatar: "鈴",
    name: "鈴木さん",
    amount: 72000,
    bidCount: 7,
    days: 3,
    cats: ["家電・PC", "カメラ", "ブランド品"],
    count: 14,
    quote:
      "引越し前に使わない家電やカメラをまとめて出品。1点ずつ売る手間がなく、1回の撮影で引き取りまで終わりました。",
    lot: "ex-lot-moving",
    lotAlt: "引越しのモデルケース。新居に持っていかない家具と箱をまとめたイメージ",
    thumbs: ["cat-camera", "cat-brand"],
  },
  {
    id: 3,
    tag: "断捨離",
    persona: "40代・女性（神奈川県横浜市）",
    avatar: "佐",
    name: "佐藤さん",
    amount: 58000,
    bidCount: 6,
    days: 2,
    cats: ["ブランド品", "時計", "衣類・靴"],
    count: 11,
    quote:
      "ブランド品を10点ほど。1点ずつフリマアプリに出すのが億劫で試してみたら、撮影から引き取りまで1回で片付きました。何より、選ぶまで業者から連絡が来ないのが助かりました。",
    lot: "ex-lot-closet",
    lotAlt: "断捨離のモデルケース。衣類や小物をまとめたイメージ",
    thumbs: ["cat-brand", "cat-fashion"],
  },
  {
    id: 4,
    tag: "遺品整理",
    persona: "50代・男性（千葉県船橋市）",
    avatar: "山",
    name: "山口さん",
    amount: 95000,
    bidCount: 8,
    days: 2,
    cats: ["家電・PC", "家具", "音楽", "ゲーム"],
    count: 24,
    quote:
      "父の遺品整理で大量の品物がありました。一括で見てもらえるのでとても楽でした。業者の方も丁寧に対応してくれ、感謝しています。",
    lot: "ex-lot-ihin",
    lotAlt: "遺品整理のモデルケース。品物を種類ごとに分けて並べたイメージ",
    thumbs: ["cat-music", "cat-game"],
  },
  {
    id: 5,
    tag: "模様替え",
    persona: "20代・女性（東京都世田谷区）",
    avatar: "中",
    name: "中村さん",
    amount: 31000,
    bidCount: 4,
    days: 3,
    cats: ["家具", "衣類・靴", "本・メディア"],
    count: 9,
    quote:
      "模様替えで不要になった家具と洋服。重い家具も玄関まで出してもらえて、部屋がすっきりしました。4社の査定を見比べて、一番コメントが丁寧な業者さんに決めました。",
    lot: "ex-lot-rearrange",
    lotAlt: "模様替えのモデルケース。入れ替える家具をリビングにまとめたイメージ",
    thumbs: ["cat-furniture", "cat-fashion"],
  },
  {
    id: 6,
    tag: "引越し",
    persona: "30代・夫婦（埼玉県さいたま市）",
    avatar: "小",
    name: "小林さん夫婦",
    amount: 112000,
    bidCount: 9,
    days: 1,
    cats: ["家電・PC", "家具", "スポーツ", "ゲーム"],
    count: 19,
    quote:
      "2LDKの引越しで家電・家具をまるごと出品。引越し当日に合わせて引き取り日を調整してもらえ、タイミングもぴったりでした。",
    lot: "ex-lot-kitchen",
    lotAlt: "引越しのモデルケース。台所用品と小型家電をまとめたイメージ",
    thumbs: ["cat-sport", "cat-game"],
  },
];

/** フィルターチップ（label=表示, tag=照合する事例タグ。"all" は全件）。 */
const FILTERS: { label: string; tag: string }[] = [
  { label: "すべて", tag: "all" },
  { label: "引越し", tag: "引越し" },
  { label: "実家整理", tag: "実家整理" },
  { label: "断捨離", tag: "断捨離" },
  { label: "遺品整理", tag: "遺品整理" },
  { label: "模様替え", tag: "模様替え" },
];

/** 数値バー。事実ベースのサービス条件のみを載せる（計測実績風の数値は実データ集計が
 *  配線されるまで掲載しない。トップ/業者ページの表記と整合を保つこと）。
 *  minor: 859px 以下で下段に小さく置く2項目（BRIEF §2.3 #2）。 */
const STATS: { num: string; unit?: string; label: string; minor?: boolean }[] = [
  { num: "¥0", label: "出品・査定・成約まで無料" },
  { num: "1", unit: "社", label: "連絡が来るのは、選んだ相手だけ" },
  { num: "4", unit: "都県", label: "東京・千葉・埼玉・神奈川", minor: true },
  { num: "12", unit: "カテゴリ", label: "家電からブランド品まで", minor: true },
];

/** 1件のケース。index が偶数=画像左／奇数=画像右（.media-split--rev）。 */
function CaseCard({ c, index }: { c: CaseItem; index: number }) {
  return (
    <Reveal
      as="article"
      className={`case-card media-split${index % 2 === 1 ? " media-split--rev" : ""}`}
    >
      <div className="case-media">
        {/* data-label: 画像が未着・失敗のとき枠中央に品目名を出す（共有 .img-frame[data-label]::before）。
            画像が届けば img が上に乗って隠れる */}
        <div className="img-frame img-frame--3x2 sp-bleed" data-label={c.tag}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`/img/v2/${c.lot}.webp`}
            width={1600}
            height={1067}
            alt={c.lotAlt}
            loading="lazy"
            decoding="async"
          />
        </div>
        <div className="case-thumbs">
          {c.thumbs.map((slug) => (
            <div className="img-frame img-frame--1x1 img-frame--pale" key={slug}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/img/real/${slug}.webp`}
                width={512}
                height={512}
                alt=""
                loading="lazy"
                decoding="async"
              />
            </div>
          ))}
        </div>
      </div>

      <div className="case-body">
        {/* 画像と引用の間に「モデルケース」チップを挟む（架空であることを金額の手前で明示） */}
        <div className="case-cats">
          <span className="case-model-chip">モデルケース</span>
          <span className="case-tag-chip">{c.tag}</span>
          {c.cats.map((cat) => (
            <span className="case-cat" key={cat}>
              {cat}
            </span>
          ))}
        </div>

        <div className="case-persona">
          <div className="case-avatar">{c.avatar}</div>
          <div className="case-persona-info">
            <div className="name">{c.name}</div>
            <div className="attr">{c.persona}</div>
          </div>
        </div>

        <div className="case-amount-box">
          <div className="case-amount-label">成約買取額（イメージ）</div>
          <div className="case-amount">
            ¥{c.amount.toLocaleString()}
            <span>円</span>
          </div>
          {/* 金額と同じ重さで「量と流れ」を読ませる（BRIEF §2.3 #4） */}
          <div className="case-facts">
            {c.bidCount}社が入札 ／ {c.count}点まとめ ／ {c.days}日で成約
          </div>
          <p className="case-amount-note">
            ※ 架空のモデルケースの想定額です。買取額は品物や状況により異なり、最終的な金額は業者の現物査定で決まります。
          </p>
        </div>

        <div className="case-quote">
          <p>{c.quote}</p>
          <span className="case-quote-note">※ 人物・セリフを含め、架空の利用イメージです</span>
        </div>
      </div>
    </Reveal>
  );
}

export default function ExamplesPage() {
  const [activeFilter, setActiveFilter] = useState("all");

  const filtered = useMemo(
    () => (activeFilter === "all" ? CASES : CASES.filter((c) => c.tag === activeFilter)),
    [activeFilter]
  );

  return (
    <main id="main">
      {/* ============ ヒーロー ============ */}
      <section className="cases-hero">
        <div className="container">
          <span className="eyebrow">成約事例</span>
          <h1>成約イメージ（モデルケース）</h1>
          <p>
            まとめて出品すると、どのように査定が集まり、成約に至るのか。サービスの流れがイメージできるモデルケースをご紹介します。
          </p>
        </div>
      </section>

      {/* 架空事例の明示（打消し表示）。帯には乗せず、ヒーロー直下の白面に置く。 */}
      <div className="cases-disclosure">
        <div className="container">
          <p className="cases-hero-note" role="note">
            ※ 掲載している事例・人物・金額・入札数はいずれも、利用の流れを説明するための架空のモデルケースです。実際の取引実績ではなく、買取額等の成果を保証するものではありません。
          </p>
        </div>
      </div>

      {/* ============ サービス数値バー（事実ベースのみ） ============ */}
      <div className="stats-bar">
        <div className="container">
          <div className="stats-bar-inner">
            {STATS.map((s) => (
              <div className={`stats-item${s.minor ? " stats-item--minor" : ""}`} key={s.label}>
                <div className="stats-num">
                  {s.num}
                  {s.unit && <span>{s.unit}</span>}
                </div>
                <div className="stats-lbl">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="section">
        <div className="container">
          {/* ============ フィルター ============ */}
          <div className="filter-bar">
            <div className="filter-inner">
              {FILTERS.map((f) => (
                <button
                  key={f.tag}
                  type="button"
                  className={`filter-chip${activeFilter === f.tag ? " active" : ""}`}
                  onClick={() => setActiveFilter(f.tag)}
                >
                  {f.label}
                </button>
              ))}
              <span className="filter-count">{filtered.length}件</span>
            </div>
          </div>

          {/* ============ 事例グリッド ============ */}
          <div className="cases-grid">
            {filtered.length === 0 ? (
              <div className="cases-empty">該当する事例が見つかりませんでした。</div>
            ) : (
              filtered.map((c, i) => <CaseCard key={c.id} c={c} index={i} />)
            )}
          </div>

          <p className="cases-note" role="note">
            ※ 上記はサービスの利用イメージ（モデルケース）であり、実際の取引実績ではありません。買取額・入札数・成約までの日数は品物や状況により異なります。最終的な買取額は業者の現物査定により決まります。
          </p>

          {/* ============ CTA ============ */}
          <Reveal className="cases-cta">
            <div className="cases-cta-inner">
              <h2>あなたの家の不用品、いくらになる？</h2>
              <p>
                1点ずつ撮って、業者に競ってもらうだけ。
                <br />
                出品・査定・お断りまで、ユーザーの費用は一切無料です。
              </p>
              <div className="cases-cta-actions">
                <Link href="/create" className="btn btn-primary btn-lg">
                  無料で出品してみる
                  <Ic name="arrow" />
                </Link>
                <Link href="/photo-guide" className="btn btn-ghost btn-lg">
                  撮影ガイドを見る
                </Link>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </main>
  );
}
