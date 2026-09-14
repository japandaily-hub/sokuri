/* eslint-disable @next/next/no-img-element */
import type { Metadata } from "next";
import Link from "next/link";
import "./photo-guide.css";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { Reveal } from "@/components/kdz/interactions";

export const metadata: Metadata = {
  title: "撮影ガイド",
  description:
    "カタヅケの撮影ガイド。上手に撮ると、業者が品物を判断しやすくなります。",
  alternates: { canonical: "/photo-guide" },
};

/** ヒーロー帯の直下に置くチェック行 */
const MERITS = [
  "1点ずつ撮って、まとめて1件に",
  "スマホで十分",
  "最大150枚まで追加できる",
  "写真が多いほど業者が状態を把握しやすい",
];

/** 撮影の上限（事実ベースの数値のみ） */
const LIMITS = ["写真は1点につき12枚まで", "1案件あたり150枚まで"];

/** 撮影の手順（6ステップ） */
const STEPS: { h: string; p: string; tip: string }[] = [
  {
    h: "明るい場所に品物を移動する",
    p: "窓際や電気をつけた部屋など、できるだけ明るい場所を選びます。暗い写真は業者が状態を判断しにくくなります。",
    tip: "フラッシュより自然光のほうがきれいに映ります",
  },
  {
    h: "1点ずつ、全体が映るように撮る",
    p: "商品は1点ずつ撮影します。まず品物全体が映る「引きの写真」を1枚撮りましょう。撮った写真は自動的に1つのアルバムにまとまり、業者はそれを見て量と状態を把握します。",
    tip: "段ボールや袋の中のものは出して、1点ずつ撮ると、業者が状態を把握しやすくなります",
  },
  {
    h: "正面だけでなく全方位から撮る",
    p: "正面・背面・側面・底面・内側など、できる限りいろいろな角度から撮りましょう。全方位の写真があるほど状態が正確に伝わります。",
    tip: "家具・家電は裏側や底面も忘れずに",
  },
  {
    h: "価値がありそうなものは近づいて撮る",
    p: "ブランド品・家電・時計・カメラなど、値がつきそうなものはアップで撮影します。メーカーロゴ・型番シール・製造タグが読めると、業者が品物を特定しやすくなります。",
    tip: "ブランドバッグはロゴ・内側・金具も撮るとベスト",
  },
  {
    h: "傷・汚れ・色あせ・凹みは隠さず撮る",
    p: "傷・汚れ・色あせ・色落ち・凹みなど、気になる部分は隠さずアップで撮りましょう。正直に伝えることで、現場での金額変更リスクが下がります。",
    tip: "傷があっても買取できることが多いので安心してください",
  },
  {
    h: "品目名を出品画面に入力する",
    p: "写真に加えて品目名を入力すると業者が検索して品物を特定しやすくなります。「ブランド名+品目」が理想です。",
    tip: "例：「SONY α7III」「シャネル チェーンバッグ」「ダイソン V12」",
  },
];

/** ポイントのうち、写真で見せる3点（zig-zag の .media-split） */
const TIP_SPLITS: { img: string; h: string; p: string }[] = [
  {
    img: "pg-tip-light",
    h: "明るく撮る",
    p: "照明を増やす、窓の近くで撮るなど明るさを確保。暗い写真は色や傷が見えにくく、業者が状態を判断しにくくなります。",
  },
  {
    img: "pg-tip-bg",
    h: "背景をすっきりさせる",
    p: "無地の床や壁の前に品物を1点だけ置き、まわりのものはいったんどけます。背景が整うほど、形も色もそのまま伝わります。",
  },
  {
    img: "pg-tip-detail",
    h: "全体と詳細の両方を撮る",
    p: "1点ごとに、全体が映る引きの写真＋気になる部分のアップ写真。この組み合わせが、いちばん伝わりやすくなります。",
  },
];

