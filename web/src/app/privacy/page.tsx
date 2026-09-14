import type { Metadata } from "next";
import Link from "next/link";
import "./privacy.css";

export const metadata: Metadata = {
  title: "プライバシーポリシー",
  description:
    "カタヅケ運営事務局が、ユーザーおよび登録業者の個人情報をどのように収集・利用・保護するかを定めたプライバシーポリシーです。",
  alternates: { canonical: "/privacy" },
};

/** 第2条「収集する情報」の表データ。バックエンドの実収集項目
 *  （UserSignupRequest / UserProfileUpdateRequest / CaseCreateRequest /
 *  OperatorSignupRequest / OperatorApplication）と整合させて記載すること。
 *
 *  ラウンド5 指摘（16・モバイル）: 9 行が同じ箱の連続で、本人確認書類・口座情報の箱が
 *  先に目に入るため「これも出さないと使えないのか」と読めていた。行の性質（必須／任意／
 *  自動）を tag として持たせ、カード見出しの右に出す（文言は「収集方法」列と矛盾させない）。
 *  req: 必須（その操作をするなら避けられない）／false: 任意・自動記録。 */
const COLLECTED: { type: string; how: string; detail: string; tag: string; req: boolean }[] = [
  { type: "アカウント情報", how: "会員登録時", detail: "メールアドレス、パスワード、氏名（任意）、LINE連携時はLINEユーザーID", tag: "登録時に必須", req: true },
  { type: "プロフィール情報", how: "マイページでの任意入力", detail: "氏名（姓・名・フリガナ）、電話番号、お住まいのエリア", tag: "任意", req: false },
  { type: "本人確認情報", how: "マイページからの任意提出", detail: "運転免許証・マイナンバーカード等の本人確認書類の画像、生年月日、職業（なりすまし・不正出品の防止、および当社からの本人確認のために利用します。登録業者へ提供することはありません）", tag: "任意", req: false },
  { type: "振込口座情報（ユーザー）", how: "マイページでの任意入力", detail: "銀行名・支店名・預金種別・口座番号・口座名義（暗号化して保存し、ご本人のみが内容を確認できます。登録業者へ自動で開示することはありません）", tag: "任意", req: false },
  { type: "出品情報", how: "出品登録時", detail: "品物の写真（AIが写真から品目・要約を生成）、利用目的、住所（都道府県・市区町村・番地等）、住居情報（住居種別・間取り・階数・エレベーターの有無）", tag: "出品時に必須", req: true },
  { type: "業者情報", how: "業者申込・登録時", detail: "会社名・屋号、代表者名、担当者名、法人登録住所、メールアドレス、パスワード、電話番号、古物商許可番号、事業形態、対応エリア、取扱カテゴリ、インボイス番号、振込先口座（暗号化して保存）、LINE連携時はLINEユーザーID", tag: "業者登録時に必須", req: true },
  { type: "取引情報", how: "取引の過程で", detail: "入札額・入札メッセージ、成約額、訪問日時、チャットの内容、評価・レビュー", tag: "取引の記録", req: false },
  { type: "お問い合わせ情報", how: "お問い合わせフォーム送信時", detail: "お名前、メールアドレス、お問い合わせ種別、お問い合わせ内容（回答のためにのみ利用します）", tag: "送信時に必須", req: true },
  { type: "アクセス情報", how: "自動取得", detail: "IPアドレス、ブラウザ情報、Cookie、閲覧ページ・時間", tag: "自動取得", req: false },
];

/** 本文の目次（ラウンド5 指摘 12）。h2 の id（page.tsx の `pp-N`）と 1:1 で対応させる。 */
const TOC: { id: string; label: string }[] = [
  { id: "pp-1", label: "第1条　基本方針" },
  { id: "pp-2", label: "第2条　収集する情報" },
  { id: "pp-3", label: "第3条　利用目的" },
  { id: "pp-4", label: "第4条　第三者への提供" },
  { id: "pp-5", label: "第5条　安全管理措置" },
  { id: "pp-6", label: "第6条　Cookieの利用" },
  { id: "pp-7", label: "第7条　個人情報の開示・訂正・削除" },
  { id: "pp-8", label: "第8条　プライバシーポリシーの変更" },
  { id: "pp-9", label: "第9条　お問い合わせ" },
];

