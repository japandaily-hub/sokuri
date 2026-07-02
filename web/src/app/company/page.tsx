import Link from "next/link";
import { Ic, type IcName } from "@/components/kdz/Icons";
import "./company.css";

export const metadata = {
  title: "運営者情報 | カタヅケ",
  description:
    "カタヅケ（家まるごと・まとめて片付け買取プラットフォーム）の運営者情報・ミッションのご紹介です。",
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

/** 私たちが大切にすること（デザインの VALUES。絵文字はアイコンに置換） */
const VALUES: { icon: IcName; title: string; body: string }[] = [
  {
    icon: "zoom",
    title: "透明性",
    body: "入札価格・手数料・評価情報をすべて公開。ユーザーが納得して判断できる環境を作ります。",
  },
  {
    icon: "shield",
    title: "安全・安心",
    body: "古物商許可確認・本人確認済みの業者のみ掲載。すべての取引に保証制度を整備。",
  },
  {
    icon: "up",
    title: "サーキュラーエコノミー",
    body: "まだ使えるものを廃棄ではなく再流通へ。環境負荷を減らす経済の循環に貢献します。",
  },
];

export default function CompanyPage() {
  return (
    <main id="main">
      {/* ============ ヒーロー（導入帯） ============ */}
      <div className="about-hero">
        <h1>
          「片付ける」を、
          <br />
          もっとかんたんに。
        </h1>
        <p>
          カタヅケは、家の不用品をまとめて複数の業者に入札してもらい、最高額で手放せるプラットフォームです。
        </p>
      </div>

      <div className="about-wrap">
        {/* ============ ミッション ============ */}
        <div className="mission-card">
          <blockquote>
            「不用品を手放すことは、新しい暮らしのはじまり。その最初の一歩を、もっと気軽に、もっと納得できるものにしたい。」
          </blockquote>
          <p>
            引越し・遺品整理・断捨離。それぞれのライフイベントで生まれる不用品には、まだ価値があります。カタヅケは、ユーザーと誠実な買取業者をつなぐことで、その価値を適切に届けます。
          </p>
        </div>

        {/* ============ 運営者情報テーブル ============ */}
        <div className="about-section">
          <span className="section-badge">COMPANY</span>
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
        </div>

        {/* ============ 私たちが大切にすること ============ */}
        <div className="about-section">
          <span className="section-badge">VALUES</span>
          <h2>私たちが大切にすること</h2>
          <div className="values-grid">
            {VALUES.map((v) => (
              <div className="value-card" key={v.title}>
                <span className="value-ic">
                  <Ic name={v.icon} />
                </span>
                <strong>{v.title}</strong>
                <p>{v.body}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ============ CTA ============ */}
        <div className="about-cta">
          <h3>一緒に、片付けをもっと良くしませんか？</h3>
          <p>採用情報・業者登録・提携のお問い合わせはこちらから</p>
          <div className="about-cta-btns">
            <Link href="/create" className="btn btn-white btn-lg">
              出品してみる
            </Link>
            <Link href="/contact" className="btn btn-outline-white btn-lg">
              お問い合わせ
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
