/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { Reveal, RevealLines } from "@/components/kdz/interactions";
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
  /* 運営形態は /legal（特定商取引法に基づく表記）に既出の「個人で運営しているため…」の再掲。
     許可証と口座を預ける業者側から「法人格・運営体制が読めない」と指摘が出たため、
     /legal にある事実だけを表に上げる（資本金・従業員数・設立年などの法人前提の項目、
     代表者名・稼働状況は実データ／掲載可否がユーザー確認待ちのため追加しない）。 */
  { th: "運営形態", td: "個人事業（法人ではありません）" },
  { th: "所在地", td: "神奈川県横浜市" },
  /* ラウンド5 指摘（14）: 連絡先が gmail のアドレス1行だけだと「メールしか窓口がない」に見え、
     知らない業者を家に呼ぶ判断をする面で不安が最大化する。既存の窓口（/contact のフォーム）を
     同じセルに並記する。返信までの日数などの新しい約束は書かない（実績・運用条件は未確定）。 */
  {
    th: "お問い合わせ",
    td: (
      <>
        <a href="mailto:katazuke.info@gmail.com">katazuke.info@gmail.com</a>
        <span className="company-table__or">
          または<Link href="/contact">お問い合わせフォーム</Link>
        </span>
      </>
    ),
  },
  { th: "事業内容", td: "不用品買取マッチングプラットフォームの運営" },
];

/**
 * 運営者情報テーブルの直前に置く安心の3点（ラウンド5 指摘 14）。
 * 「個人事業・所在地は市まで・代表者名は非掲載・連絡先は gmail」が縦に並ぶ面に安心材料が
 * 同居していないため、トップの .assure 帯と無料表記からの再掲を同じ視野に入れる。
 * 出典: 古物商許可の確認＝VALUES「安全・安心」と /business の登録条件、開示範囲＝
 * /privacy 第4条（詳細住所と連絡用メールは成立した業者にのみ／氏名・電話は提供しない）、
 * 0円＝/ の料金表（出品・査定・お断り・成約すべて無料）。新しい事実・数値は作らない。
 */
const ASSURE: { h: string; p: string }[] = [
  { h: "登録事業者のみ", p: "買取を行うのは登録業者です。その古物商許可は運営が確認します。" },
  {
    h: "連絡先は成立後に開示",
    p: "詳細な住所と連絡用のメールアドレスが渡るのは、成立した1社だけです。氏名・電話番号は業者に渡りません。",
  },
  { h: "出品・査定・お断りまで0円", p: "ユーザーの費用はかかりません。" },
];

/**
 * 業者の方へ：お預かりする情報の扱い（ラウンド5 指摘 18）。
 * 業者側には古物商許可証のコピーと振込先口座を求めるのに、運営側は個人事業・代表者名非掲載で
 * 情報の非対称が大きく、登録の最後で止まる、という指摘。既出の事実の再掲とリンクだけで埋める。
 * 出典: 許可証のコピー＝/business の登録条件、暗号化保存＝/privacy 第2条（業者情報）、
 * 削除＝/privacy 第8条、窓口＝/contact の種別「業者登録・提携について」。
 * 保管期間・無償期間・返信日数など、現時点で確定していない約束は書かない。
 */
const VENDOR_NOTES: { h: string; p: React.ReactNode }[] = [
  {
    h: "古物商許可証のコピー",
    p: (
      <>
        登録時にご提出いただき、古物営業法に基づく許可を運営が確認するために使います。登録条件は
        <Link href="/business">業者向けページ</Link>に掲載しています。
      </>
    ),
  },
  {
    h: "振込先口座",
    p: (
      <>
        ご登録いただいた振込先口座は暗号化して保存します。取り扱いは
        <Link href="/privacy">プライバシーポリシー</Link>のとおりです。
      </>
    ),
  },
  {
    h: "退会・削除のお申し出",
    p: "お申し出があった場合、当方が保有する個人情報（本人確認書類の画像・振込口座情報を含みます）は、法令上保存が必要な期間を除き、遅滞なく削除します。",
  },
  {
    h: "業者からのお問い合わせ",
    p: (
      <>
        <Link href="/contact">お問い合わせ</Link>
        の種別「業者登録・提携について」からお送りください。
      </>
    ),
  },
];

/**
 * 私たちが大切にすること（デザインの VALUES）。
 * 線アイコンを 3D 静物（/img/v2/co-value-*.webp）に置き換え、各項に
 * 検証できる事実の1文（fact）を添える。実績値・体験談は置かない。
 */