export default function PrivacyPage() {
  return (
    <main id="main">
      {/* 法務3ページ共通の無文字帯（高さ固定・文字は置かない）。
          R6 指摘 1/2/5/11/17: 修飾子はこの1組（--fixed --quiet）を /terms・/legal と共有する
          （以前 /terms に付いていた --pos-l、/legal に付いていた --pos-r は削除済み）。
          縦位置と高さは core の .hero-band--fixed（--band-pos:50% 53% / 186px・SP 120px）
          1本だけが持ち、ページ CSS では --band-pos も帯高も上書きしない（R4 D.1/F.0）。 */}
      <section className="hero-band hero-band--fixed hero-band--quiet">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/img/v2/lg-band.webp"
          width="1920"
          height="1080"
          alt=""
          loading="lazy"
          decoding="async"
        />
        <div className="hero-band__veil" aria-hidden="true" />
      </section>

      <section className="legal-head">
        <div className="legal-head__inner">
          <span className="legal-head__en">PRIVACY</span>
          <h1>プライバシーポリシー</h1>
          <p className="legal-head__meta">
            制定・施行：2026年4月1日　最終改定：2026年9月4日
          </p>
        </div>
      </section>

      {/* privacy-body: terms.css も同名の .legal-body を定義しており、クライアント遷移で
          両方の CSS が同居する。v2 で変えた条見出し・表の規則だけは特異度で確実に勝たせる。 */}
      <div className="legal-body privacy-body">
        {/* 戻り導線は本文末尾（.legal-foot）に置く。第1条の直前に挟むと本文の流れを
            断ち切るため（r1 レビュー）。/terms も同じ位置に揃えてある。 */}
        {/* 目次（ラウンド5 指摘 12）: 9 条の長文に読み進めの手がかりが無く、帯 → 見出し →
            本文が一続きで「どこに何が書いてあるか」が分からなかった。/terms・/legal にも
            同じ構え（--ui の小さな字面・囲みは上下 1px の罫だけ）で置く。 */}
        <nav className="pp-toc" aria-label="このページの目次">
          <p className="pp-toc__label">このページの内容</p>
          <ol className="pp-toc__list">
            {TOC.map((t) => (
              <li key={t.id}>
                <a href={`#${t.id}`}>{t.label}</a>
              </li>
            ))}
          </ol>
        </nav>

        <h2 id="pp-1">第1条　基本方針</h2>
        <p>
          カタヅケ運営事務局（以下「当社」）は、ユーザーおよび登録業者（以下総称して「利用者」）の個人情報の保護を重要な責務と捉え、個人情報の保護に関する法律（以下「個人情報保護法」）その他の関連法令を遵守し、適切な取り扱いに努めます。
        </p>

        <h2 id="pp-2">第2条　収集する情報</h2>
        <p>当社は、サービス提供のため以下の情報を収集します。</p>
        {/* ラウンド5 指摘（16）: 本人確認書類・口座情報の箱が先に目に入り、「業者にどこまで
            渡るのか」が 2 画面あと（第4条の注記）まで分からなかった。第4条・利用規約 第5条の
            範囲をそのまま1行に要約する（範囲を広げて書かない）。 */}
        <p className="pp-lead">
          <strong>業者に渡る情報は限られています。</strong>
          査定段階で入札業者に見えるのは、写真・品目・利用目的・地域（都道府県・市区町村）・住居情報だけです。詳細住所（番地・建物名など）と連絡用のメールアドレスは、交渉が成立した1社にのみ開示され、氏名・電話番号は業者に渡りません（
          <a href="#pp-4">第4条</a>）。
        </p>
        {/* 859px 以下ではカード積みに切り替える（privacy.css）。display:block で
            失われる表のセマンティクスは明示 role で維持する。data-label が
            カード時の項目名になるため、th の文言と一致させること。 */}
        <table role="table" className="collect-table">
          <thead role="rowgroup">
            <tr role="row">
              <th role="columnheader" scope="col">情報の種類</th>
              <th role="columnheader" scope="col">収集方法</th>
              <th role="columnheader" scope="col">具体的な内容</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {COLLECTED.map((row) => (
              <tr role="row" key={row.type}>
                <td role="cell" data-label="情報の種類" className="collect-type">
                  {row.type}
                  <span className={`pp-tag${row.req ? " pp-tag--req" : ""}`}>{row.tag}</span>
                </td>
                <td role="cell" data-label="収集方法">{row.how}</td>
                <td role="cell" data-label="具体的な内容">{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h2 id="pp-3">第3条　利用目的</h2>
        <p>収集した個人情報は以下の目的で利用します。</p>
        <ul>
          <li>カタヅケサービスの提供・運営・改善</li>
          <li>ユーザーと登録業者とのマッチング処理</li>
          <li>入札状況・成約情報等の通知</li>
          <li>カスタマーサポートへの対応</li>
          <li>なりすまし・不正出品の防止、および当社からの本人確認</li>
          <li>不正利用・規約違反の調査・対処</li>
          <li>法令に基づく対応・開示</li>
        </ul>

        <h2 id="pp-4">第4条　第三者への提供</h2>
        <p>当社は、以下の場合を除き、利用者の個人情報を第三者に提供しません。</p>
        <ul>
          <li>利用者本人の同意がある場合</li>
          <li>取引の成立に際し、相手方（業者またはユーザー）への開示が必要な場合</li>
          <li>法令に基づき開示が義務付けられている場合</li>
          <li>人命・財産保護のために緊急の必要がある場合</li>
        </ul>
        <div className="note">
          <strong>査定段階での情報開示について：</strong>
          査定段階で入札業者に提供されるのは、写真・品目・利用目的・地域（都道府県・市区町村）・住居情報（住居種別・間取り・階数・エレベーターの有無）と、これらに基づくAI要約です。ユーザーの詳細住所（番地・建物名など）と連絡用のメールアドレス（LINE連携のみの場合はLINEでの連絡のご案内）は、交渉が成立した業者にのみ開示され、それ以外の業者には一切渡りません。氏名・電話番号を業者に提供することはありません。なお、古物営業法により、1万円以上の買取など法令で定める場合には、買取業者が住所・氏名・職業・年齢を確認するため、訪問時に業者から身分証のご提示を求められることがあります。
        </div>

        <h2 id="pp-5">第5条　安全管理措置</h2>
        <p>当社は、個人情報の漏洩・滅失・毀損を防ぐため、以下の措置を講じます。</p>
        <ul>
          <li>SSL/TLSによる通信の暗号化</li>
          <li>アクセス権限の管理・制御</li>
          <li>定期的なセキュリティ監査</li>
          <li>従業員への個人情報保護教育</li>
        </ul>

        <h2 id="pp-6">第6条　Cookieの利用</h2>
        <p>
          当社のウェブサイトはCookieを使用しています。Cookieはブラウザの設定から無効にできますが、一部機能が利用できなくなる場合があります。
        </p>

        <h2 id="pp-7">第7条　個人情報の開示・訂正・削除</h2>
        <p>
          利用者は、当社が保有する自己の個人情報について、開示・訂正・利用停止・削除を請求できます。請求はお問い合わせページよりご連絡ください。本人確認のうえ、合理的な期間内に対応します。
        </p>
        <p>
          ご本人からの削除のお申し出があった場合、または退会された場合、当社が保有する個人情報（本人確認書類の画像・振込口座情報を含みます）は、法令上保存が必要な期間を除き、遅滞なく削除します。
        </p>

        <h2 id="pp-8">第8条　プライバシーポリシーの変更</h2>
        <p>
          本ポリシーは、法令の改正やサービス変更に伴い改定することがあります。重要な変更については、ウェブサイト上でお知らせします。
        </p>

        <h2 id="pp-9">第9条　お問い合わせ</h2>
        <p>
          本ポリシーに関するお問い合わせは、
          <Link href="/contact" className="contact-link">
            お問い合わせページ
          </Link>
          よりご連絡ください。
        </p>
        <p className="footer-note">
          カタヅケ運営事務局
          <br />
          神奈川県横浜市（詳細な住所は、請求があれば遅滞なく開示します）
        </p>

        <div className="legal-foot">
          <Link href="/" className="back-link">
            ← トップへ戻る
          </Link>
        </div>
      </div>
    </main>
  );
}
