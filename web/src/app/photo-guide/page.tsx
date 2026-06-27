import type { Metadata } from "next";
import Link from "next/link";
import "./photo-guide.css";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { Reveal } from "@/components/kdz/interactions";

export const metadata: Metadata = {
  title: "撮影ガイド",
  description:
    "カタヅケの撮影ガイド。上手に撮ると業者の評価が上がり、より高い買取額が届きやすくなります。",
  alternates: { canonical: "/photo-guide" },
};

/** メリットバーのチップ */
const MERITS = [
  "1点ずつ撮らなくてOK",
  "スマホで十分",
  "最大20枚まで追加できる",
  "写真が多いほど評価しやすい",
];

/** 撮影の手順（5ステップ） */
const STEPS: { h: string; p: string; tip: string }[] = [
  {
    h: "明るい場所に品物を移動する",
    p: "窓際や電気をつけた部屋など、できるだけ明るい場所を選びます。暗い写真は業者が状態を判断しにくくなります。",
    tip: "フラッシュより自然光のほうがきれいに映ります",
  },
  {
    h: "床・机に並べて全体写真を撮る",
    p: "まとめ全体が映る「引きの写真」を1〜2枚撮りましょう。業者はまずこの1枚でまとめの規模を把握します。",
    tip: "段ボールや袋の中のものは出して並べると評価が上がります",
  },
  {
    h: "価値がありそうなものは近づいて撮る",
    p: "ブランド品・家電・時計・カメラなど、高く売れそうなものはアップで撮影します。ブランドロゴや型番が読めると評価が上がります。",
    tip: "ブランドバッグはロゴ・内側・金具も撮るとベスト",
  },
  {
    h: "傷・汚れがあるものは正直に撮る",
    p: "状態を正直に伝えることで、現場での金額変更リスクが下がります。隠していると成約後のトラブルになることがあります。",
    tip: "傷があっても買取できることが多いので安心してください",
  },
  {
    h: "品目名を出品画面に入力する",
    p: "写真に加えて品目名を入力すると業者が検索・評価しやすくなります。「ブランド名+品目」が理想です。",
    tip: "例：「SONY α7III」「シャネル チェーンバッグ」「ダイソン V12」",
  },
];

/** 高評価につながる撮影のポイント（アイコンは Icons.tsx の近似に置換） */
const POINTS: { icon: IcName; h: string; p: string }[] = [
  { icon: "sun", h: "明るく撮る", p: "照明を増やす、窓の近くで撮るなど明るさを確保。暗い写真は業者が敬遠しがちです。" },
  { icon: "crop", h: "全体と詳細の両方を撮る", p: "引きの全体写真＋気になる品のアップ写真。この組み合わせが最も評価されます。" },
  { icon: "tag", h: "型番・ブランドが見えるように", p: "ラベルや刻印が映っているだけで業者が価格を調べやすくなり、高い入札につながります。" },
  { icon: "box", h: "付属品も一緒に撮る", p: "箱・リモコン・充電器・説明書など付属品があれば一緒に撮影。買取額がアップします。" },
  { icon: "check-circle", h: "動作状態を伝える", p: "電源が入る家電は電源ON状態の写真を。動作確認済みは買取額が大きく変わります。" },
  { icon: "up", h: "枚数は多いほどいい", p: "最大20枚まで追加できます。写真が多いほど業者が安心して高い入札を出せます。" },
];

/** カテゴリ別チェックリスト（実画像未投入のためアイコンタイルで表現） */
const CATS: { icon: IcName; name: string; items: string[] }[] = [
  { icon: "bag", name: "ブランド品", items: ["ロゴ・刻印が見える写真", "バッグは内側・金具も撮影", "付属品（保存袋・箱）も", "傷・汚れの状態を正直に"] },
  { icon: "sun", name: "家電・PC", items: ["型番・メーカーが見える写真", "電源ON状態の写真があると◎", "リモコン・充電器も一緒に", "製造年がわかれば伝える"] },
  { icon: "clock", name: "時計", items: ["文字盤・ケースバック・竜頭", "ブランドロゴが読めるアップ", "箱・保証書・コマ数も撮影", "傷の状態を正直に"] },
  { icon: "camera", name: "カメラ", items: ["ボディ・レンズを別々に撮影", "センサーの状態（埃・カビ確認）", "付属レンズ・フラッシュも", "動作確認済みなら必ず伝える"] },
  { icon: "sofa", name: "家具", items: ["正面・側面・背面を撮影", "傷・へこみの部分を接写", "サイズが分かる写真があると◎", "解体できる場合は伝える"] },
  { icon: "box", name: "ゲーム", items: ["本体・コントローラーを一緒に", "ソフトはタイトルが読める写真", "付属品・箱があれば一緒に", "動作確認済みは必ず伝える"] },
];

/** スクロール演出の遅延（3列グリッド用） */
const delayOf = (i: number) => ((i % 3 || undefined) as 1 | 2 | undefined);