const VALUES: { img: string; w: number; title: string; body: string; fact: React.ReactNode }[] = [
  {
    img: "co-value-clear",
    w: 520,
    title: "透明性",
    body: "入札価格・手数料・評価情報をユーザーに公開します。納得して判断できる環境を作ります。",
    fact: "ユーザーの費用は0円です。業者から受け取る手数料は、条件とあわせて業者向けページに公開しています。",
  },
  {
    /* ラウンド5 指摘（2/12/16/19）: 旧 co-value-safe は「青いリボンを掛けた白い箱に金色の鍵」で、
       贈り物にしか見えず「古物商許可証を運営が確認する」という下の1文とつながらなかった。
       R4 D.1 により画像の再生成はしないため、同じ 1:1 で既に検査を通った現場の静物
       biz-req-docs（窓光の机に書類一式と印鑑箱・背後にファイル棚）を再利用する。
       ルート跨ぎの再利用は既存の biz-reason-bulk（/business と / の業者バナー）と同じ作法。
       残り2点（透明性・循環）の比喩オブジェクトは 1:1 の代替が v2 に無いため画像担当に残す。 */
    img: "biz-req-docs",
    w: 800,
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
    w: 520,
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
          height={1088}
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
          {/* 署名。運営者メッセージの書き手を明示する（ラウンド4 指摘: 誰が運営しているのか分からない）。
              記載は運営者情報テーブルと同一の確定値のみで、代表者名・肩書は /legal のとおり
              請求時開示のため書かない。人物写真は置かない（CONSTRAINTS §3・R4 D の維持項目）。 */}
          <p className="mission-sign">カタヅケ運営事務局</p>
        </div>

        {/* ============ 運営者情報テーブル（掲載項目は現行のまま） ============
            表の直下に開示請求の導線のみを置く。代表者名・番地・電話番号の扱いは
            /legal（特定商取引法に基づく表記）に既出の事実をそのまま案内するだけで、
            新しい事実・期限・理由は書かない（掲載可否はユーザー確認待ちのため）。 */}
        <div className="about-section">
          <span className="eyebrow">COMPANY</span>
          <h2>運営者情報</h2>
          {/* 表の直前に安心の3点（再掲）。掲載できない項目が縦に並ぶ面と同じ視野に置く */}
          <ul className="co-assure" aria-label="ご利用にあたっての安心の3点">
            {ASSURE.map((a) => (
              <li key={a.h}>
                <b>{a.h}</b>
                <span>{a.p}</span>
              </li>
            ))}
          </ul>
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
            個人で運営しているため、代表者名・詳細な住所（番地等）・電話番号は常時掲載していません。
            <Link href="/legal">特定商取引法に基づく表記</Link>
            のとおり、ご請求があれば遅滞なく開示します。ご請求は
            <Link href="/contact">お問い合わせ</Link>
            の「事業者情報の開示請求」からお送りください。
          </p>
        </div>

        {/* ============ 業者の方へ：お預かりする情報の扱い（既出の事実の再掲） ============ */}
        <div className="about-section">
          <span className="eyebrow">FOR VENDORS</span>
          <h2>業者の方へ：お預かりする情報の扱い</h2>
          <p className="co-vendor-lead">
            ご登録の際にお預かりする書類と口座情報の扱いを、業者向けページとプライバシーポリシーから再掲します。
          </p>
          <ul className="co-vendor">
            {VENDOR_NOTES.map((v) => (
              <li key={v.h}>
                <b>{v.h}</b>
                <span>{v.p}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* ============ 私たちが大切にすること ============ */}
        <div className="about-section">
          <span className="eyebrow">VALUES</span>
          <RevealLines mark="under" lines={["私たちが大切にすること"]} />
          <div className="values-grid">
            {VALUES.map((v, i) => (
              <Reveal as="div" className="value-card" stagger={i} key={v.title}>
                <Reveal as="figure" variant="zoom" className="img-frame img-frame--pale img-frame--1x1 value-img" stagger={i}>
                  <img
                    src={`/img/v2/${v.img}.webp`}
                    width={v.w}
                    height={v.w}
                    alt=""
                    loading="lazy"
                    decoding="async"
                  />
                </Reveal>
                <strong>{v.title}</strong>
                <p>{v.body}</p>
                <p className="value-fact">{v.fact}</p>
              </Reveal>
            ))}
          </div>
        </div>

        {/* ============ CTA ============
            ラウンド6 指摘（12）: 補足が「業者登録・提携のお問い合わせはこちらから」の1文なのに
            主ボタンは依頼者向けの「出品してみる」で、依頼者・業者のどちらが押すボタンなのか
            判別できなかった。補足を2文に分け、どの文がどのボタンに対応するかを名指しする。
            ラウンド6 指摘（13）は主ボタンを「業者登録を申し込む」に差し替える案だが採らない:
            この CTA の直上は VALUES 節（FOR VENDORS 節はその手前）で、/company は依頼者も読む面。
            依頼者の出口を消すのではなく、宛先の対応を明示して受け手の入れ替わりを解消する。 */}
        <div className="about-cta">
          <h3>一緒に、片付けをもっと良くしませんか？</h3>
          <p>
            売りたい方は「出品してみる」からお進みください。業者登録・提携のご相談は「お問い合わせ」からお送りください。
          </p>
          <div className="about-cta-btns">
            <Link href="/create" className="btn btn-primary btn-lg">
              出品してみる
            </Link>
            <Link href="/contact" className="btn btn-ghost btn-lg btn-swipe">
              お問い合わせ
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
