"use client";

/** 利用イメージ（カードグリッド・金額/カテゴリ）。
 *  デザイン handoff: docs/design_handoff_katazuke/成約事例.html を移植。
 *  ヘッダー/フッターは共通 SiteChrome が付与するため、ここでは <main id="main"> の中身のみ描画する。
 *  カテゴリフィルターはクライアント側の状態で切り替える（元デザインの filterCases 相当）。
 *  ビジュアル再構築 v2（BRIEF §2.3）: 帯は置かず、6件の主役画像でリズムを作る。
 *  主役画像は /img/v2/ex-lot-*.webp（1536x1024 生成 → 1600×1067 表示・.img-frame--3x2）、
 *  小2枚は既存 3D シリーズ /img/real/cat-*.webp（512x512・.img-frame--1x1）。
 *  奇数番目=画像左／偶数番目=画像右（.media-split--rev）で交互に置く。
 *
 *  R4: 事例データ（CASES）は @/lib/model-cases の単一正本を読む。トップ（/）の「利用イメージ」
 *  節と同じ値を共有し、金額・入札数・日数がページ間で食い違わないようにする。ここに再定義しない。
 *
 *  ラウンド6（指摘 2/6/10/12/16/20＝6視点が一致）で肖像を撤回し、R4_BRIEF B.3 の決定
 *  （/examples は肖像を出さず頭文字アバターを維持）に戻した。ラウンド5 で矩形の肖像を足した
 *  結果、同一人物が「矩形の肖像」と「頭文字の円」の2つの記号で並んで identity が二重化し、
 *  さらに肖像を持つのは 6件中3件のためカードの立ち上がり高さが不揃いになった。
 *  モバイルでは肖像が約 100x80px に縮んで顔が判別できず、装飾としても情報としても働いていない。
 *  肖像を残す前提（表示 220px 以上＋440px 角の派生 webp。BRIEF §1.11 の 2x 規約）も未整備。
 *  顔のある3人はトップの「こんなふうに使えます」が担い、本ページは頭文字アバターで通す。
 *  /examples の v2 画像点数は 6（6件の主役画像）に戻る。
 *
 *  【景品表示法（優良誤認）対応】掲載する事例は handoff 由来の架空データであり、実際の
 *  取引実績ではない。よって本ページでは (1)「実際の」等の実在を示す表現を使わない
 *  (2) 全カード・金額表示に「モデルケース（架空の利用イメージ）」を金額より手前で明示する
 *  (3) 計測実績風の統計値（平均入札件数等）は実データ集計が配線されるまで掲載しない。
 *  実データへの差し替え時にこの注記類を外すこと。 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { Reveal } from "@/components/kdz/interactions";
import {
  CASES,
  caseName,
  MODEL_CASE_CHIP,
  MODEL_CASE_NOTE,
  type CaseItem,
} from "@/lib/model-cases";
import "./examples.css";

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
 *  minor: 859px 以下で下段に小さく置く2項目（BRIEF §2.3 #2）。
 *
 *  R4 ラウンド5 指摘（12）: 「1社」を ¥0 と同じ級数の数字で出すと、登録業者が1社しかないと
 *  読めてしまう（/vendors は掲載0件の状態）。「12カテゴリ」も数字だけでは何の12か伝わらない。
 *  数字で出すのは金額（¥0）とエリア（4都県）の2項目に絞り、残る2項目は text（ラベル先行の
 *  文型・本文と同じ級数）にする。文言はいずれも既存のサービス条件の再掲で、新しい約束はしない。 */