export default function PhotoGuidePage() {
  return (
    <main id="main">
      {/* ============ ヒーロー ============ */}
      <section className="guide-hero">
        <div className="container">
          <span className="eyebrow">PHOTO GUIDE</span>
          <h1>
            撮るほど、
            <br />
            高く売れる。
          </h1>
          <p>
            カタヅケでは写真と品目情報が業者の入札根拠になります。上手に撮ると評価が上がり、より高い買取額が届きやすくなります。
          </p>
          <div className="cta-wrap">
            <Link href="/create" className="btn btn-white btn-lg">
              さっそく出品する
              <Ic name="arrow" className="arw" />
            </Link>
          </div>
        </div>
      </section>

      {/* ============ メリットバー ============ */}
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
          {/* ============ 1. まとめて並べて撮る（良い例・悪い例） ============ */}
          <div className="guide-section" id="basics">
            <div className="guide-section-head">
              <div className="guide-section-num">1</div>
              <div>
                <h2>まとめて並べて撮る</h2>
                <p>
                  床や机の上に品物を並べて、全体が映るように引いて撮りましょう。業者はまとめの全体像を見て入札額を決めます。
                </p>
              </div>
            </div>

            <div className="compare-grid">
              <div className="compare-card good">
                <div className="compare-photo good-bg">
                  <div className="compare-photo-illus">
                    <svg viewBox="0 0 200 150" width="200" height="150" aria-hidden="true">
                      <rect x="10" y="10" width="180" height="130" rx="8" fill="#f0f7ff" />
                      <rect x="20" y="25" width="40" height="30" rx="4" fill="#90caf9" />
                      <rect x="70" y="25" width="35" height="40" rx="4" fill="#a5d6a7" />
                      <rect x="115" y="20" width="30" height="25" rx="3" fill="#ffcc80" />
                      <rect x="155" y="28" width="25" height="22" rx="3" fill="#ce93d8" />
                      <rect x="20" y="65" width="55" height="35" rx="4" fill="#80deea" />
                      <rect x="85" y="75" width="40" height="25" rx="4" fill="#ef9a9a" />
                      <rect x="135" y="60" width="45" height="45" rx="4" fill="#fff9c4" />
                      <path d="M100 8 L100 14" stroke="#f0b429" strokeWidth="2.5" strokeLinecap="round" />
                      <path d="M120 5 L118 11" stroke="#f0b429" strokeWidth="2" strokeLinecap="round" />
                      <path d="M80 5 L82 11" stroke="#f0b429" strokeWidth="2" strokeLinecap="round" />
                      <circle cx="170" cy="130" r="12" fill="#4ade80" />
                      <path d="M164 130 L168 134 L176 126" stroke="#fff" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                </div>
                <div className="compare-label">
                  <span className="compare-label-badge">良い例</span>
                  <p>品物を並べ、全体が映るように撮影。明るい場所で背景がすっきりしている。</p>
                </div>
              </div>

              <div className="compare-card bad">
                <div className="compare-photo bad-bg">
                  <div className="compare-photo-illus">
                    <svg viewBox="0 0 200 150" width="200" height="150" aria-hidden="true">
                      <rect x="10" y="10" width="180" height="130" rx="8" fill="#fff5f5" />
                      <rect x="15" y="60" width="50" height="60" rx="4" fill="#ffcdd2" transform="rotate(-15,40,90)" />
                      <rect x="80" y="20" width="90" height="70" rx="4" fill="#e0e0e0" />
                      <rect x="40" y="30" width="35" height="50" rx="4" fill="#ffecb3" transform="rotate(10,57,55)" />
                      <rect x="120" y="90" width="60" height="40" rx="4" fill="#b3e5fc" transform="rotate(-5,150,110)" />
                      <rect x="10" y="10" width="180" height="130" rx="8" fill="rgba(0,0,0,0.25)" />
                      <circle cx="170" cy="130" r="12" fill="#f87171" />
                      <path d="M165 125 L175 135M175 125 L165 135" stroke="#fff" strokeWidth="2.5" fill="none" strokeLinecap="round" />
                    </svg>
                  </div>
                </div>
                <div className="compare-label">
                  <span className="compare-label-badge">悪い例</span>
                  <p>暗くて見えにくい。品物が重なっていて何があるか分からない。</p>
                </div>
              </div>
            </div>
          </div>

          {/* ============ 2. 撮影の手順 ============ */}
          <div className="guide-section" id="steps">
            <div className="guide-section-head">
              <div className="guide-section-num">2</div>
              <div>
                <h2>撮影の手順</h2>
                <p>5分あれば十分です。この順番で撮ると業者が評価しやすくなります。</p>
              </div>
            </div>

            <div className="shoot-steps">
              {STEPS.map((s, i) => (
                <Reveal as="div" className="shoot-step" key={s.h}>
                  <div className="shoot-step-num">{i + 1}</div>
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
            </div>
          </div>

          {/* ============ 3. 高評価につながる撮影のポイント ============ */}
          <div className="guide-section" id="tips">
            <div className="guide-section-head">
              <div className="guide-section-num">3</div>
              <div>
                <h2>高評価につながる撮影のポイント</h2>
                <p>少し意識するだけで入札額が変わります。</p>
              </div>
            </div>

            <div className="point-grid">
              {POINTS.map((pt) => (
                <Reveal as="div" className="point-card" key={pt.h}>
                  <div className="point-ic">
                    <Ic name={pt.icon} />
                  </div>
                  <div className="point-body">
                    <h4>{pt.h}</h4>
                    <p>{pt.p}</p>
                  </div>
                </Reveal>
              ))}
            </div>
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
                    <span className="cat-ic">
                      <Ic name={c.icon} />
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

          {/* ============ CTA ============ */}
          <Reveal className="guide-cta">
            <div className="guide-cta-inner">
              <h2>準備ができたら、さっそく出品しよう</h2>
              <p>
                まとめて並べて撮るだけ。1点ずつ売る手間も、しつこい営業電話もありません。
                <br />
                出品・査定・お断りまで、ユーザーの費用は一切無料です。
              </p>
              <div className="btn-wrap">
                <Link href="/create" className="btn btn-white btn-lg">
                  出品をはじめる
                  <Ic name="arrow" className="arw" />
                </Link>
                <Link
                  href="/"
                  className="btn btn-ghost btn-lg"
                  style={{ color: "rgba(255,255,255,.7)", borderColor: "rgba(255,255,255,.3)", background: "transparent" }}
                >
                  サービスの詳細を見る
                </Link>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </main>
  );
}