/** 残りの撮影ポイント（ヘアラインリスト。アイコンは Icons.tsx の近似） */
const POINTS: { icon: IcName; h: string; p: string }[] = [
  { icon: "tag", h: "ブランドロゴ・型番シール・タグは接写で", p: "メーカーロゴや型番シール、製造タグがくっきり読めるアップ写真があると、業者が品物を特定して相場を調べやすくなります。" },
  { icon: "box", h: "付属品も一緒に撮る", p: "箱・リモコン・充電器・説明書など付属品があれば一緒に撮影。付属品の有無まで業者に伝わります。" },
  { icon: "check-circle", h: "動作状態を伝える", p: "電源が入る家電は電源ON状態の写真を。動作が確認できると、業者が状態を判断しやすくなります。" },
  { icon: "up", h: "枚数は多いほどいい", p: "商品1点につき最大12枚、案件全体で最大150枚まで追加できます。写真が多いほど、業者が現物を見ずに状態を確認しやすくなります。" },
];

/** カテゴリ別チェックリスト（行頭に既存 3D アイコン /img/real/cat-*.webp） */
const CATS: { img: string; name: string; items: string[] }[] = [
  { img: "cat-brand", name: "ブランド品", items: ["ロゴ・刻印が見える写真", "バッグは内側・金具も撮影", "付属品（保存袋・箱）も", "傷・汚れ・色あせは正直に"] },
  { img: "cat-kaden", name: "家電・PC", items: ["型番・メーカーが見える写真", "電源ON状態の写真があると◎", "リモコン・充電器も一緒に", "製造年がわかれば伝える"] },
  { img: "cat-watch", name: "時計", items: ["文字盤・ケースバック・竜頭", "ブランドロゴが読めるアップ", "箱・保証書・コマ数も撮影", "傷・色あせの状態を正直に"] },
  { img: "cat-camera", name: "カメラ", items: ["ボディ・レンズを別々に撮影", "センサーの状態（埃・カビ確認）", "付属レンズ・フラッシュも", "動作確認済みなら必ず伝える"] },
  { img: "cat-furniture", name: "家具", items: ["正面・側面・背面・底面を撮影", "傷・へこみ・色あせは接写で", "サイズが分かる写真があると◎", "解体できる場合は伝える"] },
  { img: "cat-game", name: "ゲーム", items: ["本体・コントローラーを一緒に", "ソフトはタイトルが読める写真", "付属品・箱があれば一緒に", "動作確認済みは必ず伝える"] },
];

/** スクロール演出の遅延（3列グリッド用） */
const delayOf = (i: number) => ((i % 3 || undefined) as 1 | 2 | undefined);

/** 2桁の通し番号（var(--en-display) で表示する） */
const numOf = (i: number) => String(i + 1).padStart(2, "0");

