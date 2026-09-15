import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { Reveal, FaqAccordion, HeroCarousel, type HeroSlide } from "@/components/kdz/interactions";
import { KdzLogo } from "@/components/kdz/Logo";
import {
  FEATURED_CASES,
  caseName,
  MODEL_CASE_CHIP,
  MODEL_CASE_NOTE,
} from "@/lib/model-cases";
import "./katazuke-top.css";

/** 対応カテゴリ（3Dアイコンで表現） */
const CATEGORIES: { img: string; name: string; ex: string }[] = [
  { img: "cat-kaden", name: "生活家電", ex: "冷蔵庫・洗濯機ほか" },
  { img: "cat-brand", name: "ブランド品", ex: "バッグ・財布" },
  { img: "cat-furniture", name: "家具", ex: "ソファ・収納" },
  { img: "cat-camera", name: "カメラ・PC", ex: "一眼・ノートPC" },
  { img: "cat-watch", name: "時計・宝飾", ex: "腕時計・アクセ" },
  { img: "cat-game", name: "ゲーム・玩具", ex: "ゲーム機・フィギュア" },
  { img: "cat-fashion", name: "ファッション", ex: "衣類・靴・小物" },
  { img: "cat-music", name: "楽器・趣味", ex: "ギター・道具" },
  { img: "cat-tableware", name: "食器・骨董", ex: "食器・茶道具" },
  { img: "cat-sport", name: "スポーツ", ex: "ゴルフ・アウトドア" },
  { img: "cat-tools", name: "工具・DIY", ex: "電動工具ほか" },
  { img: "cat-other", name: "その他いろいろ", ex: "まずは撮ってみる" },
];

/** ヒーローの人物カルーセル（2026-09-14 ユーザー指示）。
 *  「若い女性→若い男性→30代夫婦と子ども→60代夫婦」の順で、誰が使うサービスかを一人の像に
 *  固定しない。全カット同じ 2:3（1024x1536→900x1350）・同じ構図の語彙（床に座り、待たせている
 *  持ち物のそばでスマホを構える）で撮影し、切り替わっても「同じ部屋・同じ行為」に見えるようにする。 */
const HERO_SLIDES: HeroSlide[] = [
  { id: "top-hero-woman-20s", width: 900, height: 1350, alt: "リビングの床で、不用品をスマートフォンで撮影する20代の女性（イメージ）" },
  { id: "top-hero-man-20s", width: 900, height: 1350, alt: "リビングの床で、不用品をスマートフォンで撮影する20代の男性（イメージ）" },
  { id: "top-hero-couple-child", width: 900, height: 1350, alt: "子どもと一緒に、不用品をまとめて撮影する30代の夫婦（イメージ）" },
  { id: "top-hero-couple-60s", width: 900, height: 1350, alt: "並べた不用品をスマートフォンで撮影する60代の夫婦（イメージ）" },
];

const FAQ_ITEMS = [
  { q: "1点だけでも依頼できますか？", a: "はい。ただし、まとめて出すほど業者の買取総額が伸びやすく、値がつかない物も一緒に引き取ってもらいやすくなります。" },
  { q: "値段がつかない物はどうなりますか？", a: <>業者は1点ごとではなく<span className="mk">出品した商品すべてに対する買取総額で入札</span>します。単体では値がつきにくい物も、他の商品と一緒に引き取ってもらえる場合があります。</> },
  { q: "しつこい営業電話は来ますか？", a: "連絡が来るのは、あなたが選んだ1社だけ。選ぶまで連絡先は業者に開示されず、選ばなかった業者には自動でお断りが入るため、一斉架電は起こりません。" },
  { q: "個人情報はどう扱われますか？", a: "査定段階で業者に渡るのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。お名前や電話番号が業者に渡ることはなく、詳細住所と連絡用のメールアドレスも交渉が成立した1社にのみ開示されます。" },
  { q: "利用にお金はかかりますか？", a: "出品・査定・成約まで、すべて無料です。費用は一切かかりません。" },
  { q: "訪問買取は安全ですか？", a: "参加するのは、古物商許可番号の登録を必須とし、運営が許可証を確認した登録事業者のみ。訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があり、クーリング・オフの可否は品目や契約に至った経緯によって異なります。業者から交付される書面をご確認ください。" },
];

/** ご利用の流れ。ラウンド5 までは既存 3D シリーズ（/img/real/how-*.webp）を 220px の枠で使っていたが、
    ラウンド6 指摘（5・9・12）で 3 視点が「意味と結びつかない・玩具の置物に見える」と一致したため図版を撤去し、
    番号＋見出しのテキストステップにした（素材の実物: how-camera=浮いたコンパクトカメラ、
    how-trend=木製の棒グラフ、how-crown=宝飾の王冠リング、how-truck=玩具のトラック。
    3 枚は #cats のカテゴリ商品写真と語彙が重なる）。差し替え素材は /img/v2 に無い（画像は全点投入済み）。 */
