/* eslint-disable @next/next/no-img-element */
import type { Metadata } from "next";
import Link from "next/link";
import "./photo-guide.css";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { Reveal, RevealLines } from "@/components/kdz/interactions";

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
  "1回の出品で150枚まで載せられる",
  "写真が多いほど業者が状態を把握しやすい",
];

/** 撮影の上限（事実ベースの数値のみ） */
const LIMITS = ["写真は1点につき12枚まで", "1回の出品につき150枚まで"];

/** 撮影の手順（6ステップ） */
const STEPS: { h: string; p: string; tip: string }[] = [
  {
    h: "明るい場所に品物を移動する",
    p: "窓際や電気をつけた部屋など、できるだけ明るい場所を選びます。暗い写真は業者が状態を判断しにくくなります。",
    tip: "フラッシュより自然光のほうがきれいに写ります",
  },
  {
    h: "1点ずつ、全体が写るように撮る",
    p: "品物は1点ずつ撮影します。まず品物全体が写る「引きの写真」を1枚撮りましょう。撮った写真は自動的に1つのアルバムにまとまり、業者はそれを見て量と状態を把握します。",
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
    h: "傷・汚れ・色あせ・へこみは隠さず撮る",
    p: "傷・汚れ・色あせ・色落ち・へこみなど、気になる部分は隠さずアップで撮りましょう。正直に伝えておくと、訪問時に金額が変わりにくくなります。",
    tip: "傷があっても買い取ってもらえることが多いので安心してください",
  },
  {
    h: "品目名を出品画面に入力する",
    p: "写真に加えて品目名を入力すると、業者が検索して品物を特定しやすくなります。「ブランド名＋品目」が理想です。",
    tip: "例：「SONY α7III」「シャネル チェーンバッグ」「ダイソン V12」",
  },
];

/** ポイントのうち、写真で見せる3点（zig-zag の .media-split）
    ラウンド6 指摘（8）: 1:1 の画像に対して本文が2行しかなく、テキスト側に 150px 超の空きが残って
    読み進む動機が切れていた。画像の表示 AR は BRIEF §1.5「表示AR＝生成AR」（素材 1024x1024）の
    ため変えられないので、テキスト側に具体例の1行（tip）を足して左右の分量を均す。
    書式は §2 手順の .tip と同じ（ゴシック小・左に --marker の縦罫）。 */
const TIP_SPLITS: { img: string; h: string; p: string; tip: string }[] = [
  {
    img: "pg-tip-light",
    h: "明るく撮る",
    p: "照明を増やす、窓の近くで撮るなど明るさを確保。暗い写真は色や傷が見えにくく、業者が状態を判断しにくくなります。",
    tip: "例：日中に窓際で撮る。部屋の照明はすべて点ける",
  },
  {
    img: "pg-tip-bg",
    h: "背景をすっきりさせる",
    p: "無地の床や壁の前に品物を1点だけ置き、まわりのものはいったんどけます。背景が整うほど、形も色もそのまま伝わります。",
    tip: "例：無地の布やシーツを1枚敷いて、その上に置く",
  },
  {
    img: "pg-tip-detail",
    h: "全体と詳細の両方を撮る",
    p: "1点ごとに、全体が写る引きの写真＋気になる部分のアップ写真。この組み合わせが、いちばんよく伝わります。",
    tip: "例：引きで1枚＋ロゴ・型番・傷のアップで数枚",
  },
];

/** 残りの撮影ポイント（ヘアラインリスト。アイコンは Icons.tsx の近似） */
const POINTS: { icon: IcName; h: string; p: string }[] = [
  { icon: "tag", h: "ブランドロゴ・型番シール・タグはアップで", p: "メーカーロゴや型番シール、製造タグがくっきり読めるアップ写真があると、業者が品物を特定して相場を調べやすくなります。" },
  { icon: "box", h: "付属品も一緒に撮る", p: "箱・リモコン・充電器・説明書など付属品があれば一緒に撮影。付属品の有無まで業者に伝わります。" },
  { icon: "check-circle", h: "動作状態を伝える", p: "電源が入る家電は電源ON状態の写真を。動作が確認できると、業者が状態を判断しやすくなります。" },
  { icon: "up", h: "枚数は多いほどいい", p: "品物1点につき12枚、1回の出品で150枚まで載せられます。写真が多いほど、業者が現物を見ずに状態を確認しやすくなります。" },
];

