import Link from "next/link";
import { Ic, type IcName } from "@/components/kdz/Icons";
import "./company.css";

export const metadata = {
  title: "会社概要 | カタヅケ",
  description:
    "カタヅケ（家まるごと・まとめて片付け買取プラットフォーム）の会社概要・ミッション・運営チームのご紹介です。",
};

/** 数字実績（デザインの .numbers-grid） */
const NUMBERS: { val: string; unit?: string; label: string }[] = [
  { val: "12,400", unit: "+", label: "累計出品件数" },
  { val: "4.8", label: "平均評価（5点満点）" },
  { val: "380", unit: "社", label: "登録買取業者数" },
];

/** 会社情報テーブル（デザインの .company-table） */
const COMPANY_ROWS: { th: string; td: React.ReactNode }[] = [
  { th: "会社名", td: "株式会社カタヅケ" },
  { th: "設立", td: "2023年4月" },
  { th: "代表取締役", td: "山村 大輔" },
  {
    th: "所在地",
    td: (
      <>
        〒150-0001
        <br />
        東京都渋谷区神宮前6丁目23-4
        <br />
        JPR神宮前ビル 3F
      </>
    ),
  },
  {
    th: "事業内容",
    td: (
      <>
        不用品買取マッチングプラットフォームの運営
        <br />
        買取業者向けSaaS提供
      </>
    ),
  },
  { th: "資本金", td: "8,000万円" },
  { th: "従業員数", td: "32名（2026年6月現在）" },
  { th: "許認可", td: "古物商許可（東京都公安委員会 第303291234号）" },
  { th: "加盟団体", td: "一般社団法人リユース業協会" },
];

/** 創業チーム（デザインの .team-grid） */
const TEAM: { initial: string; bg: string; name: string; role: string; bio: string }[] = [
  {
    initial: "山",
    bg: "#1f54de",
    name: "山村 大輔",
    role: "代表取締役CEO",
    bio: "元リサイクル業界営業10年。業界の非効率を解消するために創業。",
  },
  {
    initial: "佐",
    bg: "#1f8a5b",
    name: "佐々木 理恵",
    role: "CTO",
    bio: "元メガベンチャーエンジニア。プラットフォーム開発・運営を統括。",
  },
  {
    initial: "田",
    bg: "#9b59b6",
    name: "田中 孝文",
    role: "COO / 業者渉外",
    bio: "元古物商。全国380社との業者ネットワークを構築。",
  },
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

        {/* ============ 数字実績 ============ */}
        <div className="numbers-grid">
          {NUMBERS.map((n) => (
            <div className="number-card" key={n.label}>
              <div className="number-val">
                {n.val}
                {n.unit ? <span className="number-unit">{n.unit}</span> : null}
              </div>
              <div className="number-lbl">{n.label}</div>
            </div>
          ))}
        </div>

        {/* ============ 会社概要テーブル ============ */}
        <div className="about-section">
          <span className="section-badge">COMPANY</span>
          <h2>会社概要</h2>
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

        {/* ============ 創業チーム ============ */}
        <div className="about-section">
          <span className="section-badge">TEAM</span>
          <h2>創業チーム</h2>
          <div className="team-grid">
            {TEAM.map((m) => (
              <div className="team-card" key={m.name}>
                <div className="team-avatar" style={{ background: m.bg }}>
                  {m.initial}
                </div>
                <div className="team-name">{m.name}</div>
                <div className="team-role">{m.role}</div>
                <div className="team-bio">{m.bio}</div>
              </div>
            ))}
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
