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
 *  R4: 事例データ（CASES）は @/lib/model-cases の単一正本を読む。トップ（/）の「利用イメージ」
 *  節と同じ値を共有し、金額・入札数・日数がページ間で食い違わないようにする。ここに再定義しない。
 *
 *  R4 ラウンド5（指摘 2/13）で肖像の方針を改めた。R4_BRIEF B.3 は「48px の円に入れても顔が
 *  潰れる」ことを理由に見送りにしていたが、円ではなく矩形（.img-frame--1x1・PC 200px /
 *  SP 128px）で出せば潰れない。トップの「こんなふうに使えます」で顔のある3人（田中・鈴木・
 *  山口＝portrait を持つケース）が、同じ3人の詳細である本ページではイニシャルの円のままで、
 *  同一人物の見え方が分断されていたため、B.3 の判断を上書きして肖像を出す。
 *  素材は原寸 800px 角（表示 200px）なので、画像担当が 440px 角の派生（mc-*-440.webp）を
 *  書き出したら src を差し替える（BRIEF §1.11 の 2x 規約）。manifest の used_by も要追記。
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

        {/* R4 ラウンド5 指摘（2/13）: トップの「こんなふうに使えます」で顔のある3人（田中・
            鈴木・山口）が、同じ3人の詳細であるこのページではイニシャルの円のままで、同一人物の
            見え方が分断されていた。肖像を持つケースだけ矩形（.img-frame--1x1）で顔を出す。
            円形のイニシャルは氏名の隣の識別マークとして残す（正典: 円形はアバターとドットのみ）。
            肖像は生成画像・架空であることを、この上の .cases-hero-note（MODEL_CASE_NOTE）と
            alt 内の「架空のモデルケース」、下の .case-quote-note が三重に担保する。 */}
        <div className={`case-persona${c.portrait ? " case-persona--portrait" : ""}`}>
          {c.portrait ? (
            <div className="img-frame img-frame--1x1 img-frame--white case-portrait">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/img/v2/${c.portrait}.webp`}
                width={800}
                height={800}
                alt={c.portraitAlt}
                loading="lazy"
                decoding="async"
              />
            </div>
          ) : null}
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
          <div className="case-amount">
            ¥{c.amount.toLocaleString()}
            <span>円</span>
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
      {/* R4 ラウンド5 指摘（11）: eyebrow が「成約事例」だと、直下の h1「成約イメージ
          （モデルケース）」という打消し表示の直前に、実在の成約実績を示唆する語を置くことに
          なる。トップの .model-cases 節（eyebrow「利用イメージ」）と語彙を揃える。 */}
      <section className="cases-hero">
        <div className="container">
          <span className="eyebrow">利用イメージ</span>
          <h1>成約イメージ（モデルケース）</h1>
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
          <p className="cases-hero-note" role="note">
            {MODEL_CASE_NOTE}
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