const STATS: { num?: string; unit?: string; text?: string; label: string; minor?: boolean }[] = [
  { num: "¥0", label: "出品・査定・成約まで無料" },
  { text: "連絡が来るのは、選んだ1社だけ", label: "選ばなかった業者には自動でお断りが入ります" },
  { num: "4", unit: "都県", label: "東京・千葉・埼玉・神奈川", minor: true },
  { text: "家電からブランド品まで対応", label: "12のカテゴリから選んで出品できます", minor: true },
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
        {/* 打消し表示。DOM 順で必ず金額（.case-amount-box）より手前に置く（R4_BRIEF B.3）。
            クラスは共有の .model-chip（katazuke-pages.css）。ページ CSS で再定義しない。
            R4 ラウンド5 指摘（8）: チップとカテゴリタグを同じ行に並べると 2 行に折り返し、
            タグの塊に視線が取られて氏名・数値に入るのが遅れる。チップを単独行に分ける
            （.model-chip 自体は共有クラスなので上書きせず、行を分ける器を足すだけ）。 */}
        <div className="case-chip-row">
          <span className="model-chip">{MODEL_CASE_CHIP}</span>
        </div>
        <div className="case-cats">
          <span className="case-tag-chip">{c.tag}</span>
          {c.cats.map((cat) => (
            <span className="case-cat" key={cat}>
              {cat}
            </span>
          ))}
        </div>

        {/* ラウンド6 指摘（2/6/10/12/16/20）: ラウンド5 で足した矩形の肖像を撤回し、
            頭文字の円アバター 1 本に戻した（同一人物を2つの記号で示す二重表示の解消。
            6件中3件だけ肖像がありカードの立ち上がり高さも不揃いだった）。
            顔のある3人（田中・鈴木・山口）はトップの「こんなふうに使えます」が担う。
            c.portrait / c.portraitAlt はトップ専用のフィールドなのでここでは参照しない。 */}
        <div className="case-persona">
          <div className="case-avatar">{c.avatar}</div>
          <div className="case-persona-info">
            <div className="name">{caseName(c)}</div>
            <div className="attr">{c.persona}</div>
          </div>
        </div>

        <div className="case-amount-box">
          {/* R4_BRIEF E.1: 「量と流れ」を金額より先に読ませる（金額を主役にしない）。
              金額は 24px に落とし、この行より大きくならないようにしてある */}
          <div className="case-facts">
            {c.bidCount}社が入札 ／ {c.count}点まとめ ／ {c.days}日で成約
          </div>
          <div className="case-amount-label">買取額の例（架空のモデルケース）</div>
          {/* ラウンド6 指摘（7/13/18）: 1カードに ※ が3本（金額注記・セリフ注記・ページ冒頭の
              注記）あり、6件で計19本の小活字が本文より面積を占めていた。カード内の打消しは
              「チップ1つ＋金額の1行」に統合し、現物査定と引用の断り書きはカード群の手前の
              .cases-hero-note に一度だけ集約する。
              指摘 18（先頭カードが最高額 ¥148,000 で、上から読む人が最初に触れる金額が最大値に
              なる）に合わせ、この1行は金額の「手前」に置く（打消し表示を強調表示より先に読ませる。
              R4_BRIEF B.3 の「金額より手前」を .model-chip に続いて二重に満たす）。 */}
          <p className="case-note">
            ※ 架空の想定額です。買取額は品物や状況により大きく異なります。
          </p>
          <div className="case-amount">
            ¥{c.amount.toLocaleString()}
            <span>円</span>
          </div>
        </div>

        <div className="case-quote">
          <p>{c.quote}</p>
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
      {/* R4 ラウンド5 指摘（11）: eyebrow が「成約事例」だと、直下の h1 という打消し表示の
          直前に、実在の成約実績を示唆する語を置くことになる。トップの .model-cases 節
          （eyebrow「利用イメージ」）と語彙を揃える。
          ラウンド6 指摘（1/15/19＝3視点が一致）: h1 も「成約イメージ」のままで eyebrow と
          食い違っていた。「成約」は実取引の成立を示唆する語で、稼働直前の現状では最も避けたい。
          h1 と layout.tsx の metadata.title を「利用イメージ（モデルケース）」に統一する
          （ヘッダーナビ・フッターのラベルは core 所有のため差し戻し）。 */}
      <section className="cases-hero">
        <div className="container">
          <span className="eyebrow">利用イメージ</span>
          <h1>利用イメージ（モデルケース）</h1>
          <p>
            まとめて出品すると、どのように査定が集まり、成約に至るのか。サービスの流れがイメージできるモデルケースをご紹介します。
          </p>
        </div>
      </section>

      {/* ============ サービス数値バー（事実ベースのみ） ============ */}
      <div className="stats-bar">
        <div className="container">
          <div className="stats-bar-inner">
            {STATS.map((s) => (
              <div
                className={`stats-item${s.minor ? " stats-item--minor" : ""}${
                  s.text ? " stats-item--text" : ""
                }`}
                key={s.label}
              >
                {s.text ? (
                  <div className="stats-txt">{s.text}</div>
                ) : (
                  <div className="stats-num">
                    {s.num}
                    {s.unit && <span>{s.unit}</span>}
                  </div>
                )}
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
            {/* 絞り込み操作中も架空であることが視界から消えないようにする（R4_BRIEF E.1）。
                PC は件数の隣、859px 以下はチップ列（横スクロール）の外＝常に見える位置に置く */}
            <span className="filter-note">すべて架空のモデルケース</span>
          </div>

          {/* 架空事例の明示（打消し表示）。R4 ラウンド5 指摘（4/14）: h1 直下に置くと
              ページの入口が灰色の小文字の塊になり、視覚的な導入が無いまま注意書きの壁が
              立っていた。文言は一切短縮せず（折りたたみにも入れない＝打消し表示を隠さない）、
              打消しの対象＝カード群・金額の直前に移す。DOM 順は「注記 → カード（.model-chip）
              → 金額」で、金額より手前という要件（R4_BRIEF B.3）を維持する。 */}
          {/* ラウンド6 指摘（13）: カード内に散っていた断り書き（引用が架空である旨・現物査定）を
              ここに一度だけ集約する。MODEL_CASE_NOTE は共有の正本（core 所有）なので、
              このページの表示に必要な2文だけを後ろに足す。 */}
          <p className="cases-hero-note" role="note">
            {MODEL_CASE_NOTE}
            カード内のコメントも架空のもので、実際の利用者の体験談ではありません。最終的な買取額は、業者が現物を確認したうえで決まります。
          </p>

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
          {/* 押す直前の安心1行（.section-cta / /signup の既存文言の再掲。新しい約束は足さない） */}
          <p className="cases-assure">
            登録・査定・お断りまで無料　／　連絡が来るのは、あなたが選んだ1社だけ
          </p>
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