export default function PhotoGuidePage() {
  return (
    <main id="main">
      {/* ============ ヒーロー（写真帯・LCP） ============ */}
      <section className="hero-band hero-band--tall hero-band--face pg-hero">
        <img
          src="/img/v2/pg-hero.webp"
          width={1920}
          height={1080}
          alt="明るい部屋で、床に置いた品物をスマートフォンで撮影する女性（イメージ）"
          loading="eager"
          fetchPriority="high"
          decoding="async"
        />
        <div className="hero-band__veil" aria-hidden="true" />
        <div className="container hero-band__copy">
          <span className="eyebrow">撮影ガイド</span>
          <h1>
            撮るほど、
            <br />
            伝わる。
          </h1>
          <p>
            カタヅケでは写真と品目情報が業者の入札根拠になります。上手に撮ると、業者が品物を判断しやすくなります。
          </p>
        </div>
      </section>

      {/* ============ ヒーローの CTA（帯の外・直下の白面） ============
          R4 ブリーフ A.4「LINE CTA を写真帯／濃紺帯の上に置かない」に合わせ、CTA 行を帯の外へ出す。
          .deep-band（katazuke-pages.css §1.3「ボタンは置かず直下の白面へ」）と同じ扱いに統一し、
          ベイル済みの帯の上で主色ブルーの面が地と同系になる／緑タイルが暗い面に浮く問題を解消する。
          .hero-cta は Dock の IntersectionObserver の監視対象なのでクラスは残す（Dock 挙動は不変）。
          区切りの罫は直下 .merit-bar の border-top が持つため、この面には引かない。 */}
      <div className="pg-hero-actions">
        <div className="container">
          <div className="hero-cta pg-hero-cta">
            {/* LINE CTA は 7 箇所共通の 2 トーン構造（主色ブルーの面＋左端に LINE 緑のタイル）。
                タイルは aria-hidden の純装飾で、アクセシブル名はラベル＋補足の文字が担う。 */}
            <Link href="/login?callbackUrl=%2Fcreate" className="btn btn-line btn-lg">
              <span className="btn-line__tile" aria-hidden="true" />
              <span className="btn-line__body">
                <span className="btn-line__label">LINEではじめる（無料）</span>
                <span className="btn-line__sub">LINEアカウントでログインできます</span>
              </span>
              <Ic name="arrow" className="btn-line__arr" />
            </Link>
            <a href="#basics" className="btn btn-ghost btn-lg">
              読んでから決める ↓
            </a>
          </div>
        </div>
      </div>

      {/* ============ 帯の直下：4チェック行（白地・ヘアライン） ============ */}
      <div className="merit-bar">
        <div className="container">
          <div className="merit-bar-inner">
            {MERITS.map((m) => (
              <div className="merit-chip" key={m}>
                <Ic name="check" />
                {m}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="section">
        <div className="container">
          {/* ============ 1. 一品ずつ撮る（良い例・避けたい例） ============ */}
          <div className="guide-section" id="basics">
            <div className="guide-section-head">
              <div className="guide-section-num">1</div>
              <div>
                <h2>一品ずつ、全体が映るように撮る</h2>
                <p>
                  品物は1点ずつ撮影します。1枚の写真に1つの品物だけを、全体が映るように収めましょう。撮った写真はまとめて1つのアルバムになり、業者はそれを見て買取総額を決めます。
                </p>
              </div>
            </div>

            <div className="compare-grid">
              <figure className="compare-card">
                <div className="img-frame img-frame--1x1 sp-bleed">
                  <img
                    src="/img/v2/pg-good.webp"
                    width={800}
                    height={800}
                    alt="明るい部屋で、ソファ1点の全体が枠に収まっている"
                    loading="lazy"
                    decoding="async"
                  />
                </div>
                <figcaption className="compare-label">
                  <span className="compare-label-badge is-good">
                    <span aria-hidden="true">○</span>良い例
                  </span>
                  <p>1枚に1品。品物全体が映り、明るい場所で背景がすっきりしている。</p>
                </figcaption>
              </figure>

              <figure className="compare-card">
                <div className="img-frame img-frame--1x1 sp-bleed">
                  <img
                    src="/img/v2/pg-bad.webp"
                    width={800}
                    height={800}
                    alt="暗い部屋で、洗濯物や箱が重なり、ソファが右端で見切れている"
                    loading="lazy"
                    decoding="async"
                  />
                </div>
                <figcaption className="compare-label">
                  <span className="compare-label-badge is-bad">
                    <span aria-hidden="true">△</span>避けたい例
                  </span>
                  <p>複数の品物を1枚に詰め込み、暗くて重なっていて何があるか分からない。</p>
                </figcaption>
              </figure>
            </div>

            <p className="pg-note">※ 買取額は業者の現物査定で決まります</p>
          </div>

          {/* ============ 2. 撮影の手順 ============ */}
          <div className="guide-section" id="steps">
            <div className="guide-section-head">
              <div className="guide-section-num">2</div>
              <div>
                <h2>撮影の手順</h2>
                <p>5分あれば十分です。この順番で撮ると業者が品物を把握しやすくなります。</p>
              </div>
            </div>

            <div className="limit-chips">
              {LIMITS.map((l) => (
                <span className="limit-chip" key={l}>
                  {l}
                </span>
              ))}
            </div>

            <ol className="shoot-steps">
              {STEPS.map((s, i) => (
                <Reveal as="li" className="shoot-step" key={s.h}>
                  <span className="shoot-step-num" aria-hidden="true">
                    {numOf(i)}
                  </span>
                  <div className="shoot-step-body">
                    <h4>{s.h}</h4>
                    <p>{s.p}</p>
                    <span className="tip">
                      <Ic name="spark" />
                      {s.tip}
                    </span>
                  </div>
                </Reveal>
              ))}
            </ol>

            <p className="pg-note">
              写真に住所・氏名・他の人が写り込まないよう、書類や画面は伏せて撮ってください。
            </p>
          </div>

          {/* ============ 3. 伝わりやすくなる撮影のポイント ============ */}
          <div className="guide-section" id="tips">
            <div className="guide-section-head">
              <div className="guide-section-num">3</div>
              <div>
                <h2>伝わりやすくなる撮影のポイント</h2>
                <p>少し意識するだけで、伝わり方が変わります。</p>
              </div>
            </div>

            <div className="tip-splits">
              {TIP_SPLITS.map((t, i) => (
                <Reveal
                  as="div"
                  className={i % 2 === 1 ? "media-split media-split--rev tip-split" : "media-split tip-split"}
                  key={t.h}
                >
                  <div className="img-frame img-frame--1x1 sp-bleed">
                    <img
                      src={`/img/v2/${t.img}.webp`}
                      width={800}
                      height={800}
                      alt=""
                      loading="lazy"
                      decoding="async"
                    />
                  </div>
                  <div className="tip-copy">
                    <span className="tip-num" aria-hidden="true">
                      {numOf(i)}
                    </span>
                    <h4>{t.h}</h4>
                    <p>{t.p}</p>
                  </div>
                </Reveal>
              ))}
            </div>

            <ul className="point-list">
              {POINTS.map((pt) => (
                <li className="point-item" key={pt.h}>
                  <span className="point-ic">
                    <Ic name={pt.icon} />
                  </span>
                  <div className="point-body">
                    <h4>{pt.h}</h4>
                    <p>{pt.p}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {/* ============ 4. カテゴリ別・撮影チェックリスト ============ */}
          <div className="guide-section" id="cats">
            <div className="guide-section-head">
              <div className="guide-section-num">4</div>
              <div>
                <h2>カテゴリ別・撮影チェックリスト</h2>
                <p>品目によって業者が見たいポイントが異なります。</p>
              </div>
            </div>

            <div className="cat-guide-grid">
              {CATS.map((c, i) => (
                <Reveal as="div" className="cat-guide-card" delay={delayOf(i)} key={c.name}>
                  <div className="cat-name">
                    <span className="img-frame img-frame--pale img-frame--1x1 cat-ic">
                      <img
                        src={`/img/real/${c.img}.webp`}
                        width={512}
                        height={512}
                        alt=""
                        loading="lazy"
                        decoding="async"
                      />
                    </span>
                    {c.name}
                  </div>
                  <ul>
                    {c.items.map((li) => (
                      <li key={li}>{li}</li>
                    ))}
                  </ul>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ============ 末尾 CTA（濃紺帯。ボタンは帯の下の白面に置く） ============ */}
      <section className="deep-band pg-cta-band">
        <div className="container">
          <span className="deep-band__label">READY</span>
          <h2>準備ができたら、さっそく出品しよう</h2>
          <p>
            1点ずつ撮って、まとめて出すだけ。1点ずつ売る手間も、しつこい営業電話もありません。
            <br />
            出品・査定・お断りまで、ユーザーの費用は一切無料です。
          </p>
        </div>
      </section>

      <div className="pg-cta-actions">
        <div className="container">
          <div className="pg-cta-btns">
            {/* ヒーローと同一の 2 トーン構造。同じ文言のボタンが違う見た目で並ばないよう揃える。 */}
            <Link href="/login?callbackUrl=%2Fcreate" className="btn btn-line btn-lg">
              <span className="btn-line__tile" aria-hidden="true" />
              <span className="btn-line__body">
                <span className="btn-line__label">LINEではじめる（無料）</span>
                <span className="btn-line__sub">LINEアカウントでログインできます</span>
              </span>
              <Ic name="arrow" className="btn-line__arr" />
            </Link>
            <Link href="/" className="btn btn-ghost btn-lg">
              サービスの詳細を見る
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
