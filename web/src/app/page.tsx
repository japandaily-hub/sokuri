import Link from "next/link";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { Reveal, PhImg, FaqAccordion } from "@/components/kdz/interactions";
import { KdzLogo } from "@/components/kdz/Logo";

/** 対応カテゴリ（実画像未投入のためアイコンタイルで表現） */
const CATEGORIES: { icon: IcName; name: string; ex: string }[] = [
  { icon: "sun", name: "生活家電", ex: "冷蔵庫・洗濯機ほか" },
  { icon: "bag", name: "ブランド品", ex: "バッグ・財布" },
  { icon: "sofa", name: "家具", ex: "ソファ・収納" },
  { icon: "camera", name: "カメラ・PC", ex: "一眼・ノートPC" },
  { icon: "clock", name: "時計・宝飾", ex: "腕時計・アクセ" },
  { icon: "box", name: "ゲーム・玩具", ex: "ゲーム機・フィギュア" },
  { icon: "tag", name: "ファッション", ex: "衣類・靴・小物" },
  { icon: "spark", name: "楽器・趣味", ex: "ギター・道具" },
  { icon: "crop", name: "食器・骨董", ex: "食器・茶道具" },
  { icon: "trend", name: "スポーツ", ex: "ゴルフ・アウトドア" },
  { icon: "scale", name: "工具・DIY", ex: "電動工具ほか" },
  { icon: "house", name: "その他いろいろ", ex: "まずは撮ってみる" },
];

const FAQ_ITEMS = [
  { q: "1点だけでも依頼できますか？", a: "はい。ただし、まとめて出すほど業者の買取総額が伸びやすく、値がつかない物も一緒に引き取ってもらいやすくなります。" },
  { q: "値段がつかない物はどうなりますか？", a: "業者は1点ごとではなく“まとめ全体”の金額で入札します。単体では値がつきにくい物も、まとめに含めて引き取ってもらえる場合があります。" },
  { q: "しつこい営業電話は来ますか？", a: "連絡が来るのは査定額の上位3社のみ。他の業者には自動でお断りが入り、一斉架電は起こりません。" },
  { q: "個人情報はどう扱われますか？", a: "査定段階で業者に渡るのは写真と品目のみ。お名前・電話・住所は交渉成立後に開示されます。" },
  { q: "利用にお金はかかりますか？", a: "出品・査定・成約まで、すべて無料です。費用は一切かかりません。" },
  { q: "訪問買取に不安があります", a: "参加するのは古物商許可を確認した登録事業者のみ。訪問買取は特定商取引法によりクーリングオフの対象です。" },
];

const STEPS: { n: string; en: string; icon: IcName; h: string; p: string; img: string }[] = [
  { n: "1", en: "SHOOT", icon: "camera", h: "まとめて撮る", p: "家じゅうの不用品を1点ずつ撮影。写真と品目をまとめて登録するだけで出品完了です。", img: "step-1.png" },
  { n: "2", en: "WAIT", icon: "scan", h: "査定が届く", p: "登録業者が、まとめ全体に買取総額で入札。あなたは待つだけで査定が集まります。", img: "step-2.png" },
  { n: "3", en: "CHOOSE", icon: "scale", h: "上位3社と交渉", p: "金額上位の3社とだけやりとり。条件を比べて、納得の1社を選べます。", img: "step-3.png" },
  { n: "4", en: "DONE", icon: "truck", h: "引き取りに来てもらう", p: "成立した業者がまとめて引き取りに。玄関先で渡すだけで、片付け完了です。", img: "step-4.png" },
];

const SCENES: { tag: string; tagIcon: IcName; h: string; p: string; img: string; icon: IcName }[] = [
  { tag: "断捨離", tagIcon: "spark", h: "暮らしを身軽に", p: "使わない物をまとめて手放し、すっきりした部屋に。1点からでも、まとめてでも。", img: "p-female.png", icon: "spark" },
  { tag: "引越し", tagIcon: "truck", h: "新居に持っていかない物を", p: "荷造りのついでに撮るだけ。運ぶ前にまとめて買取・回収できます。", img: "p-moving.png", icon: "truck" },
  { tag: "実家じまい", tagIcon: "people", h: "家族で、まとめて整理", p: "量が多く判断に迷う実家の整理も、撮ってまとめれば業者がまとめて査定。", img: "p-senior.png", icon: "house" },
  { tag: "遺品整理", tagIcon: "shield", h: "ていねいに、まとめて", p: "値がつかない物も含めてまとめて回収。気持ちの整理も、無理なく進められます。", img: "p-ihin.png", icon: "shield" },
];

