"use client";

/** 成約事例（カードグリッド・金額/カテゴリ）。
 *  デザイン handoff: docs/design_handoff_katazuke/成約事例.html を忠実移植。
 *  ヘッダー/フッターは共通 SiteChrome が付与するため、ここでは <main id="main"> の中身のみ描画する。
 *  カテゴリフィルターはクライアント側の状態で切り替える（元デザインの filterCases 相当）。
 *  事例写真（img/cat-*.png）は実アセット未投入のため PhImg のプレースホルダで表示する。 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { Reveal, PhImg } from "@/components/kdz/interactions";
import "./examples.css";

type CaseItem = {
  id: number;
  featured: boolean;
  tag: string;
  persona: string;
  avatar: string;
  name: string;
  amount: number;
  bidCount: number;
  days: number;
  area: string;
  cats: string[];
  count: number;
  quote: string;
  photos: string[];
};

/** 写真スラッグ → プレースホルダ用アイコン（実画像未投入時の見栄え担保）。 */
const PHOTO_ICON: Record<string, IcName> = {
  "cat-kaden": "sun",
  "cat-furniture": "sofa",
  "cat-brand": "bag",
  "cat-watch": "clock",
  "cat-camera": "camera",
  "cat-fashion": "tag",
  "cat-music": "spark",
  "cat-game": "box",
  "cat-book": "crop",
  "cat-sport": "trend",
  "cat-other": "box",
};

const photoIcon = (slug: string): IcName => PHOTO_ICON[slug] ?? "box";