const STEPS: { n: string; en: string; h: string; p: string }[] = [
  { n: "1", en: "SHOOT", h: "1点ずつ撮る", p: "家じゅうの不用品を1点ずつ撮影。写真と品目をまとめて登録するだけで出品完了です。" },
  { n: "2", en: "WAIT", h: "査定が届く", p: "買取業者があなたの出品した商品に入札。あなたは待つだけで査定が集まります。" },
  { n: "3", en: "CHOOSE", h: "査定を見比べて選ぶ", p: "届いた査定を一覧で見比べて、納得の1社を選ぶだけ。選ぶまで、業者から連絡は来ません。" },
  { n: "4", en: "DONE", h: "引き取りに来てもらう", p: "成立した業者がまとめて引き取りに。玄関先で渡すだけで、片付け完了です。" },
];

/** 利用シーン。人物写真は撤去し、場面を示す静物（1:1）に置換 */
const SCENES: { tag: string; h: string; p: string; img: string }[] = [
  { tag: "断捨離", h: "暮らしを身軽に", p: "使わない物をまとめて手放し、すっきりした部屋に。1点からでも、まとめてでも。", img: "top-scene-danshari" },
  { tag: "引越し", h: "新居に持っていかない物を", p: "荷造りのついでに撮るだけ。運ぶ前にまとめて買取・回収できます。", img: "top-scene-moving" },
  { tag: "実家じまい", h: "家族で、まとめて整理", p: "量が多く判断に迷う実家の整理も、撮ってまとめれば業者がまとめて査定。", img: "top-scene-jikka" },
  { tag: "遺品整理", h: "ていねいに、まとめて", p: "値がつかない物も含めてまとめて回収。気持ちの整理も、無理なく進められます。", img: "top-scene-ihin" },
];

/** よくある不安。人物実写のストック写真を撤去し、静物 1:1 の連作に置換 */
const WORRIES: { h: string; p: string; img: string }[] = [
  { h: "出品も発送も、正直めんどう", p: "撮影・採寸・説明文・梱包・発送・購入者対応。フリマは手間が多く、量が多いほど踏み出せません。", img: "top-worry-listing" },
  { h: "営業電話が、一斉にかかってくる", p: "一括査定に申し込んだ途端、多数の業者から電話が殺到。応対だけで疲れ、結局決めきれません。", img: "top-worry-phone" },
  { h: "そもそも、何から手をつければ", p: "売れる物・売れない物、仕分けの基準がわからない。家まるごととなると、考えるだけで腰が重くなります。", img: "top-worry-boxes" },
];

const delayOf = (i: number) => ((i % 3 || undefined) as 1 | 2 | undefined);

