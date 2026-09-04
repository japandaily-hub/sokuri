/**
 * 特定商取引法に基づく表記（/legal）
 *
 * デザイン正典 docs/design_handoff_katazuke/特定商取引法.html をベースに実装。
 * 共通ヘッダー/フッターは SiteChrome がグローバルに付与するため、本ページは
 * <main id="main"> の中身（doc-wrap）だけを描く。
 *
 * 運営主体は個人事業主。事業者名（カタヅケ運営事務局）・所在地（神奈川県横浜市）・
 * 連絡先メール（katazuke.info@gmail.com）は確定値を記載。代表者名・詳細住所（番地）・
 * 電話番号は特商法第11条施行規則に基づく「請求があれば遅滞なく開示」の省略運用とする。
 * 古物商許可は申請中・未取得のため、許可番号は取得後に追記する（現時点では非掲載）。
 */
import Link from "next/link";
import "./legal.css";

export const metadata = {
  title: "特定商取引法に基づく表記",
  description:
    "カタヅケの特定商取引法に基づく表記。運営者情報・サービス内容・料金・返品等について記載しています。",
};

export default function LegalPage() {
  return (
    <main id="main">
      <div className="doc-wrap">
        <div className="doc-eyebrow">LEGAL</div>
        <h1 className="doc-title">特定商取引法に基づく表記</h1>
        <div className="doc-meta">最終更新：2026年6月1日</div>

        <p className="doc-lead">
          本ページは、特定商取引に関する法律（特定商取引法）第11条および第58条の2に基づき、本サービスの運営者情報および取引条件を表示するものです。
        </p>

        {/* 運営者情報 */}
        <h2 className="doc-section-title">サービス運営者情報</h2>
        <table className="spec-table">
          <tbody>
            <tr>
              <th>事業者名</th>
              <td>カタヅケ運営事務局</td>
            </tr>
            <tr>
              <th>代表者名</th>
              <td>請求があれば遅滞なく開示します</td>
            </tr>
            <tr>
              <th>所在地</th>
              <td>
                神奈川県横浜市
                <br />
                <span className="note">
                  ※ 詳細な住所（番地等）は、請求があれば遅滞なく開示します。
                </span>
              </td>
            </tr>
            <tr>
              <th>電話番号</th>
              <td>
                請求があれば遅滞なく開示します
                <br />
                <span className="note">
                  ※ メールでの対応を原則としています。お問い合わせは
                  <Link href="/contact">お問い合わせフォーム</Link>
                  または下記メールアドレスをご利用ください。
                </span>
              </td>
            </tr>
            <tr>
              <th>メールアドレス</th>
              <td>
                <a href="mailto:katazuke.info@gmail.com">katazuke.info@gmail.com</a>
                <br />
                <span className="note">
                  ※ <Link href="/contact">お問い合わせフォーム</Link>もご利用いただけます。
                </span>
              </td>
            </tr>
          </tbody>
        </table>

        {/* サービス内容 */}
        <h2 className="doc-section-title">サービス内容・取引条件</h2>
        <table className="spec-table">
          <tbody>
            <tr>
              <th>サービス名</th>
              <td>カタヅケ（家まるごと不用品まとめ買取マッチングサービス）</td>
            </tr>
            <tr>
              <th>サービスの内容</th>
              <td>
                ユーザーが家庭内の不用品をまとめて出品し、複数の登録買取業者が買取総額で入札するマッチングプラットフォームの提供。当社はマッチングの場を提供するものであり、買取取引の当事者ではありません。
              </td>
            </tr>
            <tr>
              <th>対応エリア</th>
              <td>東京都・千葉県・埼玉県・神奈川県（順次拡大予定）</td>
            </tr>
            <tr>
              <th>ユーザー負担費用</th>
              <td>
                <strong style={{ color: "var(--green)" }}>無料</strong>
                （出品・査定・お断りまで費用は一切かかりません）
                <br />
                <span className="note">
                  ※ 成約に至った場合も、ユーザーへの費用請求はありません。
                </span>
              </td>
            </tr>
            <tr>
              <th>業者手数料</th>
              <td>
                成約時に登録業者が支払う手数料：<strong>買取金額の8%</strong>
                <br />
                <span className="note">
                  ※ 登録・掲載・入札費用は業者も無料です。
                </span>
                <br />
                <span className="note">
                  ※ サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします。
                </span>
              </td>
            </tr>
            <tr>
              <th>入札・査定期間</th>
              <td>
                出品から業者選択までの間（期間の定めはありません）
                <br />
                <span className="note">
                  ※ 入札の受付は、ユーザーが業者を選択した時点で終了します。ユーザーは任意のタイミングで出品を取り下げることもできます。
                </span>
              </td>
            </tr>
            <tr>
              <th>引き取り</th>
              <td>
                成約した登録業者がユーザー指定の場所へ訪問して引き取ります。日程は業者とのチャットで調整します。
              </td>
            </tr>
            <tr>
              <th>支払い方法</th>
              <td>
                業者によって異なります（現金・お振込みなど）。詳細は交渉時に業者へご確認ください。
                <br />
                <span className="note">
                  ※ 当社が買取代金をお預かりしたり、ユーザーへお振込みしたりすることはありません。
                </span>
              </td>
            </tr>
            <tr>
              <th>支払い時期</th>
              <td>
                業者が引き取りを完了した時点で、ユーザーと業者の間で直接精算されます。
              </td>
            </tr>
          </tbody>
        </table>

        {/* 返品・キャンセル */}
        <h2 className="doc-section-title">返品・キャンセルについて</h2>
        <table className="spec-table">
          <tbody>
            <tr>
              <th>出品のキャンセル</th>
              <td>
                業者を選択する前は、ユーザーが任意で出品を取り下げることができます。業者を選択した後のキャンセルは、業者との合意が必要です。
              </td>
            </tr>
            <tr>
              <th>
                クーリング・オフ
                <br />
                （ユーザー）
              </th>
              <td>
                訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があります。クーリング・オフの可否は、品目（家具・家電等は対象外）や契約に至った経緯（ご自身の依頼で業者が訪問した場合は対象外となることがあります）によって異なります。業者から交付される書面をご確認ください。
                <br />
                <span className="note">
                  ※ 当社の定める取引のお取りやめについては
                  <Link href="/terms">利用規約</Link>をご確認ください。
                </span>
              </td>
            </tr>
            <tr>
              <th>
                クーリング・オフ
                <br />
                （業者向け）
              </th>
              <td>
                登録業者は、特定商取引法に基づく法定書面の交付およびクーリング・オフに関する告知の義務を負います。業者がこれを怠った場合、当社は登録を取り消すことがあります。
              </td>
            </tr>
            <tr>
              <th>買取後の返品</th>
              <td>
                成約・引き取り完了後の返品は、業者とユーザーの個別合意によります。当社が関与する取引ではありません。
              </td>
            </tr>
          </tbody>
        </table>

        {/* 個人情報 */}
        <h2 className="doc-section-title">個人情報の取り扱い</h2>
        <table className="spec-table">
          <tbody>
            <tr>
              <th>個人情報の管理</th>
              <td>
                ユーザーの氏名・電話番号・詳細住所（番地・建物名など）は、査定段階では業者に開示されません。ユーザーが選択した業者にのみ、成約後に引き取りに必要な情報（詳細住所・連絡用のメールアドレス）が開示されます。詳細は
                <Link href="/privacy">プライバシーポリシー</Link>をご覧ください。
              </td>
            </tr>
          </tbody>
        </table>

        <div className="doc-warn">
          <strong>ご注意</strong>
          <br />
          本サービスは不用品買取のマッチングプラットフォームであり、当社（カタヅケ運営事務局）は買取取引の当事者ではありません。買取金額・条件・日程等に関するご要望は、交渉相手である登録業者へ直接お問い合わせください。
        </div>

        <div className="doc-nav">
          <Link href="/privacy">プライバシーポリシー</Link>
          <Link href="/terms">利用規約・業者利用規約</Link>
          <Link href="/contact">お問い合わせ</Link>
          <Link href="/">トップページへ戻る</Link>
        </div>
      </div>
    </main>
  );
}
