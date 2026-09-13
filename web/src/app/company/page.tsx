/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import "./company.css";

export const metadata = {
  title: "運営者情報",
  description:
    "カタヅケ（家まるごと・まとめて片付け買取プラットフォーム）の運営者情報・ミッションのご紹介です。",
  alternates: { canonical: "/company" },
};

/**
 * 運営者情報テーブル（デザインの .company-table）
 *
 * 運営主体は個人事業主（事業者名「カタヅケ運営事務局」）。法人前提の項目
 * （資本金・従業員数・設立登記・加盟団体）、未取得の古物商許可番号、実績のない数字・
 * 架空の創業チームは、虚偽表示を避けるため掲載しない。代表者名・電話番号など
 * 特商法上の開示事項は /legal（特定商取引法に基づく表記）側で扱う。
 */
const COMPANY_ROWS: { th: string; td: React.ReactNode }[] = [
  { th: "事業者名", td: "カタヅケ運営事務局" },
  { th: "所在地", td: "神奈川県横浜市" },
  {
    th: "お問い合わせ",
    td: <a href="mailto:katazuke.info@gmail.com">katazuke.info@gmail.com</a>,
  },
  { th: "事業内容", td: "不用品買取マッチングプラットフォームの運営" },
];

/**
 * 私たちが大切にすること（デザインの VALUES）。
 * 線アイコンを 3D 静物（/img/v2/co-value-*.webp）に置き換え、各項に
 * 検証できる事実の1文（fact）を添える。実績値・体験談は置かない。
 */
const VALUES: { img: string; title: string; body: string; fact: React.ReactNode }[] = [
  {
    img: "co-value-clear",
    title: "透明性",
    body: "入札価格・手数料・評価情報をユーザーに公開します。納得して判断できる環境を作ります。",
    fact: "ユーザーの費用は0円です。業者から受け取る手数料は、条件とあわせて業者向けページに公開しています。",
  },
  {
    img: "co-value-safe",
    title: "安全・安心",
    body: "古物商許可番号の登録を必須とし、運営が許可証を確認した業者のみが参加します。",
    fact: (
      <>
        買取を行うのは登録業者であり、その古物商許可番号を運営が確認します。トラブルが起きたときは、
        <Link href="/contact">お問い合わせ（トラブル・クレーム）</Link>
        から運営が業者との連絡を仲介します。
      </>
    ),
  },
  {
    img: "co-value-cycle",
    title: "サーキュラーエコノミー",
    body: "まだ使えるものを廃棄ではなく、再流通に回す仕組みにします。",
    fact: "引き取られた品物は、古物商許可を受けた登録業者を通じて中古品として再流通します。",
  },
];

export default function CompanyPage() {
  return (
    <main id="main">
      {/* ============ ヒーロー（写真帯・見出しのみ・LCP） ============ */}
      <section className="hero-band hero-band--tall hero-band--headline co-band">
        <img
          src="/img/v2/co-band.webp"
          width={1920}
          height={1080}
          alt=""
          loading="eager"
          fetchPriority="high"
          decoding="async"
        />
        <div className="hero-band__veil" aria-hidden="true" />
        <div className="container hero-band__copy">
          <h1>
            「片付ける」を、
            <br />
            もっとかんたんに。
          </h1>
        </div>
      </section>

      <div className="about-wrap">
        <p className="about-lead">
          カタヅケは、家の不用品をまとめて出品し、複数の業者の入札を見比べて自分で選べるプラットフォームです。
        </p>

        {/* ============ ミッション（白地＋左罫） ============ */}
        <div className="mission-card">
          <blockquote>
            「不用品を手放すことは、新しい暮らしのはじまり。その最初の一歩を、もっと気軽に、もっと納得できるものにしたい。」
          </blockquote>
          <p>
            引越し・遺品整理・断捨離。それぞれのライフイベントで生まれる不用品には、まだ価値があります。カタヅケは、ユーザーと誠実な買取業者をつなぐことで、その価値を適切に届けます。
          </p>
        </div>

        {/* ============ 運営者情報テーブル（掲載項目は現行のまま） ============
            表の直下に開示請求の導線のみを置く。代表者名・番地・電話番号の扱いは
            /legal（特定商取引法に基づく表記）に既出の事実をそのまま案内するだけで、
            新しい事実・期限・理由は書かない（掲載可否はユーザー確認待ちのため）。 */}
        <div className="about-section">
          <span className="eyebrow">COMPANY</span>
          <h2>運営者情報</h2>
          <div className="company-table-wrap">
            <table className="company-table">
              <tbody>
                {COMPANY_ROWS.map((r) => (
                  <tr key={r.th}>
                    <th>{r.th}</th>
                    <td>{r.td}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="about-disclose">
            代表者名・詳細な住所（番地等）・電話番号は、
            <Link href="/legal">特定商取引法に基づく表記</Link>
            のとおり、ご請求があれば遅滞なく開示します。ご請求は
            <Link href="/contact">お問い合わせ</Link>
            の「事業者情報の開示請求」からお送りください。
          </p>
        </div>

        {/* ============ 私たちが大切にすること ============ */}
        <div className="about-section">
          <span className="eyebrow">VALUES</span>
          <h2>私たちが大切にすること</h2>
          <div className="values-grid">
            {VALUES.map((v) => (
              <div className="value-card" key={v.title}>
                <div className="img-frame img-frame--pale img-frame--1x1 value-img">
                  <img
                    src={`/img/v2/${v.img}.webp`}
                    width={800}
                    height={800}
                    alt=""
                    loading="lazy"
                    decoding="async"
                  />
                </div>
                <strong>{v.title}</strong>
                <p>{v.body}</p>
                <p className="value-fact">{v.fact}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ============ CTA ============ */}
        <div className="about-cta">
          <h3>一緒に、片付けをもっと良くしませんか？</h3>
          <p>業者登録・提携のお問い合わせはこちらから</p>
          <div className="about-cta-btns">
            <Link href="/create" className="btn btn-primary btn-lg">
              出品してみる
            </Link>
            <Link href="/contact" className="btn btn-ghost btn-lg">
              お問い合わせ
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