export default function HomePage() {
  return (
    <>
      <main id="main">
        <div className="site-frame">
        {/* ============ HERO ============ */}
        <section className="hero" id="top">
          <div className="container hero-grid">
            <div className="hero-copy">
              <h1>
                片付けたい。でも、
                <br />
                <span className="hl">動けない</span>あなたへ。
              </h1>
              <p className="hero-sub">
                家じゅうの不用品を、<strong>1点ずつ撮って、あとは待つだけ</strong>。登録業者が<span className="mk">買取総額</span>で競い合い、値がつかない物もまとめて引き取ります。営業電話に追われることはありません。
              </p>
              {/* R4 E.1-1: 「撮るだけ・待つだけ」は .hero-sub の「1点ずつ撮って、あとは待つだけ」と重複するため
                  3 項目に減らす。CTA 直下に安心 1 行は足さない（直下の .assure 帯に同じ約束があり、
                  ファーストビューで同じ約束が 3 回並ぶため）。 */}
              <ul className="hero-trust">
                {/* eslint-disable @next/next/no-img-element */}
                <li><span className="tb"><img src="/img/real/check.webp" alt="" width={512} height={512} loading="lazy" decoding="async" /></span>まとめるほど高くなりやすい</li>
                <li><span className="tb"><img src="/img/real/check.webp" alt="" width={512} height={512} loading="lazy" decoding="async" /></span>値がつかない物も回収</li>
                <li><span className="tb"><img src="/img/real/check.webp" alt="" width={512} height={512} loading="lazy" decoding="async" /></span>連絡は選んだ1社だけ</li>
                {/* eslint-enable @next/next/no-img-element */}
              </ul>
              {/* 4ステップ帯は番号＋文字のみ（アイコンは「ご利用の流れ」で大きく1箇所に集める） */}
              <div className="hero-how">
                <div className="hw-step"><span className="hw-n">1</span><span>撮る</span></div>
                <Ic name="arrow" className="hw-arr" />
                <div className="hw-step"><span className="hw-n">2</span><span>業者が競う</span></div>
                <Ic name="arrow" className="hw-arr" />
                <div className="hw-step"><span className="hw-n">3</span><span>見比べて選ぶ</span></div>
                <Ic name="arrow" className="hw-arr" />
                <div className="hw-step"><span className="hw-n">4</span><span>引き取り完了</span></div>
              </div>
              <div className="hero-cta">
                {/* ユーザー指示によりLINEログイン後の着地先を /create から /mypage へ変更
                    （2026-09-15）。従来はコピー「まずは1枚、撮ってみることから」に合わせて
                    /create 固定だったが、マイページ着地を優先する方針に変更。 */}
                <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line btn-lg">
                  <span className="btn-line__tile" aria-hidden="true" />
                  <span className="btn-line__body">
                    <span className="btn-line__label">LINEではじめる（無料）</span>
                    <span className="btn-line__sub">LINEアカウントでログインできます</span>
                  </span>
                  <Ic name="arrow" className="btn-line__arr" />
                </Link>
                {/* ラウンド4（22）: 「仕組みを確認する」では着地が分からず、LINE を押せない人の受け皿に
                    ならない。着地（このページ内の「入札のしくみ」節）を label に出し、同一ページ内移動を
                    ↓ で示す（/photo-guide の「読んでから決める ↓」と語彙を揃える）。
                    所要時間（「1分でわかる」）は E 章「新しい約束・期間・効果を書かない」に反するため書かない。 */}
                <Link href="/#auction" className="btn btn-ghost btn-lg">入札のしくみを見る ↓</Link>
              </div>
            </div>
            <div className="hero-figure">
              {/* 2026-09-14: 単一の人物像を「若い女性→若い男性→30代夫婦と子ども→60代夫婦」の
                  4カット巡回に変更（ユーザー指示）。AR は .hero-photo--2x3（PC 2:3 / 859px 以下 4:5）が持ち、
                  859px 以下の切り位置は .img-frame--hero-person（core・katazuke.css）が持つ。
                  4カットとも同じ 2:3 素材（構図の語彙を揃えてあるため --pos の値もそのまま使い回せる）。
                  実装は HeroCarousel（components/kdz/interactions.tsx）。1枚目のみ LCP。
                  ▼手元版（人物なし）の控え。単一カットに戻す場合はこのコメントを参照:
                     src="/img/v2/top-hero.webp"
                     alt="床に並べた不用品をスマートフォンで1点ずつ撮影する手元（イメージ）" */}
              <figure className="hero-photo hero-photo--2x3 sp-bleed">
                <HeroCarousel slides={HERO_SLIDES} />
              </figure>
            </div>
          </div>
        </section>

        {/* ============ 信頼の根拠（帯） ============ */}
        <section className="assure" aria-label="サービスの安心ポイント">
          <div className="container">
            {/* 行頭は既存の線アイコン .ic。3D レンダー（1024px 素材）を 56px 枠に縮小すると
                被写体と枠地が同色になり空箱に見えるため（ラウンド2 実測・BRIEF §4-15
                「3D は 112px 以上の枠でしか使わない」）、.assure-item .ai 本来の
                「--pale 面＋--primary 罫＋currentColor の線画」に戻す。 */}
            <div className="assure-item"><span className="ai"><Ic name="shield" /></span><span><b>登録事業者のみ</b><span>古物商許可を確認</span></span></div>
            <div className="assure-item"><span className="ai"><Ic name="lock" /></span><span><b>連絡先は成立後に開示</b><span>氏名・電話は渡りません</span></span></div>
            <div className="assure-item"><span className="ai"><Ic name="phone" /></span><span><b>一斉架電なし</b><span>連絡は選んだ1社だけ</span></span></div>
            <div className="assure-item"><span className="ai"><Ic name="pin" /></span><span><b>東京・千葉・埼玉・神奈川</b><span>順次エリア拡大中</span></span></div>
          </div>
        </section>

        {/* ============ 共感（悩み） ============ */}
        <section className="section empathy">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">よくある不安</span>
              <h2>片付け、こんな<span className="mk">めんどう</span>で<br className="sp-br" />止まっていませんか</h2>
              <p className="sub">「家じゅうを片付けたい」気持ちはあるのに、最初の一歩でつまずく。多くの方が、同じところで止まっています。</p>
            </div>
            <div className="emp-grid">
              {WORRIES.map((w, i) => (
                <Reveal as="article" className="emp-card" delay={delayOf(i)} key={w.img}>
                  <div className="emp-photo img-frame img-frame--1x1 sp-bleed">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/img/v2/${w.img}.webp`} alt="" width={800} height={800} loading="lazy" decoding="async" />
                  </div>
                  <div className="emp-body"><h3>{w.h}</h3><p>{w.p}</p></div>
                </Reveal>
              ))}
            </div>
            <div className="turn"><p>カタヅケなら、その「めんどう」を<span className="accent">撮って待つだけ</span>に変えます。</p></div>
          </div>
        </section>
        </div>

        <div className="site-frame">
        {/* ============ STEPS（使い方） ============ */}
        <section className="section steps" id="flow">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">ご利用の流れ</span>
              <h2>あなたがするのは、<br className="sp-br" />「撮る」と「選ぶ」だけ</h2>
              <p className="sub">たった4ステップ。梱包も発送も、価格交渉も要りません。</p>
            </div>
            <div className="steps-grid">
              {STEPS.map((s, i) => (
                <Reveal as="article" className="step" delay={delayOf(i)} key={s.n}>
                  {/* 図版なし（上の STEPS のコメント参照）。区切りは 1px の上罫と余白だけ */}
                  <div className="step-body">
                    <span className="step-n"><span className="num">{s.n}</span>{s.en}</span>
                    <h3>{s.h}</h3>
                    <p>{s.p}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ============ 中間CTA ============ */}
        <div className="section-cta">
          <div className="container">
            <div className="scta-inner">
              <div className="scta-text">
                <strong>まず1枚、撮るだけ。<br className="sp-br" />今日から始められます。</strong>
                {/* R4 E.1-2: 既存の無料表記に「連絡は選んだ1社だけ」を並べ、CTA と同一視野に入れる */}
                <span>登録・査定・お断りまですべて無料<br />連絡が来るのは、選んだ1社だけ</span>
              </div>
              <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line btn-lg">
                <span className="btn-line__tile" aria-hidden="true" />
                <span className="btn-line__body">
                  <span className="btn-line__label">LINEではじめる（無料）</span>
                  {/* ラウンド6 指摘（10）: 補足が左の .scta-text「登録・査定・お断りまですべて無料」と
                      同内容で、同一視野に同じ文が 2 回出ていた。無料の条件は左のテキスト側に持たせ、
                      ボタン内はヒーロー／最終 CTA と同じ「押した先で何が起きるか」に戻す。 */}
                  <span className="btn-line__sub">LINEアカウントでログインできます</span>
                </span>
                <Ic name="arrow" className="btn-line__arr" />
              </Link>
            </div>
          </div>
        </div>

        {/* ============ BUNDLE ============ */}
        <section className="section bundle" id="bundle">
          {/* 縦書きの柱は節のラベルに徹する。h2 と同文だと見出しが縦横で二度読みになる（裁定7） */}
          <span className="vt" aria-hidden="true">まとめ売り</span>
          <div className="container">
            <div className="bundle-lead">
              <Reveal className="bundle-figure img-frame img-frame--contain">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/real/bundle-3d.webp" alt="さまざまな不用品がひとつの箱にまとまり、まとめて1つの価格がつくイメージ" width={1536} height={864} loading="lazy" decoding="async" />
              </Reveal>
              <Reveal className="bundle-copy" delay={1}>
                <span className="eyebrow">まとめ売り</span>
                <h2>まとめて出すほど、<br className="sp-br" /><span style={{ color: "var(--primary)" }}>有利</span>になる。</h2>
                <p className="lead">カタヅケは<span className="mk">家まるごと</span>の片付け向け。1点ずつではなく、たまった不用品をまとめて査定に出すほど、買取総額が伸びやすく、値がつかない物まで一緒に手放せます。</p>
              </Reveal>
            </div>
            <div className="bundle-grid">
              {/* 行頭は線アイコン .ic。1024px の 3D レンダーを 56〜72px 枠へ縮めると被写体がにじみ、
                  同じページの assure / trust / cats-note のチップだけ画質が落ちて見えた（ラウンド3 指摘）。
                  BRIEF §4-15「3D は 112px 以上の枠でしか使わない」に従い、チップの語彙を帯・安心の仕組みと揃える。 */}
              <Reveal as="article" className="bundle-c">
                <span className="bc-ic"><Ic name="trend" /></span>
                <h3>数が多いほど、総額が伸びやすい</h3>
                <p>業者は「まとめ買い」を望むため、点数が増えるほど買取総額の条件が良くなりやすい。1点ずつ売るより、まとめて出したほうが業者は仕入れやすくなります。</p>
              </Reveal>
              <Reveal as="article" className="bundle-c key" delay={1}>
                <span className="bc-badge">ここがポイント</span>
                <span className="bc-ic"><Ic name="bag" /></span>
                <h3>値がつかない物も、まとめて回収</h3>
                <p>業者は1点ごとではなく<strong className="mk">出品した商品すべてに対する買取総額で入札</strong>します。だから単体では値がつきにくい物も、他の商品と一緒に引き取り。「これは売れないかも」も、一緒に手放せます。</p>
              </Reveal>
              <Reveal as="article" className="bundle-c" delay={2}>
                <span className="bc-ic"><Ic name="box" /></span>
                <h3>仕分け・分別は不要</h3>
                <p>ジャンルが混ざっていてもOK。家じゅうの「どうしよう」を、思いついた物から撮ってまとめるだけ。あとは業者がまとめて査定します。</p>
              </Reveal>
            </div>
            <p className="bundle-note">※ 引き取りの可否・条件は品物や業者により異なります。一部、引き取りが難しい物は手放す導線をご案内します。</p>
          </div>
        </section>

        {/* ============ AUCTION ============ */}
        <section className="section auction" id="auction">
          <span className="vt" aria-hidden="true">入札のしくみ</span>
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">入札のしくみ</span>
              <h2>業者が<span className="mk">買取総額</span>で競うから、<br className="sp-br" />高くなりやすい。</h2>
              <p className="sub">あなたが出したのは写真だけ。あとは登録業者どうしが、あなたが出品した商品に買取総額で入札し合います。</p>
            </div>
            <div className="auc-grid">
              <Reveal className="auc-figure img-frame img-frame--contain">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/real/bid-3d.webp" alt="複数の業者が、まとめた不用品に買取総額を提示して競り合うイメージ" width={1536} height={864} loading="lazy" decoding="async" />
              </Reveal>
              <ol className="auc-steps">
                <li><span className="an">1</span><div><h4>連絡先を伏せて出品内容が届く</h4><p>業者に届くのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。あなたのお名前・電話・詳細住所は伏せたままです。</p></div></li>
                <li><span className="an">2</span><div><h4>登録業者が買取総額で入札</h4><p>複数の業者が、出品した商品すべてに対して買取総額を提示します。提示された総額は、すべて一覧で見比べられます。</p></div></li>
                <li><span className="an">3</span><div><h4>連絡が来るのは選んだ1社だけ</h4><p>選ぶまで、業者はあなたに連絡できません。選ばなかった業者には自動でお断りが入り、営業電話の一斉架電はありません。</p></div></li>
                <li><span className="an">4</span><div><h4>あなたは選んで、引き取りを待つだけ</h4><p>提示を見比べて1社を選択。成立後に連絡先を開示し、引き取り日時を決めます。</p></div></li>
              </ol>
            </div>
            <p className="auc-note">※ 最終的な買取額は業者の現物査定により決まります。</p>
          </div>
        </section>

        {/* ============ HANDOVER ============ */}
        <section className="section handover">
          <div className="container media-split">
            <Reveal className="handover-figure img-frame img-frame--3x2 sp-bleed">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/img/v2/top-handover.webp" width={1600} height={1067} alt="玄関先で、まとめた品物を業者に引き渡す場面（イメージ）" loading="lazy" decoding="async" />
            </Reveal>
            <Reveal className="media-copy" delay={1}>
              <span className="eyebrow">引き渡しの流れ</span>
              <h2>業者が直接、引き取りに来ます</h2>
              <p className="sub">梱包も発送も、あなたはしなくていい。選んだ業者がまとめて引き取りに来ます。やりとりするのは、交渉が成立した相手とだけです。</p>
              <ul className="mlist">
                {/* eslint-disable @next/next/no-img-element */}
                <li><span className="ck"><img src="/img/real/check.webp" alt="" width={512} height={512} loading="lazy" decoding="async" /></span>梱包も発送も不要。玄関先で引き渡すだけ。</li>
                <li><span className="ck"><img src="/img/real/check.webp" alt="" width={512} height={512} loading="lazy" decoding="async" /></span>連絡先が業者に渡るのは、交渉成立後。</li>
                <li><span className="ck"><img src="/img/real/check.webp" alt="" width={512} height={512} loading="lazy" decoding="async" /></span>訪問日時は、あなたの都合で選べます。</li>
                <li><span className="ck"><img src="/img/real/check.webp" alt="" width={512} height={512} loading="lazy" decoding="async" /></span>大型家具や大量の品も、まとめて相談OK。</li>
                {/* eslint-enable @next/next/no-img-element */}
              </ul>
            </Reveal>
          </div>
        </section>

        {/* ============ 利用シーン ============ */}
        <section className="section scenes">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">こんな時に</span>
              <h2><span className="mk">家まるごと</span>の片付けに</h2>
              <p className="sub">まとまった量を手放したいときほど、カタヅケが力を発揮します。</p>
            </div>
            <div className="scenes-grid">
              {SCENES.map((s, i) => (
                <Reveal as="article" className="scene-card" delay={delayOf(i)} key={s.tag}>
                  <div className="scene-img img-frame img-frame--1x1 img-frame--pale">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/img/v2/${s.img}.webp`} alt="" width={800} height={800} loading="lazy" decoding="async" />
                  </div>
                  <div className="scene-body">
                    <span className="scene-tag">{s.tag}</span>
                    <h3>{s.h}</h3>
                    <p>{s.p}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ============ 利用イメージ（架空のモデルケース） ============ */}
        {/* R4 B.2: 「こんな時に」（.scenes）で自分を重ねた直後に置く。
            数値・文言はすべて @/lib/model-cases の FEATURED_CASES から描画する（直書き禁止。
            /examples と値がずれないようにするため）。
            景表法: .model-note をカード群より手前・.model-chip を各カードの先頭（肖像より上）に置く。
            トップに金額は出さない（上位3件の額だけを見た読者に平均像を与えないため。
            買取額の例は 6 件すべてが並ぶ /examples に限定する）。 */}
        <section className="section model-cases" id="model-cases">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">利用イメージ</span>
              <h2>こんなふうに使えます</h2>
              {/* ラウンド5 指摘（2/9）: 架空の打消しが sub ＋ .model-note ＋ 各カードのチップ ＋
                  カード下の 1 行で 4 重になり「守りが過剰＝かえって信用できない」印象になっていた。
                  sub は 2 文目「実際の利用実績ではありません。」を落として 1 文に絞る（同義の明示は
                  直下の .model-note が「実際の取引実績ではなく…」で担うため、明示は弱まらない）。 */}
              <p className="sub">サービスの流れをイメージしていただくための、架空のモデルケースです。</p>
            </div>
            {/* ラウンド5 指摘（4/12/19）: ラウンド4 で置いた業者募集の 1 行
                （「カタヅケは現在、参加いただける買取業者を募集しています。」）を、この節から外した。
                依頼者向けの節（肖像の直前）に別の宛先の文が挟まって流れが切れ、安心材料を探している
                位置では「まだ買ってくれる人がいない」と読める、と 3 視点が一致して指摘。
                事実は #trust の「登録制の事業者のみ」（依頼者向けの安心の文脈）へ移し、業者への
                募集そのものは同ページ下部の .biz-banner（「カタヅケに参加しませんか」＋審査制・登録無料）
                が既に担っているため、重複する 1 文を新設しない。 */}
            <p className="model-note" role="note">{MODEL_CASE_NOTE}</p>
            <div className="mc-grid">
              {FEATURED_CASES.map((c, i) => (
                <Reveal as="article" className="mc-card" delay={delayOf(i)} key={c.id}>
                  <span className="model-chip">{MODEL_CASE_CHIP}</span>
                  <div className="mc-fig img-frame img-frame--1x1">
                    {/* 1:1 の枠に 1:1 の素材＝トリミングが起きないため --pos は書かない（R4 D.2 #11-13） */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/img/v2/${c.portrait}.webp`} alt={c.portraitAlt} width={800} height={800} loading="lazy" decoding="async" />
                  </div>
                  <p className="mc-who">
                    <span className="mc-name">{caseName(c)}</span>
                    <span className="mc-attr">{c.persona}／{c.tag}</span>
                  </p>
                  <p className="mc-quote">「{c.quoteShort}」</p>
                  {/* ラウンド5 指摘（3/8/13/18）: 入札社数を R4 B.2 の指定どおり中央に戻し、
                      点数／入札／成約までの横 3 分割にする。ラウンド4 で外した理由（「8社前後は
                      入札が来る」という平均像＝実質的な集計統計になる）は、ラウンド5 で
                      lib/model-cases.ts の bidCount が 3〜5 に下がり（featured は 5／3／5）
                      「だいたい◯社」と読める並びではなくなったため解消した。
                      あわせて、直前の .model-note が「金額・入札数はいずれも架空」と入札数に
                      言及しているのに画面に入札数がない不一致（13）と、/examples との情報量の
                      食い違い（8/18）も消える。値は必ず FEATURED_CASES から描画（直書き禁止）。
                      成約件数は同一カードに並べないので、割り算で成約率は得られない（R4_BRIEF §15）。
                      金額は引き続きトップに出さない（6 件すべてが並ぶ /examples に限定・B.2）。 */}
                  <dl className="mc-facts">
                    <div><dt>まとめて出品</dt><dd><b>{c.count}</b><span>点</span></dd></div>
                    <div><dt>入札</dt><dd><b>{c.bidCount}</b><span>社</span></dd></div>
                    <div><dt>成約まで</dt><dd><b>{c.days}</b><span>日</span></dd></div>
                  </dl>
                  {/* ラウンド5 指摘（2/9）: カード下の「架空のモデルケースの数値です」を削除した
                      （打消しは各カード先頭の .model-chip ＋ カード群手前の .model-note が担う）。
                      ラウンド4 でこの 1 行を足した根拠は「モバイルでスクロールするとカード上端の
                      チップが画面外に出る」だったが、390px のカード実測（チップ 32 ＋ 肖像 350 ＋
                      氏名 46 ＋ 一言 60 ＋ 数値 76 ≒ 564px < 表示領域 700px 前後）では
                      チップと数値が同一視野に収まるため、近接は維持できている。 */}
                </Reveal>
              ))}
            </div>
            <p className="mc-more">
              <Link href="/examples">6件のモデルケース（買取額の例を含む）を見る<Ic name="arrow" /></Link>
            </p>
          </div>
        </section>
        </div>

        <div className="site-frame">
        {/* ============ TRUST ============ */}
        <section className="section trust" id="trust">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">安心の仕組み</span>
              <h2>はじめてでも、<br className="sp-br" />安心して任せられる</h2>
              <p className="sub">「知らない業者は不安」を解消するために。カタヅケは、参加する業者とあなたの情報の扱いに、きちんと線を引いています。</p>
            </div>
            <div className="media-split trust-split">
              <Reveal className="trust-hero img-frame img-frame--contain">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/real/trust-illus-1.webp" alt="登録事業者の古物商許可を確認するイメージ" width={1024} height={768} loading="lazy" decoding="async" />
              </Reveal>
              <Reveal className="trust-list" delay={1}>
                {/* 行頭アイコンは帯（.assure-item .ai）と同じ 56px チップ＋線アイコンに統一。
                    1024px の 3D レンダーを 64px 枠へ縮小すると灰色のにじみにしか見えず、
                    3 項の行頭も揃わなかった（ラウンド2 実測・BRIEF §4-15）。 */}
                <article className="trust-item">
                  <span className="ti-ic"><Ic name="shield" /></span>
                  {/* ラウンド5 指摘（19）: モデルケース節の冒頭にあった業者募集の 1 行を、
                      依頼者の安心材料として読める位置（この項）へ事実のまま移した。
                      対応エリアは .assure 帯・/vendors と同じ 4 都県、審査の運用は /business
                      （審査制）と /vendors の空状態文（「運営が承認した業者のみを掲載します」）の
                      再掲で、新しい約束・期間・効果は足していない。 */}
                  <div className="ti-body"><h3>登録事業者のみ</h3><p>査定に参加するのは登録された買取事業者だけ。古物営業に必要な古物商許可を、登録時・取引前に確認します。対応エリアは東京・千葉・埼玉・神奈川で、審査を通過した業者から順に参加します。</p></div>
                </article>
                <article className="trust-item">
                  <span className="ti-ic"><Ic name="lock" /></span>
                  <div className="ti-body"><h3>連絡先は成立後に開示</h3><p>査定段階で業者に渡るのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。お名前や電話番号は業者に渡らず、詳細住所と連絡用のメールアドレスは交渉が成立するまで開示されません。</p></div>
                </article>
                <article className="trust-item">
                  <span className="ti-ic"><Ic name="scale" /></span>
                  <div className="ti-body"><h3>訪問買取は特定商取引法の対象</h3><p>訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があります。一部の物品は法令により対象外とされています。お客様の品物が対象かどうかは、訪問した業者が交付する書面に記載されます。ご不明な場合は消費者ホットラインにご相談ください。</p></div>
                </article>
              </Reveal>
            </div>
          </div>
        </section>

        {/* ============ 料金 ============ */}
        <section className="section bg-pale fee" id="fee">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">料金について</span>
              <h2>費用は、一切かかりません</h2>
              <p className="sub">出品・査定・成約まで、すべて無料です。</p>
            </div>
            <Reveal className="fee-zero">
              <span className="fz-label">お客様のお支払い</span>
              <strong className="fz-num">¥0</strong>
              <span className="fz-note">出品・査定・お断り・引き取りまで、費用は一切かかりません。</span>
              {/* ラウンド4（20）: 減額相談の注記は最下部の最小級の※ではなく ¥0 と同一視野に、本文サイズ・
                  肯定形で置く（打消し表示は強調表示と同程度に認識できる大きさ・近接で示す）。
                  意味は旧 .fee-caution と同一で、新しい約束・期間は足していない。 */}
              <span className="fz-caution">訪問時の現物確認で写真と状態が違えば、業者から金額のご相談が届くことがあります。納得できなければお断りできます（お断りにも費用はかかりません）。</span>
            </Reveal>
            <Reveal className="fee-card" delay={1}>
              <div className="fee-head"><h3>出品から成約まで、お金はかかりません</h3><p>出品・査定・お断りまで、すべて無料</p></div>
              <div className="fee-rows">
                <div className="fee-row"><span className="fl">写真・品目の登録<small>まとめて出品するだけ</small></span><span className="fv">無料</span></div>
                <div className="fee-row"><span className="fl">出品・査定<small>業者への出品と入札の受け取り</small></span><span className="fv">無料</span></div>
                <div className="fee-row"><span className="fl">査定を見て断る<small>金額に納得できなければ取りやめOK</small></span><span className="fv">無料</span></div>
                <div className="fee-row"><span className="fl">成約・引き取り<small>買取額や条件は事前に明示</small></span><span className="fv">無料</span></div>
              </div>
              {/* 旧 .fee-caution（12.5px の最下部※）は ¥0 直下の .fz-caution へ移設（ラウンド4・20） */}
            </Reveal>
          </div>
        </section>

        {/* ============ 対応カテゴリ ============ */}
        <section className="section" id="cats">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">対応カテゴリ</span>
              <h2>こんな物が対象です</h2>
              <p className="sub">「これって売れる？」のほとんどに対応。迷ったら、まずは撮ってまとめてみてください。</p>
            </div>
            <div className="cats-grid">
              {CATEGORIES.map((c) => (
                <Link href="/create" className="cat" key={c.name}>
                  {/* data-label は画像が読み込めなかったときに枠へ品目名を残すための CSS フォールバック */}
                  <div className="cat-img img-frame img-frame--1x1" data-label={c.name}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/img/real/${c.img}.webp`} alt="" width={512} height={512} loading="lazy" decoding="async" />
                  </div>
                  <div className="cat-body">
                    <div className="cl">{c.name}</div>
                    <div className="cs">{c.ex}</div>
                  </div>
                </Link>
              ))}
            </div>
            <Reveal className="cats-note">
              {/* 56px 枠の 3D レンダーは縮小でにじむため線アイコンへ（ラウンド3 指摘・BRIEF §4-15） */}
              <span className="cn-ic"><Ic name="camera" /></span>
              <div className="cn-body">
                <h4>「売れないかも」と思う物も、まずは撮ってまとめて。</h4>
                <p>点数がそろうと<strong className="mk">まとめて一括買取</strong>の対象になりやすく、単体では値がつきにくい物も一緒に引き取れる場合があります。引き取りが難しい物は、手放す導線をご案内します。</p>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ============ 運営者メッセージ ============ */}
        <section className="section founder" id="founder">
          <div className="container media-split media-split--rev">
            <Reveal as="figure" className="founder-photo img-frame img-frame--3x2 sp-bleed">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/img/v2/top-founder-desk.webp" width={1600} height={1067} alt="" loading="lazy" decoding="async" />
            </Reveal>
            <Reveal className="founder-copy" delay={1}>
              <span className="mb-4 inline-block"><KdzLogo size={20} /></span>
              <span className="eyebrow">私たちについて</span>
              <h2>「片付けたい」を、<br />めんどうで終わらせない。</h2>
              <p>片付けが進まないのは、やる気の問題ではありません。出品の手間、営業電話の不安、何から手をつけるかの迷い。その一つひとつが、最初の一歩を重くしています。</p>
              <p>カタヅケは、それを「撮って待つだけ」に変えるために生まれました。業者が競い、値がつかない物まで引き取り、連絡は選んだ1社だけ。あなたが背負うものを、できる限り減らします。</p>
              <p>カタヅケが目指すのは、顧客と業者を結ぶ、無駄のない場所です。<strong>顧客・業者・社会の三者に喜びと安心を</strong>。それが、カタヅケの根にある考え方です。</p>
              <p className="founder-sign"><span>カタヅケ 運営事務局</span>顧客にも業者にも、社会にも。三方よしの場所をつくります。</p>
            </Reveal>
          </div>
        </section>

        {/* ============ FAQ ============ */}
        <section className="section bg-pale" id="faq">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">よくある質問</span>
              <h2>よくある質問</h2>
            </div>
            <FaqAccordion items={FAQ_ITEMS} />
            <div className="faq-more">
              <Link href="/faq" className="btn btn-ghost btn-lg">すべてのQ&amp;Aを見る<Ic name="arrow" /></Link>
            </div>
          </div>
        </section>

        {/* ============ 最終CTA（写真帯は見出しだけ。ボタンは帯の下の白面） ============ */}
        {/* R4 D.2 #2: 人物入りの帯。縦位置は .hero-band--face（core）。veil は --headline の .55 のまま、
            帯に本文は置かない（白見出しは素材中央の落ち着いた中間調ゾーンに載る） */}
        <section className="hero-band hero-band--mid hero-band--headline hero-band--face" id="contact">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/img/v2/top-cta-band.webp" width={1920} height={1088} alt="" loading="lazy" decoding="async" />
          <div className="hero-band__veil" aria-hidden="true" />
          <div className="container hero-band__copy">
            <h2>今日、その<br className="sp-br" />「片付けたい」を動かす</h2>
          </div>
        </section>
        <section className="final-actions">
          <div className="container">
            {/* ラウンド4（12）: リンク先は自社ログイン画面（/login?callbackUrl=%2Fmypage、
                2026-09-15にユーザー指示で/createから変更）。LINEログイン成功時にbot_prompt
                （auth.ts）で友だち追加の確認画面を挟むようになった。 */}
            <p>まずは1枚、撮ってみることから。LINEアカウントでログインして、マイページから出品をはじめましょう。登録・査定は無料です。</p>
            <div className="final-cta">
              <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line btn-lg">
                <span className="btn-line__tile" aria-hidden="true" />
                <span className="btn-line__body">
                  <span className="btn-line__label">LINEではじめる（無料）</span>
                  <span className="btn-line__sub">LINEアカウントでログインできます</span>
                </span>
                <Ic name="arrow" className="btn-line__arr" />
              </Link>
              <Link href="/#bundle" className="btn btn-ghost btn-lg">もう一度、仕組みを見る</Link>
            </div>
            <p className="final-note">※ 最終的な買取額は業者の現物査定により決まります。</p>
          </div>
        </section>

        {/* ============ 業者向け導線 ============ */}
        <section className="biz-banner">
          <div className="container">
            <div className="biz-banner-inner">
              <div className="biz-banner-copy">
                <span className="eyebrow">買取業者の方へ</span>
                <h2>買取業者の方へ。<br />カタヅケに参加しませんか。</h2>
                <p>顧客と業者、双方に無駄がない。だから長く続く。<br />一括出品への入札で、効率的な仕入れルートを開拓できます。<br />※ サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします。</p>
                {/* ラウンド4（7）: flex-wrap のままだと 5 個の幅が極端に不揃いで、長い β の1本が
                    折返しをぎざぎざにしていた。PC は 2 列の等幅グリッドにし、長い β だけを最後段に
                    全幅で送る（katazuke-top.css）。DOM は短い4本の並び順を保ったまま β を末尾へ移す
                    だけで、文言・条件の意味は変えない。 */}
                <div className="biz-banner-tags">
                  <span className="biz-tag">初期費用・月額費用 無料</span>
                  <span className="biz-tag">成約時8%（税別）のみ</span>
                  <span className="biz-tag">下見なし・一斉架電なし</span>
                  <span className="biz-tag">古物商許可が必要</span>
                  {/* ラウンド5 指摘（21）: 1 案件に何社が入るのかが業者側から読めなかった。
                      数値は出さず、実装済みの仕組み（#auction「複数の業者が、出品した商品すべてに
                      対して買取総額を提示します」）の再掲に留める。2 列グリッドの短いチップを
                      5 個にすると 3 段目に半分の穴が空くため、β と同じ全幅（--wide）で置く。 */}
                  <span className="biz-tag biz-tag--wide">1案件に複数社が入札する仕組み</span>
                  <span className="biz-tag biz-tag--wide">β期間中は手数料0円（期間限定・請求開始は事前にお知らせします）</span>
                </div>
                <div className="biz-banner-cta">
                  <Link href="/business" className="btn btn-white btn-lg">業者登録の詳細を見る<Ic name="arrow" /></Link>
                  <span className="biz-chip">審査制・登録無料</span>
                </div>
              </div>
              {/* data-label は画像が未着・失敗のときに枠を空箱にしないための CSS フォールバック（画像が届けば cover の img が覆う）。
                  alt 文そのままの言い回しだと代替テキストの露出に見えるため、/examples の枠と同じく品名として読める短い名詞にする（ラウンド3 指摘） */}
              <div className="biz-banner-media img-frame img-frame--1x1" data-label="まとめ買取">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/img/v2/biz-reason-bulk.webp" width={800} height={800} alt="" loading="lazy" decoding="async" />
              </div>
            </div>
          </div>
        </section>
        </div>
      </main>
    </>
  );
}