/** カテゴリ別チェックリスト（品目名＋確認項目のみ。サムネイルは置かない）
    ラウンド6 指摘（5）: 行頭の 72px サムネは 3D 静物の中身が判別できず、1px 枠のボックスに
    小さな画像が乗るだけの構成が安く見えていた（512px 素材を 72px＝7.1倍で敷く BRIEF §1.11 の
    2x 規約超過もここが唯一の残件だった）。/img/real/cat-*.webp の参照を外し、箱組も畳んで
    ヘアラインの台帳（.point-list / /company の .co-vendor と同じ作法）にそろえる。
    Icons.tsx は core 所有・R4 で変更不可のため、6品目すべてに合う .ic が無い（家電・PC／ゲーム）。
    半端なアイコンを混ぜるより品目名のみで通す。 */
const CATS: { name: string; items: string[] }[] = [
  { name: "ブランド品", items: ["ロゴ・刻印が見える写真", "バッグは内側・金具も撮影", "付属品（保存袋・箱）も", "傷・汚れ・色あせは正直に"] },
  { name: "家電・PC", items: ["型番・メーカーが見える写真", "電源ON状態の写真があると◎", "リモコン・充電器も一緒に", "製造年が分かれば伝える"] },
  { name: "時計", items: ["文字盤・ケースバック・竜頭", "ブランドロゴが読めるアップ", "箱・保証書・余りコマも撮影", "傷・色あせの状態を正直に"] },
  { name: "カメラ", items: ["ボディ・レンズを別々に撮影", "センサーの状態（埃・カビ確認）", "付属レンズ・フラッシュも", "動作確認済みなら必ず伝える"] },
  { name: "家具", items: ["正面・側面・背面・底面を撮影", "傷・へこみ・色あせはアップで", "サイズが分かる写真があると◎", "解体できる場合は伝える"] },
  { name: "ゲーム", items: ["本体・コントローラーを一緒に", "ソフトはタイトルが読める写真", "付属品・箱があれば一緒に", "動作確認済みは必ず伝える"] },
];

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
          height={1088}
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
            カタヅケでは、業者は写真と品目情報をもとに入札します。上手に撮ると、業者が品物を判断しやすくなります。
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
            {/* 2026-09-15 ユーザー指示: LINEログイン着地先を/createから/mypageへ変更（他CTAと統一） */}
            <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line btn-lg">
              <span className="btn-line__tile" aria-hidden="true" />
              <span className="btn-line__body">
                <span className="btn-line__label">LINEではじめる（無料）</span>
                <span className="btn-line__sub">LINEアカウントでログインできます</span>
              </span>
              <Ic name="arrow" className="btn-line__arr" />
            </Link>
            <a href="#basics" className="btn btn-ghost btn-lg btn-swipe">
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
                <RevealLines mark="under" lines={["1点ずつ、全体が写るように撮る"]} />
                <p>
                  品物は1点ずつ撮影します。1枚の写真に1つの品物だけを、全体が写るように収めましょう。撮った写真はまとめて1つのアルバムになり、業者はそれを見て、入札する買取総額を決めます。
                </p>
              </div>
            </div>

            <div className="compare-grid">
              <figure className="compare-card">
                <Reveal as="figure" variant="zoom" className="img-frame img-frame--1x1 sp-bleed">
                  <img
                    src="/img/v2/pg-good.webp"
                    width={800}
                    height={800}
                    alt="明るい部屋で、ソファ1点の全体が枠に収まっている"
                    loading="lazy"
                    decoding="async"
                  />
                </Reveal>
                <figcaption className="compare-label">
                  <span className="compare-label-badge is-good">
                    <span aria-hidden="true">○</span>良い例
                  </span>
                  <p>1枚に1点。品物全体が写り、明るい場所で背景がすっきりしている。</p>
                </figcaption>
              </figure>

              <figure className="compare-card">
                <Reveal as="figure" variant="zoom" className="img-frame img-frame--1x1 sp-bleed">
                  <img
                    src="/img/v2/pg-bad.webp"
                    width={800}
                    height={800}
                    alt="暗い部屋で、洗濯物や箱が重なり、ソファが右端で見切れている"
                    loading="lazy"
                    decoding="async"
                  />
                </Reveal>
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
                <Reveal as="li" className="shoot-step" stagger={i} key={s.h}>
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
              写真に住所・氏名や他の人が写り込まないようご注意ください。書類や画面は伏せて撮ってください。
            </p>
            {/* ラウンド6 指摘（9）: 手順 06 の例示が他社の登録商標の実名で、記述的使用ではあっても
                自社の販促面に他社商標が並ぶため提携の誤認リスクが残る。「メーカー名＋型番」という
                書き方を示すには実名の例が最も伝わるので例示は残し、指摘が併記した代替のとおり
                商標の帰属と無関係であることを同一視野に1行で添える。 */}
            <p className="pg-note">
              ※ 記載の会社名・製品名は各社の商標または登録商標です。カタヅケと各社の提携関係を示すものではありません。
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
                  {/* ラウンド6 指摘（11）: この節の 01/02/03 は §2「撮影の手順」と同じ番号書式で、
                      どちらが手順でどちらが補足か読み分けられなかった。番号は手順章だけの記号として残し、
                      ポイント側は見出しのみにする。 */}
                  <div className="tip-copy">
                    <h4>{t.h}</h4>
                    <p>{t.p}</p>
                    <span className="tip">
                      <Ic name="spark" />
                      {t.tip}
                    </span>
                  </div>
                </Reveal>
              ))}
            </div>

            <ul className="point-list">
              {POINTS.map((pt) => (
                <li className="point-item" key={pt.h}>
                  <span className="point-ic" aria-hidden="true">
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
                <Reveal as="div" className="cat-guide-card" stagger={i} key={c.name}>
                  <div className="cat-name">{c.name}</div>
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

      {/* ============ 末尾 CTA（見出し・本文・ボタンを1ブロックに内包） ============
          ラウンド6 指摘（3 High / 6 High・同一箇所）: 濃紺帯が見出し＋本文2行で終わり、
          LINE と副 CTA の2本が帯の外の白地に落ちていたため、帯の下端に無駄な余白が残り
          「ボタンが帯からはみ出した崩れ」「章に属さず浮いたボタン」に見えていた。
          指摘3 の推奨案 A を採る: 面を --pale-2 に替え、CTA 行を同じ section の中に内包する。
          これで LINE CTA を --deep の上に置かない規約（BRIEF §1.3・R4 A.4）を保ったまま、
          見出し→本文→ボタンが1つのブロックとして読める（帯とボタンの間の白い谷が消える）。
          .deep-band は外す（面が濃紺でなくなるため）。READY ラベルは書式だけ
          .deep-band__label から借り、色を --primary に落とす（案 A の指定どおり）。 */}
      <section className="pg-cta-band">
        <div className="container">
          <span className="deep-band__label">READY</span>
          <RevealLines mark="under" lines={["準備ができたら、さっそく出品しよう"]} />
          <p>
            1点ずつ撮って、まとめて出すだけ。1点ずつ売る手間も、しつこい営業電話もありません。
            <br />
            出品・査定・お断りまで、ユーザーの費用は一切かかりません。
          </p>
          <div className="pg-cta-btns">
            {/* ヒーローと同一の 2 トーン構造。同じ文言のボタンが違う見た目で並ばないよう揃える。 */}
            {/* 2026-09-15 ユーザー指示: LINEログイン着地先を/createから/mypageへ変更（他CTAと統一） */}
            <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line btn-lg">
              <span className="btn-line__tile" aria-hidden="true" />
              <span className="btn-line__body">
                <span className="btn-line__label">LINEではじめる（無料）</span>
                <span className="btn-line__sub">LINEアカウントでログインできます</span>
              </span>
              <Ic name="arrow" className="btn-line__arr" />
            </Link>
            <Link href="/" className="btn btn-ghost btn-lg btn-swipe">
              サービスの詳細を見る
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