const delayOf = (i: number) => ((i % 3 || undefined) as 1 | 2 | undefined);

export default function HomePage() {
  return (
    <>
      <main id="main">
        {/* ============ HERO ============ */}
        <section className="hero" id="top">
          <div className="container hero-grid">
            <div className="hero-copy">
              <span className="hero-eyebrow">
                <span className="dot" />
                家まるごと、まとめて片付け買取
              </span>
              <h1>
                片付けたい。でも、
                <br />
                <span className="hl">動けない</span>あなたへ。
              </h1>
              <p className="hero-sub">
                家じゅうの不用品を、<strong>まとめて撮って待つだけ</strong>。登録業者が“買取総額”で競い合い、値がつかない物もまとめて引き取ります。営業電話に追われることはありません。
              </p>
              <ul className="hero-trust">
                <li><span className="tb"><Ic name="check" /></span>撮るだけ・待つだけ</li>
                <li><span className="tb"><Ic name="check" /></span>まとめるほど高くなりやすい</li>
                <li><span className="tb"><Ic name="check" /></span>値がつかない物も回収</li>
                <li><span className="tb"><Ic name="check" /></span>連絡は上位3社だけ</li>
              </ul>
              <div className="hero-how">
                <div className="hw-step"><span className="hw-n">1</span><Ic name="camera" className="hw-ic" /><span>撮る</span></div>
                <Ic name="arrow" className="hw-arr" />
                <div className="hw-step"><span className="hw-n">2</span><Ic name="trend" className="hw-ic" /><span>業者が競う</span></div>
                <Ic name="arrow" className="hw-arr" />
                <div className="hw-step"><span className="hw-n">3</span><Ic name="crown" className="hw-ic" /><span>上位3社と交渉</span></div>
                <Ic name="arrow" className="hw-arr" />
                <div className="hw-step"><span className="hw-n">4</span><Ic name="truck" className="hw-ic" /><span>引き取り完了</span></div>
              </div>
              <div className="hero-cta">
                <Link href="/create" className="btn btn-line btn-lg">
                  <Ic name="chat" />LINEで無料ではじめる<Ic name="arrow" className="arw" />
                </Link>
                <Link href="/#auction" className="btn btn-ghost btn-lg">仕組みを確認する</Link>
              </div>
            </div>
            <div className="hero-figure">
              <figure className="hero-photo ph-wrap">
                <PhImg src="/img/p-hero.png" alt="自宅のリビングで、家じゅうの不用品をまとめてスマホで撮影する女性" label="p-hero.png" icon="camera" imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </figure>
            </div>
          </div>
        </section>

        {/* ============ 信頼の根拠（帯） ============ */}
        <section className="assure" aria-label="サービスの安心ポイント">
          <div className="container">
            <div className="assure-item"><span className="ai"><Ic name="shield" /></span><span><b>登録事業者のみ</b><span>古物商許可を確認</span></span></div>
            <div className="assure-item"><span className="ai"><Ic name="lock" /></span><span><b>連絡先は成立後に開示</b><span>査定は写真と品目だけ</span></span></div>
            <div className="assure-item"><span className="ai"><Ic name="phone" /></span><span><b>一斉架電なし</b><span>連絡は上位3社だけ</span></span></div>
            <div className="assure-item"><span className="ai"><Ic name="pin" /></span><span><b>東京・千葉・埼玉・神奈川</b><span>順次エリア拡大中</span></span></div>
          </div>
        </section>

        {/* ============ 共感（悩み） ============ */}
        <section className="section empathy">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">YOUR WORRIES</span>
              <h2>片付け、こんな“めんどう”で<br className="sp-br" />止まっていませんか</h2>
              <p className="sub">「家じゅうを片付けたい」気持ちはあるのに、最初の一歩でつまずく。多くの方が、同じところで止まっています。</p>
            </div>
            <div className="emp-grid">
              <Reveal as="article" className="emp-card">
                <div className="emp-photo ph-wrap"><PhImg src="/img/worry-1.png" alt="出品や発送の手間を思って気が重くなる女性" label="worry-1.png" icon="camera" imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} /></div>
                <div className="emp-body"><h3>出品も発送も、正直めんどう</h3><p>撮影・採寸・説明文・梱包・発送・購入者対応。フリマは手間が多く、量が多いほど踏み出せません。</p></div>
              </Reveal>
              <Reveal as="article" className="emp-card" delay={1}>
                <div className="emp-photo ph-wrap"><PhImg src="/img/worry-2.png" alt="一括査定の営業電話が一斉にかかってきて不安な女性" label="worry-2.png" icon="phone" imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} /></div>
                <div className="emp-body"><h3>営業電話が、一斉にかかってくる</h3><p>一括査定に申し込んだ途端、多数の業者から電話が殺到。応対だけで疲れ、結局決めきれません。</p></div>
              </Reveal>
              <Reveal as="article" className="emp-card" delay={2}>
                <div className="emp-photo ph-wrap"><PhImg src="/img/worry-3.png" alt="物の山を前に、何から手をつけるか迷う女性" label="worry-3.png" icon="box" imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} /></div>
                <div className="emp-body"><h3>そもそも、何から手をつければ</h3><p>売れる物・売れない物、仕分けの基準がわからない。家まるごととなると、考えるだけで腰が重くなります。</p></div>
              </Reveal>
            </div>
            <div className="turn"><p>カタヅケなら、その「めんどう」を<span className="accent">まとめて撮るだけ</span>に変えます。</p></div>
          </div>
        </section>

        {/* ============ STEPS（使い方） ============ */}
        <section className="section steps" id="flow">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">HOW IT WORKS</span>
              <h2>あなたがするのは、<br className="sp-br" />「撮る」と「選ぶ」だけ</h2>
              <p className="sub">たった4ステップ。梱包も発送も、価格交渉も要りません。</p>
            </div>
            <div className="steps-grid">
              {STEPS.map((s, i) => (
                <Reveal as="article" className="step" delay={delayOf(i)} key={s.n}>
                  <div className="step-photo ph-wrap"><PhImg src={`/img/${s.img}`} alt={s.h} label={s.img} icon={s.icon} imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} /></div>
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
            <Reveal className="scta-inner">
              <div className="scta-text">
                <strong>まず1枚、撮るだけ。今日から始められます。</strong>
                <span>登録・査定・お断りまですべて無料</span>
              </div>
              <Link href="/create" className="btn btn-line btn-lg">
                <Ic name="chat" />LINEで無料ではじめる<Ic name="arrow" className="arw" />
              </Link>
            </Reveal>
          </div>
        </div>

        {/* ============ BUNDLE ============ */}
        <section className="section bundle" id="bundle">
          <div className="container">
            <div className="bundle-lead">
              <Reveal className="bundle-figure ph-wrap">
                <PhImg src="/img/bundle-3d.png" alt="さまざまな不用品がひとつの箱にまとまり、まとめて1つの価格がつくイメージ" label="bundle-3d.png" icon="box" imgStyle={{ width: "100%", height: "100%", objectFit: "contain" }} />
              </Reveal>
              <Reveal className="bundle-copy" delay={1}>
                <span className="eyebrow">BUNDLE &amp; SELL</span>
                <h2>まとめて出すほど、<span style={{ color: "var(--blue)" }}>有利</span>になる。</h2>
                <p className="lead">カタヅケは“家まるごと”の片付け向け。1点ずつではなく、たまった不用品をまとめて査定に出すほど、買取総額が伸びやすく、値がつかない物まで一緒に手放せます。</p>
              </Reveal>
            </div>
            <div className="bundle-grid">
              <Reveal as="article" className="bundle-c">
                <span className="bc-ic"><Ic name="up" /></span>
                <h3>数が多いほど、総額が伸びやすい</h3>
                <p>業者は「まとめ買い」を望むため、点数が増えるほど買取総額の条件が良くなりやすい。1点ずつ売るより、まとめたほうがお得です。</p>
              </Reveal>
              <Reveal as="article" className="bundle-c key" delay={1}>
                <span className="bc-badge">ここがポイント</span>
                <span className="bc-ic"><Ic name="bag" /></span>
                <h3>値がつかない物も、まとめて回収</h3>
                <p>業者は1点ごとではなく<strong>“まとめ全体”の金額で入札</strong>します。だから単体では値がつきにくい物も、まとめに含めて引き取り。「これは売れないかも」も、一緒に手放せます。</p>
              </Reveal>
              <Reveal as="article" className="bundle-c" delay={2}>
                <span className="bc-ic"><Ic name="camera" /></span>
                <h3>仕分け・分別は不要</h3>
                <p>ジャンルが混ざっていてもOK。家じゅうの「どうしよう」を、思いついた物から撮ってまとめるだけ。あとは業者がまとめて査定します。</p>
              </Reveal>
            </div>
            <p className="bundle-note">※ 引き取りの可否・条件は品物や業者により異なります。一部、引き取りが難しい物は手放す導線をご案内します。</p>
          </div>
        </section>

        {/* ============ AUCTION ============ */}
        <section className="section auction" id="auction">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">HOW THE AUCTION WORKS</span>
              <h2>業者が“買取総額”で競うから、<br className="sp-br" />高くなりやすい。</h2>
              <p className="sub">あなたが出したのは写真だけ。あとは登録業者どうしが、あなたの品物まとめに買取総額で入札し合います。</p>
            </div>
            <div className="auc-grid">
              <Reveal className="auc-figure ph-wrap">
                <PhImg src="/img/bid-3d.png" alt="複数の業者が、まとめた不用品に買取総額を提示して競り合うイメージ" label="bid-3d.png" icon="trend" imgStyle={{ width: "100%", height: "100%", objectFit: "contain" }} />
              </Reveal>
              <ol className="auc-steps">
                <li><span className="an">1</span><div><h4>写真と品目だけが業者に届く</h4><p>あなたの連絡先は伏せたまま。査定に回るのは「写真」と「品目」だけです。</p></div></li>
                <li><span className="an">2</span><div><h4>登録業者が買取総額で入札</h4><p>複数の業者が、まとめ全体に対して金額を提示。競争で総額が引き上げられます。</p></div></li>
                <li><span className="an">3</span><div><h4>連絡が来るのは上位3社だけ</h4><p>金額上位の3社とだけやりとり。それ以外は自動でお断り。営業電話の一斉架電はありません。</p></div></li>
                <li><span className="an">4</span><div><h4>あなたは選んで、引き取りを待つだけ</h4><p>提示を見比べて1社を選択。成立後に連絡先を開示し、引き取り日時を決めます。</p></div></li>
              </ol>
            </div>
            <p className="auc-note">※ 最終的な買取額は業者の現物査定により決まります。</p>
          </div>
        </section>

        {/* ============ HANDOVER ============ */}
        <section className="section">
          <div className="container media-split">
            <Reveal className="media-figure ph-wrap">
              <PhImg src="/img/handover-new.png" alt="玄関先で、業者スタッフがまとめた品物を受け取る様子" label="handover-new.png" icon="truck" imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} />
            </Reveal>
            <Reveal className="media-copy" delay={1}>
              <span className="eyebrow">HANDOVER</span>
              <h2>業者が直接、引き取りに来ます</h2>
              <p className="sub">梱包も発送も、あなたはしなくていい。選んだ業者がまとめて引き取りに来ます。やりとりするのは、交渉が成立した相手とだけです。</p>
              <ul className="mlist">
                <li><span className="ck"><Ic name="check" /></span>梱包も発送も不要。玄関先で引き渡すだけ。</li>
                <li><span className="ck"><Ic name="check" /></span>連絡先が業者に渡るのは、交渉成立後。</li>
                <li><span className="ck"><Ic name="check" /></span>訪問日時は、あなたの都合で選べます。</li>
                <li><span className="ck"><Ic name="check" /></span>大型家具や大量の品も、まとめて相談OK。</li>
              </ul>
            </Reveal>
          </div>
        </section>

        {/* ============ 利用シーン ============ */}
        <section className="section bg-pale">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">USE CASES</span>
              <h2>“家まるごと”の片付けに</h2>
              <p className="sub">まとまった量を手放したいときほど、カタヅケが力を発揮します。</p>
            </div>
            <div className="scenes-grid">
              {SCENES.map((s, i) => (
                <Reveal as="article" className="scene-card" delay={delayOf(i)} key={s.tag}>
                  <div className="scene-img ph-wrap"><PhImg src={`/img/${s.img}`} alt={s.h} label={s.img} icon={s.icon} imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} /></div>
                  <div className="scene-body">
                    <span className="scene-tag"><Ic name={s.tagIcon} />{s.tag}</span>
                    <h3>{s.h}</h3>
                    <p>{s.p}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ============ TRUST ============ */}
        <section className="section" id="trust">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">SAFE &amp; SECURE</span>
              <h2>はじめてでも、安心して任せられる</h2>
              <p className="sub">「知らない業者は不安」を解消するために。カタヅケは、参加する業者とあなたの情報の扱いに、きちんと線を引いています。</p>
            </div>
            <div className="trust-grid">
              <Reveal as="article" className="trust-c">
                <div className="tc-illus ph-wrap"><PhImg src="/img/trust-illus-1.png" alt="登録事業者を審査・確認するイメージ" label="trust-illus-1.png" icon="shield" imgStyle={{ width: "100%", height: "100%", objectFit: "contain", padding: 10 }} /></div>
                <div className="tc-body"><span className="tc-ic"><Ic name="shield" /></span><h3>登録制の事業者のみ</h3><p>査定に参加するのは登録された買取事業者だけ。古物営業に必要な古物商許可を、登録時・取引前に確認します。</p></div>
              </Reveal>
              <Reveal as="article" className="trust-c" delay={1}>
                <div className="tc-illus ph-wrap"><PhImg src="/img/trust-illus-2.png" alt="連絡先は交渉成立後に開示されるイメージ" label="trust-illus-2.png" icon="lock" imgStyle={{ width: "100%", height: "100%", objectFit: "contain", padding: 10 }} /></div>
                <div className="tc-body"><span className="tc-ic"><Ic name="lock" /></span><h3>連絡先は成立後に開示</h3><p>査定段階で業者に渡るのは「写真と品目」のみ。お名前・電話・住所は、交渉が成立するまで開示されません。</p></div>
              </Reveal>
              <Reveal as="article" className="trust-c" delay={2}>
                <div className="tc-illus ph-wrap"><PhImg src="/img/trust-illus-3.png" alt="訪問買取はクーリングオフの対象となるイメージ" label="trust-illus-3.png" icon="check-circle" imgStyle={{ width: "100%", height: "100%", objectFit: "contain", padding: 10 }} /></div>
                <div className="tc-body"><span className="tc-ic"><Ic name="check-circle" /></span><h3>訪問買取はクーリングオフ対象</h3><p>訪問による買取には特定商取引法が適用され、法定書面の交付や8日間のクーリングオフ等の保護を受けられます。</p></div>
              </Reveal>
            </div>
          </div>
        </section>

        {/* ============ 料金 ============ */}
        <section className="section bg-pale" id="fee">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">PRICING</span>
              <h2>費用は、一切かかりません</h2>
              <p className="sub">出品・査定・成約まで、すべて無料です。</p>
            </div>
            <Reveal className="fee-card">
              <div className="fee-head"><h3>出品から成約まで、お金はかかりません</h3><p>出品・査定・お断りまで、すべて無料</p></div>
              <div className="fee-rows">
                <div className="fee-row"><span className="fl">写真・品目の登録<small>まとめて出品するだけ</small></span><span className="fv">無料</span></div>
                <div className="fee-row"><span className="fl">出品・査定<small>業者への出品と入札の受け取り</small></span><span className="fv">無料</span></div>
                <div className="fee-row"><span className="fl">査定を見て断る<small>金額に納得できなければ取りやめOK</small></span><span className="fv">無料</span></div>
                <div className="fee-row"><span className="fl">成約・引き取り<small>買取額や条件は事前に明示</small></span><span className="fv">無料</span></div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ============ 対応カテゴリ ============ */}
        <section className="section" id="cats">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">CATEGORIES</span>
              <h2>こんな物が対象です</h2>
              <p className="sub">「これって売れる？」のほとんどに対応。迷ったら、まずは撮ってまとめてみてください。</p>
            </div>
            <div className="cats-grid">
              {CATEGORIES.map((c) => (
                <Link href="/create" className="cat" key={c.name}>
                  <div className="cat-img" style={{ display: "grid", placeItems: "center" }}>
                    <Ic name={c.icon} style={{ fontSize: 32, color: "var(--blue)", strokeWidth: 1.8 }} />
                  </div>
                  <div className="cat-body">
                    <div className="cl">{c.name}</div>
                    <div className="cs">{c.ex}</div>
                  </div>
                </Link>
              ))}
            </div>
            <Reveal className="cats-note">
              <span className="cn-ic"><Ic name="bag" /></span>
              <div className="cn-body">
                <h4>「売れないかも」と思う物も、まずは撮ってまとめて。</h4>
                <p>点数がそろうと<strong>“まとめて一括買取”</strong>の対象になりやすく、単体では値がつきにくい物も一緒に引き取れる場合があります。引き取りが難しい物は、手放す導線をご案内します。</p>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ============ 運営者メッセージ ============ */}
        <section className="section" id="founder">
          <div className="container founder-grid">
            <Reveal as="figure" className="founder-photo ph-wrap">
              <PhImg src="/img/founder-new.png" alt="カタヅケ運営事務局のスタッフ" label="founder-new.png" icon="people" imgStyle={{ width: "100%", height: "100%", objectFit: "cover" }} />
              <figcaption>カタヅケ運営事務局</figcaption>
            </Reveal>
            <Reveal className="founder-copy" delay={1}>
              <span className="mb-4 inline-block"><KdzLogo size={20} /></span>
              <span className="eyebrow">OUR MISSION</span>
              <h2>「片付けたい」を、<br />めんどうで終わらせない。</h2>
              <p>片付けが進まないのは、やる気の問題ではありません。出品の手間、営業電話の不安、何から手をつけるかの迷い——その一つひとつが、最初の一歩を重くしています。</p>
              <p>カタヅケは、それを「まとめて撮るだけ」に変えるために生まれました。業者が競い、値がつかない物まで引き取り、連絡は上位3社だけ。あなたが背負うものを、できる限り減らします。</p>
              <p>カタヅケが目指すのは、顧客と業者を結ぶ、無駄のない場所です。<strong>顧客・業者・社会の三者に喜びと安心を</strong>——それが、カタヅケの根にある考え方です。</p>
              <p className="founder-sign"><span>カタヅケ 運営事務局</span>顧客にも業者にも、社会にも。三方よしの場所をつくります。</p>
            </Reveal>
          </div>
        </section>

        {/* ============ FAQ ============ */}
        <section className="section bg-pale" id="faq">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">FAQ</span>
              <h2>よくある質問</h2>
            </div>
            <FaqAccordion items={FAQ_ITEMS} />
            <div style={{ textAlign: "center", marginTop: 32 }}>
              <Link href="/faq" className="btn btn-ghost btn-lg">すべてのQ&amp;Aを見る<Ic name="arrow" className="arw" /></Link>
            </div>
          </div>
        </section>

        {/* ============ 最終CTA ============ */}
        <section className="section final" id="contact">
          <div className="container">
            <h2>今日、その「片付けたい」を動かす</h2>
            <p>まずは1枚、撮ってみることから。LINEで友だち追加すれば、すぐに出品をはじめられます。登録・査定は無料です。</p>
            <div className="final-cta">
              <Link href="/create" className="btn btn-line btn-lg"><Ic name="chat" />LINEではじめる<Ic name="arrow" className="arw" /></Link>
              <Link href="/#bundle" className="btn btn-ghost btn-lg">もう一度、仕組みを見る</Link>
            </div>
            <p className="final-note">※ 最終的な買取額は業者の現物査定により決まります。</p>
          </div>
        </section>
      </main>

      {/* ============ 業者向け導線 ============ */}
      <section className="biz-banner">
        <div className="container">
          <div className="biz-banner-inner">
            <div className="biz-banner-copy">
              <span className="eyebrow">FOR BUYERS</span>
              <h2>買取業者の方へ。<br />カタヅケに参加しませんか。</h2>
              <p>顧客と業者、双方に無駄がない。だから長く続く。<br />まとめ出品への入札で、効率的な仕入れルートを開拓できます。</p>
              <div className="biz-banner-tags">
                <span className="biz-tag">初期費用・月額費用 無料</span>
                <span className="biz-tag">成約時8%のみ</span>
                <span className="biz-tag">下見なし・一斉架電なし</span>
                <span className="biz-tag">古物商許可が必要</span>
              </div>
            </div>
            <div className="biz-banner-cta">
              <Link href="/business" className="btn btn-white btn-lg">業者登録の詳細を見る<Ic name="arrow" className="arw" /></Link>
              <span style={{ fontSize: 12, color: "rgba(255,255,255,.45)" }}>審査制・登録無料</span>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
