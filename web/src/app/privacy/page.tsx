import type { Metadata } from "next";
import Link from "next/link";
import "./privacy.css";

export const metadata: Metadata = {
  title: "プライバシーポリシー",
  description:
    "カタヅケ運営事務局が、ユーザーおよび登録業者の個人情報をどのように収集・利用・保護するかを定めたプライバシーポリシーです。",
};

/** 第2条「収集する情報」の表データ。デザインのテーブルをそのまま移植。 */
const COLLECTED: { type: string; how: string; detail: string }[] = [
  { type: "本人確認情報", how: "登録・申し込み時", detail: "氏名、メールアドレス、電話番号、郵便番号、住所" },
  { type: "出品情報", how: "出品登録時", detail: "品物の写真・品目・数量・状態・メモ" },
  { type: "業者情報", how: "業者登録時", detail: "会社名・屋号、代表者名、古物商許可証情報、対応エリア" },
  { type: "取引情報", how: "取引成立時", detail: "入札額、成約額、引き取り日時" },
  { type: "アクセス情報", how: "自動取得", detail: "IPアドレス、ブラウザ情報、Cookie、閲覧ページ・時間" },
];

export default function PrivacyPage() {
  return (
    <main id="main">
      <section className="legal-hero">
        <div className="container">
          <span className="eyebrow">PRIVACY POLICY</span>
          <h1>プライバシーポリシー</h1>
          <p className="updated">制定・施行：2026年4月1日　最終改定：2026年6月25日</p>
        </div>
      </section>

      <div className="legal-body">
        <Link href="/" className="back-link">
          ← トップへ戻る
        </Link>

        <h2>第1条　基本方針</h2>
        <p>
          カタヅケ運営事務局（以下「当社」）は、ユーザーおよび登録業者（以下総称して「利用者」）の個人情報の保護を重要な責務と捉え、個人情報の保護に関する法律（以下「個人情報保護法」）その他の関連法令を遵守し、適切な取り扱いに努めます。
        </p>

        <h2>第2条　収集する情報</h2>
        <p>当社は、サービス提供のため以下の情報を収集します。</p>
        <table>
          <thead>
            <tr>
              <th>情報の種類</th>
              <th>収集方法</th>
              <th>具体的な内容</th>
            </tr>
          </thead>
          <tbody>
            {COLLECTED.map((row) => (
              <tr key={row.type}>
                <td>{row.type}</td>
                <td>{row.how}</td>
                <td>{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h2>第3条　利用目的</h2>
        <p>収集した個人情報は以下の目的で利用します。</p>
        <ul>
          <li>カタヅケサービスの提供・運営・改善</li>
          <li>ユーザーと登録業者とのマッチング処理</li>
          <li>入札状況・成約情報等の通知</li>
          <li>カスタマーサポートへの対応</li>
          <li>不正利用・規約違反の調査・対処</li>
          <li>法令に基づく対応・開示</li>
        </ul>

        <h2>第4条　第三者への提供</h2>
        <p>当社は、以下の場合を除き、利用者の個人情報を第三者に提供しません。</p>
        <ul>
          <li>利用者本人の同意がある場合</li>
          <li>取引の成立に際し、相手方（業者またはユーザー）への開示が必要な場合</li>
          <li>法令に基づき開示が義務付けられている場合</li>
          <li>人命・財産保護のために緊急の必要がある場合</li>
        </ul>
        <div className="note">
          <strong>査定段階での情報開示について：</strong>
          出品情報（写真・品目）は入札業者に提供されますが、ユーザーの氏名・電話番号・住所は、交渉が成立した業者にのみ開示されます。それ以外の業者には一切渡りません。
        </div>

        <h2>第5条　安全管理措置</h2>
        <p>当社は、個人情報の漏洩・滅失・毀損を防ぐため、以下の措置を講じます。</p>
        <ul>
          <li>SSL/TLSによる通信の暗号化</li>
          <li>アクセス権限の管理・制御</li>
          <li>定期的なセキュリティ監査</li>
          <li>従業員への個人情報保護教育</li>
        </ul>

        <h2>第6条　Cookieの利用</h2>
        <p>
          当社のウェブサイトはCookieを使用しています。Cookieはブラウザの設定から無効にできますが、一部機能が利用できなくなる場合があります。
        </p>

        <h2>第7条　個人情報の開示・訂正・削除</h2>
        <p>
          利用者は、当社が保有する自己の個人情報について、開示・訂正・利用停止・削除を請求できます。請求はお問い合わせページよりご連絡ください。本人確認のうえ、合理的な期間内に対応します。
        </p>

        <h2>第8条　プライバシーポリシーの変更</h2>
        <p>
          本ポリシーは、法令の改正やサービス変更に伴い改定することがあります。重要な変更については、ウェブサイト上でお知らせします。
        </p>

        <h2>第9条　お問い合わせ</h2>
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
          東京都（詳細住所は登録業者・成約ユーザーにのみ開示）
        </p>
      </div>
    </main>
  );
}