const CASES: CaseItem[] = [
  {
    id: 1,
    featured: true,
    tag: "実家整理",
    persona: "60代・女性（東京都練馬区）",
    avatar: "田",
    name: "田中さん",
    amount: 148000,
    bidCount: 11,
    days: 2,
    area: "東京都練馬区",
    cats: ["家電・PC", "家具", "ブランド品", "時計", "カメラ"],
    count: 32,
    quote:
      "実家の片付けで途方に暮れていましたが、まとめて撮影するだけで業者さんが競ってくれるとは。引越し業者への追加依頼もなく、スタッフ2名で丁寧に運んでくれました。",
    photos: ["cat-kaden", "cat-furniture", "cat-brand", "cat-watch", "cat-camera", "cat-other"],
  },
  {
    id: 2,
    featured: false,
    tag: "引越し",
    persona: "30代・男性（東京都渋谷区）",
    avatar: "鈴",
    name: "鈴木さん",
    amount: 72000,
    bidCount: 7,
    days: 3,
    area: "東京都渋谷区",
    cats: ["家電・PC", "カメラ", "ブランド品"],
    count: 14,
    quote:
      "引越し前に使わない家電やカメラをまとめて出品。個別に売るより楽で、思ったより高い金額がついてびっくりしました。",
    photos: ["cat-kaden", "cat-camera", "cat-brand", "cat-other"],
  },
  {
    id: 3,
    featured: false,
    tag: "断捨離",
    persona: "40代・女性（神奈川県横浜市）",
    avatar: "佐",
    name: "佐藤さん",
    amount: 58000,
    bidCount: 6,
    days: 2,
    area: "神奈川県横浜市",
    cats: ["ブランド品", "時計", "衣類・靴"],
    count: 11,
    quote:
      "ブランド品を10点ほど。1点ずつメルカリに出すのが億劫で試してみたら、まとめての評価で思いがけない金額に。何より連絡が上位3社だけなのが助かりました。",
    photos: ["cat-brand", "cat-watch", "cat-fashion", "cat-other"],
  },
  {
    id: 4,
    featured: false,
    tag: "遺品整理",
    persona: "50代・男性（千葉県船橋市）",
    avatar: "山",
    name: "山口さん",
    amount: 95000,
    bidCount: 8,
    days: 2,
    area: "千葉県船橋市",
    cats: ["家電・PC", "家具", "音楽", "ゲーム"],
    count: 24,
    quote:
      "父の遺品整理で大量の品物がありました。一括で見てもらえるのでとても楽でした。業者の方も丁寧に対応してくれ、感謝しています。",
    photos: ["cat-kaden", "cat-furniture", "cat-music", "cat-game"],
  },
  {
    id: 5,
    featured: false,
    tag: "模様替え",
    persona: "20代・女性（東京都世田谷区）",
    avatar: "中",
    name: "中村さん",
    amount: 31000,
    bidCount: 4,
    days: 3,
    area: "東京都世田谷区",
    cats: ["家具", "衣類・靴", "本・メディア"],
    count: 9,
    quote:
      "模様替えで不要になった家具と洋服。重い家具も玄関まで出してもらえて、部屋がすっきりしました。3社から連絡が来て、一番丁寧な業者さんに決めました。",
    photos: ["cat-furniture", "cat-fashion", "cat-book", "cat-other"],
  },
  {
    id: 6,
    featured: false,
    tag: "引越し",
    persona: "30代・夫婦（埼玉県さいたま市）",
    avatar: "小",
    name: "小林さん夫婦",
    amount: 112000,
    bidCount: 9,
    days: 1,
    area: "埼玉県さいたま市",
    cats: ["家電・PC", "家具", "スポーツ", "ゲーム"],
    count: 19,
    quote:
      "2LDKの引越しで家電・家具をまるごと出品。引越し当日に合わせて引き取り日を調整してもらえ、タイミングもぴったりでした。",
    photos: ["cat-kaden", "cat-furniture", "cat-sport", "cat-game"],
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

const STATS: { num: string; unit: string; label: string }[] = [
  { num: "¥68,000", unit: "〜", label: "最高入札額（直近30日）" },
  { num: "7.4", unit: "件", label: "平均入札件数" },
  { num: "78", unit: "%", label: "入札があった割合" },
  { num: "2.1", unit: "日", label: "平均成約までの日数" },
];

function CasePhoto({ slug }: { slug: string }) {
  return (
    <div className="case-photo">
      <PhImg
        src={`/img/${slug}.png`}
        alt=""
        label={`${slug}.png`}
        icon={photoIcon(slug)}
        imgStyle={{ width: "100%", height: "100%", objectFit: "contain" }}
      />
    </div>
  );
}

function FeaturedCase({ c }: { c: CaseItem }) {
  return (
    <Reveal className="featured-case">
      <div className="featured-badge">
        <Ic name="spark" />
        注目の成約事例
      </div>
      <div className="featured-inner">
        <div className="featured-photos">
          {c.photos.slice(0, 6).map((p, i) => (
            <CasePhoto key={`${p}-${i}`} slug={p} />
          ))}
        </div>
        <div className="featured-body">
          <div>
            <span className="featured-tag">{c.tag}</span>
          </div>
          <div className="case-persona featured-persona">
            <div className="case-avatar">{c.avatar}</div>
            <div className="case-persona-info">
              <div className="name">{c.name}</div>
              <div className="attr">{c.persona}</div>
            </div>
          </div>
          <div>
            <div className="featured-amount-label">成約買取額</div>
            <div className="featured-amount">
              ¥{c.amount.toLocaleString()}
              <span>円</span>
            </div>
            <div className="featured-stat">
              {c.bidCount}社が入札 / {c.count}点まとめ / {c.days}日で成約
            </div>
          </div>
          <div className="featured-cats">
            {c.cats.map((cat) => (
              <span className="case-cat" key={cat}>
                {cat}
              </span>
            ))}
          </div>
          <div className="case-quote">
            <p>{c.quote}</p>
          </div>
        </div>
      </div>
    </Reveal>
  );
}

function CaseCard({ c }: { c: CaseItem }) {
  return (
    <Reveal as="article" className="case-card">
      <div className="case-photos">
        {c.photos.slice(0, 4).map((p, i) => (
          <CasePhoto key={`${p}-${i}`} slug={p} />
        ))}
      </div>
      <div className="case-body">
        <div className="case-header">
          <div className="case-persona">
            <div className="case-avatar">{c.avatar}</div>
            <div className="case-persona-info">
              <div className="name">{c.name}</div>
              <div className="attr">{c.persona}</div>
            </div>
          </div>
          <div className="case-amount-box">
            <div className="case-amount-label">成約買取額</div>
            <div className="case-amount">
              ¥{c.amount.toLocaleString()}
              <span>円</span>
            </div>
            <div className="case-bid-info">{c.bidCount}社入札</div>
          </div>
        </div>
        <div className="case-cats">
          <span className="case-tag-chip">{c.tag}</span>
          {c.cats.map((cat) => (
            <span className="case-cat" key={cat}>
              {cat}
            </span>
          ))}
        </div>
        <div className="case-quote">
          <p>{c.quote}</p>
        </div>
        <div className="case-meta">
          <span>
            <Ic name="box" />
            {c.count}点
          </span>
          <span>
            <Ic name="pin" />
            {c.area}
          </span>
          <span>
            <Ic name="clock" />
            {c.days}日で成約
          </span>
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
          <span className="eyebrow">CASES</span>
          <h1>実際の成約事例</h1>
          <p>
            まとめて出品することで、どのくらいの金額になるのか。実際にカタヅケを利用したユーザーの事例をご紹介します。
          </p>
        </div>
      </section>

      {/* ============ 実績バー ============ */}
      <div className="stats-bar">
        <div className="container">
          <div className="stats-bar-inner">
            {STATS.map((s) => (
              <div className="stats-item" key={s.label}>
                <div className="stats-num">
                  {s.num}
                  <span>{s.unit}</span>
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
              filtered.map((c) =>
                c.featured && activeFilter === "all" ? (
                  <FeaturedCase key={c.id} c={c} />
                ) : (
                  <CaseCard key={c.id} c={c} />
                )
              )
            )}
          </div>

          {/* ============ CTA ============ */}
          <Reveal className="cases-cta">
            <div className="cases-cta-inner">
              <h2>あなたの家の不用品、いくらになる？</h2>
              <p>
                まとめて撮って、業者に競ってもらうだけ。
                <br />
                出品・査定・お断りまで、ユーザーの費用は一切無料です。
              </p>
              <div className="cases-cta-actions">
                <Link href="/create" className="btn btn-white btn-lg">
                  無料で出品してみる
                  <Ic name="arrow" className="arw" />
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
