import type { Metadata } from "next";
import Link from "next/link";
import { RevealLines } from "@/components/kdz/interactions";
import { publicPageMetadata } from "@/lib/seo";
import "./privacy.css";

export const metadata: Metadata = publicPageMetadata({
  path: "/privacy",
  title: "プライバシーポリシー",
  description:
    "カタヅケ運営事務局が、ユーザーおよび登録業者の個人情報をどのように収集・利用・保護するかを定めたプライバシーポリシーです。",
});

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
  // H-7 / L-4: マイページのプロフィール画面（mypage/profile）の必須・任意の表示と一致させる。
  // 必須は姓・名だけ。住所欄は「住所を登録するときは入力」（UserProfileUpdateRequest と住所更新は別）。
  // お住まいのエリア（residence_area）は任意で、住所を保存すると都道府県から自動で決まる。
  { type: "プロフィール情報", how: "マイページでの入力（保存する場合は氏名が必須）", detail: "必須：氏名（姓・名）／住所を登録する場合：郵便番号・都道府県・市区町村・番地（建物名・部屋番号は任意）／任意：フリガナ、電話番号、生年月日、職業、お住まいのエリア（住所を保存すると都道府県から自動で設定されます）", tag: "保存時に一部必須", req: false },
  { type: "本人確認情報", how: "マイページからの任意提出", detail: "運転免許証・マイナンバーカード等の本人確認書類の画像、生年月日、職業（なりすまし・不正出品の防止、および運営者からの本人確認のために利用します。登録業者へ提供することはありません）", tag: "任意", req: false },
  // M-6: 依頼者の口座を業者・運営の画面へ返す API は無い（backend users.py の本人用エンドポイントだけ）。
  { type: "振込口座情報（ユーザー）", how: "マイページでの任意入力", detail: "銀行名・支店名・預金種別・口座番号・口座名義（暗号化して保存し、ご本人のみが内容を確認できます）。口座は、ご本人が業者へお伝えすると決めた場合に限り、ご本人からその相手の業者へお伝えいただくものです。運営が自動で業者へ開示することはありません", tag: "任意", req: false },
  { type: "出品情報", how: "出品登録時", detail: "品物の写真（AIが写真から品目・要約を生成。第5条）、利用目的、住所（都道府県・市区町村・番地等）、住居情報（住居種別・間取り・階数・エレベーターの有無）", tag: "出品時に必須", req: true },
  // H-7 / L-4: 業者申込フォーム（/business・OperatorApplicationCreateRequest）の必須・任意の表示に合わせる。
  // 口座の用途は実装上「申込内容の確認」だけ（精算・返金の処理は実装に無い）ため、第3条にも精算とは書かない。
  { type: "業者申込情報", how: "業者登録のお申し込み時", detail: "必須：会社名・屋号、代表者名、所在地（法人は本店、個人事業主は事業所）、担当者名、メールアドレス、電話番号、事業形態、主な対応エリア、古物商許可番号、振込先口座（暗号化して保存）／任意：取扱カテゴリ、インボイス制度登録番号、ご質問・備考", tag: "申込時に一部必須", req: true },
  // 業者アカウント（OperatorSignupRequest）・許可証画像（backend operator_license.py）・
  // 業者プロフィール（OperatorProfile。退会時に operator_pii_erasure.py が消す項目と同じ）。
  { type: "業者アカウント情報", how: "業者アカウントの作成・審査・プロフィールの入力時", detail: "必須：会社名・屋号、メールアドレス、パスワード、古物商許可番号、古物商許可証の画像（審査のため）／任意：招待コード、業者プロフィール（対応エリア・取扱カテゴリ・得意カテゴリ・スタッフ数・営業時間・紹介文）、LINE連携時はLINEユーザーID", tag: "業者登録時に一部必須", req: true },
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
  { id: "pp-5", label: "第5条　外部サービスの利用と外国にある事業者" },
  { id: "pp-6", label: "第6条　安全管理措置" },
  { id: "pp-7", label: "第7条　Cookieの利用" },
  { id: "pp-8", label: "第8条　個人情報の開示・訂正・削除" },
  { id: "pp-9", label: "第9条　プライバシーポリシーの変更" },
  { id: "pp-10", label: "第10条　お問い合わせ" },
];

/**
 * 第5条「外部サービスの利用」の表データ（C-3）。
 *
 * 実装で実際に呼んでいる外部サービスだけを載せる（2026-10-06 時点の grep 結果）:
 * - Google Gemini: backend/app/services/vision.py・summary.py（写真は Exif 等のメタデータを除いてから送る）
 * - Brevo: backend/app/services/notify.py（api.brevo.com）
 * - LINE: backend/app/services/line_notify.py・endpoints/auth.py（api.line.me）
 * - Render: render.yaml（region: oregon。API サーバーとデータベース）
 * - Vercel: web の配信と web/src/app/api の中継
 * - Cloudflare R2: backend/app/services/storage_backends/r2.py（R2 の設定がある場合だけ使う）。
 *   R2 に置くのは品物の写真だけ。本人確認書類・許可証の画像はデータベースに保存する（M-1）。
 * - 郵便番号検索 zipcloud: web/src/lib/postal-lookup.ts（ブラウザから直接呼ぶ。M-1）
 * - 銀行・支店検索 bank.teraren.com: web/src/lib/bank-lookup.ts（ブラウザから直接呼ぶ。M-1）
 * - 運営向け障害通知の Webhook: backend/app/services/alerts.py（ALERT_WEBHOOK_URL が設定されている場合だけ。
 *   本文は app/core/masking.py の mask_sensitive_in_text を通したエラー文）
 * 事業者名・所在国は各社の公開情報に基づく（zipcloud＝株式会社アイビスの API 利用規約、
 * bank.teraren.com＝同サイトの運営者情報「合同会社テラレン」。2026-10-06 確認）。
 * サービスを足したり外したりしたら、この表も同時に直すこと。ブラウザから直接呼ぶホストは
 * BROWSER_EXTERNAL_HOSTS にも載せる（web/src/lib/external-hosts-guard.test.mts が src 全体の
 * 外部 URL と突き合わせる）。
 * H-1 / M-7: Gemini は無料枠を前提にしており（backend/app/config.py）、送信内容が提供元の製品改善に
 * 使われうるため「委託」とは断定しない。委託・第三者提供の区分と同意の取り方、外国にある第三者への
 * 提供の法的根拠は弁護士の確認前の暫定表記。
 */
const PROCESSORS: { purpose: string; vendor: string; country: string; data: string }[] = [
  { purpose: "AIによる写真の解析（品目・要約の生成）", vendor: "Google LLC（Gemini API）", country: "米国", data: "品物の写真（位置情報などは除去済み）" },
  { purpose: "サーバー・データベースの運用", vendor: "Render Services, Inc.", country: "米国（サーバーの所在地も米国）", data: "本ポリシー第2条の情報全般（保存・処理のため）" },
  { purpose: "ウェブサイトの配信", vendor: "Vercel Inc.", country: "米国", data: "アクセス情報、ウェブサイト経由で送信される入力内容" },
  { purpose: "品物の写真の保存（クラウドストレージを利用する場合）", vendor: "Cloudflare, Inc.（R2）", country: "米国", data: "品物の写真（本人確認書類・許可証の画像はここには保存せず、データベースに保存します）" },
  { purpose: "メールの送信", vendor: "Sendinblue SAS（Brevo）", country: "フランス", data: "送信先のメールアドレス、メールの本文（お知らせの内容）" },
  { purpose: "LINEでのログイン・通知", vendor: "LINEヤフー株式会社", country: "日本", data: "LINEユーザーID、通知の本文（LINE連携をした場合のみ）" },
  { purpose: "郵便番号からの住所の自動入力（お使いのブラウザから直接送信）", vendor: "株式会社アイビス（zipcloud）", country: "日本", data: "入力された郵便番号（ブラウザから直接通信するため、IPアドレスなどの通信情報も先方に届きます）" },
  { purpose: "銀行名・支店名の候補表示（お使いのブラウザから直接送信）", vendor: "合同会社テラレン（銀行くん）", country: "日本", data: "入力中の銀行名・支店名の文字列（口座番号・口座名義は送りません。ブラウザから直接通信するため、IPアドレスなどの通信情報も先方に届きます）" },
  { purpose: "運営者への障害の通知（運営者が通知先を設定している場合のみ）", vendor: "運営者が設定したチャットサービスの Webhook（Slack／Discord 互換）", country: "所在国は確認中", data: "障害の内容を伝えるエラー文（メールアドレスなどは伏せ字にしたもの）" },
];

/* ブラウザから直接呼んでいる外部ホスト（M-1）の一覧。上の PROCESSORS に対応する行があること。
   web/src/lib/external-hosts-guard.test.mts が、この行のホスト名と、src 配下で fetch している外部 URL の
   ホストを突き合わせる（page.tsx は Next のページなので named export は増やさず、コメントで持つ）。
   external-hosts: zipcloud.ibsnet.co.jp bank.teraren.com */

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
            制定・施行：2026年4月1日　最終改定：2026年10月6日
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

        <RevealLines as="h2" mark="under" id="pp-1" lines={["第1条　基本方針"]} />
        <p>
          カタヅケ運営事務局（個人事業。以下「運営者」）は、ユーザーおよび登録業者（以下総称して「利用者」）の個人情報の保護を重要な責務と捉え、個人情報の保護に関する法律（以下「個人情報保護法」）その他の関連法令を遵守し、適切な取り扱いに努めます。
        </p>

        <RevealLines as="h2" mark="under" id="pp-2" lines={["第2条　収集する情報"]} />
        <p>運営者は、サービス提供のため以下の情報を収集します。</p>
        {/* ラウンド5 指摘（16）: 本人確認書類・口座情報の箱が先に目に入り、「業者にどこまで
            渡るのか」が 2 画面あと（第4条の注記）まで分からなかった。第4条・利用規約 第5条の
            範囲をそのまま1行に要約する（範囲を広げて書かない）。 */}
        <p className="pp-lead">
          <strong>業者に渡る情報は限られています。</strong>
          入札の段階で入札業者に見えるのは、写真・品目・利用目的・地域（都道府県・市区町村）・住居情報だけです。詳細住所（番地・建物名など）と連絡用のメールアドレスは、交渉が成立した1社にのみ開示され、カタヅケのサービス上で氏名・電話番号が業者に渡ることはありません。訪問時には、業者が法令に基づき本人確認をする場合があります（
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

        <RevealLines as="h2" mark="under" id="pp-3" lines={["第3条　利用目的"]} />
        <p>収集した個人情報は以下の目的で利用します。</p>
        <ul>
          <li>カタヅケサービスの提供・運営・改善</li>
          <li>ユーザーと登録業者とのマッチング処理</li>
          <li>入札状況・成約情報等の通知</li>
          <li>カスタマーサポートへの対応</li>
          <li>なりすまし・不正出品の防止、および運営者からの本人確認</li>
          {/* H-3: 決済方針が未決のため、運営者が代金を受け取る・送金するとは書かない
              （/legal「お支払い方法は、成約後にご案内します」と揃える）。
              M-6: 口座を業者へ渡す機能は無い（backend users.py の本人用エンドポイントだけ）。第2条・第4条と同じ文にそろえる。 */}
          <li>
            振込口座情報（任意登録）：ご本人が控えとして確認できるようにするため。口座は、ご本人が業者へお伝えすると決めた場合に限り、ご本人からその相手の業者へお伝えいただくものです。運営が自動で業者へ開示することはありません（お支払い方法は成約後にご案内します）
          </li>
          {/* L-4: 業者の振込先口座の精算・返金への利用は実装に無いため書かない（申込内容の確認のみ）。 */}
          <li>業者の審査（お申し込み内容・古物商許可番号・許可証の画像の確認）</li>
          <li>不正利用・規約違反の調査・対処</li>
          <li>法令に基づく対応・開示</li>
        </ul>

        <RevealLines as="h2" mark="under" id="pp-4" lines={["第4条　第三者への提供"]} />
        <p>運営者は、以下の場合を除き、利用者の個人情報を第三者に提供しません。</p>
        <ul>
          <li>利用者本人の同意がある場合</li>
          <li>取引の成立に際し、相手方（業者またはユーザー）への開示が必要な場合</li>
          <li>法令に基づき開示が義務付けられている場合</li>
          <li>人命・財産保護のために緊急の必要がある場合</li>
          {/* H-1: Gemini への写真の送信を「委託」と断定しないため、外部サービスの扱いは第5条に寄せる。 */}
          <li>第5条に記載する外部サービスを、それぞれの目的に必要な範囲で利用する場合（各サービスの扱いは第5条のとおりです）</li>
        </ul>
        <p>
          振込口座情報は、ご本人が業者へお伝えすると決めた場合に限り、ご本人からその相手の業者へお伝えいただくものです。運営が自動で業者へ開示することはありません。
        </p>
        <div className="note">
          <strong>入札の段階での情報開示について：</strong>
          入札の段階で入札業者に提供されるのは、写真・品目・利用目的・地域（都道府県・市区町村）・住居情報（住居種別・間取り・階数・エレベーターの有無）と、これらに基づくAI要約です。ユーザーの詳細住所（番地・建物名など）と連絡用のメールアドレス（LINE連携のみの場合はLINEでの連絡のご案内）は、交渉が成立した業者にのみ開示され、それ以外の業者には一切渡りません。氏名・電話番号を業者に提供することはありません。なお、古物営業法により、1万円以上の買取など法令で定める場合には、買取業者が住所・氏名・職業・年齢を確認するため、訪問時に業者から身分証のご提示を求められることがあります。
        </div>

        {/* C-3: 実装で使っている外部サービスを列挙する（PROCESSORS のコメント参照）。
            外国にある事業者の記載は弁護士の確認前の暫定表記。法令の効果（同意の要否等）は断定しない。 */}
        <RevealLines
          as="h2"
          mark="under"
          id="pp-5"
          lines={["第5条　外部サービスの利用と外国にある事業者"]}
        />
        <p>
          運営者は、サービスの提供に必要な範囲で、以下の外部サービスを利用しています。これらの事業者には、それぞれの目的に必要な情報だけを送ります。
        </p>
        <table role="table" className="collect-table">
          <thead role="rowgroup">
            <tr role="row">
              <th role="columnheader" scope="col">利用目的</th>
              <th role="columnheader" scope="col">事業者（所在国）</th>
              <th role="columnheader" scope="col">送る情報</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {PROCESSORS.map((row) => (
              <tr role="row" key={row.purpose}>
                <td role="cell" data-label="利用目的" className="collect-type">
                  {row.purpose}
                </td>
                <td role="cell" data-label="事業者（所在国）">
                  {row.vendor}（{row.country}）
                </td>
                <td role="cell" data-label="送る情報">{row.data}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {/* H-1 / M-7: Gemini は無料枠を前提にしている（backend/app/config.py）。区分（委託か第三者提供か）・
            同意の取り方・外国にある第三者への提供の根拠は断定せず、暫定表記である旨を残す。 */}
        <div className="note">
          <strong>AIによる写真の解析について：</strong>
          Google LLC（米国）の Gemini API に、品物の写真（位置情報などは除去済み）を送信します。この送信を個人情報の取り扱いの委託と第三者への提供のどちらとして扱うか、および同意の取り方は、弁護士の確認前の暫定表記です。
        </div>
        <div className="note">
          <strong>外国にある事業者について：</strong>
          上記のうち、日本以外の国にある事業者へは、個人情報が外国で保存・処理されます。提供先の国における個人情報の保護に関する制度や、提供先が講じている個人情報の保護のための措置についてお知りになりたい場合は、お問い合わせページからご連絡ください。本条の記載（外国にある事業者への提供の扱いを含みます）は、弁護士の確認前の暫定表記です。
        </div>

        <RevealLines as="h2" mark="under" id="pp-6" lines={["第6条　安全管理措置"]} />
        {/* C-4: 実装している措置だけを書く（していない「定期監査」「従業員教育」は書かない）。
            根拠: 通信＝https 配信／パスワード＝backend/app/core/security.py（scrypt）／
            口座＝backend/app/core/crypto.py（Fernet）／ログ＝backend/app/core/masking.py・app_logging.py／
            書類画像＝本人と運営者の管理画面だけが取得できる専用エンドポイント（operator_license.py・user_identity）。 */}
        <p>運営者は、個人情報の漏洩・滅失・毀損を防ぐため、以下の措置を講じています。</p>
        <ul>
          <li>通信の暗号化（ウェブサイトとサーバーの通信はHTTPSで行います）</li>
          <li>パスワードはそのままの形では保存せず、復元できない形（ハッシュ）に変換して保存します</li>
          <li>振込口座の情報は暗号化して保存します</li>
          <li>本人確認書類・許可証の画像は、ご本人と運営者の管理画面からのみ閲覧できるよう、アクセスを制限しています</li>
          <li>システムの記録（ログ）に残るメールアドレスは、一部を伏せ字にしています</li>
          <li>外部サービスの利用先と所在国を把握し、第5条に記載しています</li>
        </ul>

        <RevealLines as="h2" mark="under" id="pp-7" lines={["第7条　Cookieの利用"]} />
        <p>
          運営者のウェブサイトはCookieを使用しています。Cookieはブラウザの設定から無効にできますが、一部機能が利用できなくなる場合があります。
        </p>

        <RevealLines as="h2" mark="under" id="pp-8" lines={["第8条　個人情報の開示・訂正・削除"]} />
        {/* L-5: 請求の窓口と本人確認の方法を書く。手数料は設定が無いため書かない。
            ログインした状態のフォーム送信は backend がアカウントに紐付ける（contact_messages.user_id）。 */}
        <p>
          利用者は、運営者が保有する自己の個人情報について、開示・訂正・追加・削除・利用停止を請求できます。
        </p>
        <ul>
          <li>
            窓口：
            <Link href="/contact" className="contact-link">
              お問い合わせページ
            </Link>
            の種別「個人情報の取り扱いについて」からお送りください。
          </li>
          <li>
            本人確認：カタヅケにログインした状態でお送りいただくか、ご登録のメールアドレスを入力してお送りください。回答は、ご登録のメールアドレス宛にお送りします。ご登録内容と照らして確認できない場合は、追加で確認をお願いすることがあります。
          </li>
          <li>本人確認ができたのち、合理的な期間内に対応します。</li>
        </ul>

        {/* H-2: 退会時の扱いは実装に合わせる。
            依頼者＝backend users.py _delete_and_anonymize_user（引き取り前の取引があると退会不可）。
            業者＝backend services/operator_pii_erasure.py ＋ operator_profile._delete_and_anonymize_operator
            （進行中の取引があると退会不可・未決の入札は取り下げ）。
            残す記録の保存期間は運営が決める事項のため書かない（実装に無い削除も書かない）。 */}
        <h3>退会されたときの扱い（ユーザー）</h3>
        <p>
          成約後、引き取りが完了していない取引がある間は、退会の手続きができません。退会されると、次の情報を消去します。
        </p>
        <ul>
          <li>氏名・フリガナ、電話番号、生年月日、職業、住所（郵便番号から建物名・部屋番号まで）、お住まいのエリア</li>
          <li>振込口座情報、本人確認書類の画像</li>
          <li>メールアドレス（復元できない内部用の値に置き換えます）、パスワード、LINE連携</li>
          <li>出品の詳細住所（番地・建物名など。引き取りが完了した取引のものを除きます）</li>
          <li>ログインした状態で送られたお問い合わせの、お名前・メールアドレス・内容</li>
        </ul>
        <p>
          次の記録は、取引の相手方である業者の記録でもあるため、取引の整合と紛争への対応のために残します：出品の内容（写真・品目・地域・住居情報）、入札・取引・チャット・評価の記録、引き取りが完了した取引の詳細住所、本人確認書類の審査結果の記録。出品中の案件は、退会の時点で取り下げます。ログインせずに送られたお問い合わせは、ご本人であることを確認したうえで、個別に削除します。
        </p>
        <h3>退会されたときの扱い（登録業者）</h3>
        <p>
          進行中の取引がある間は、退会の手続きができません。退会の時点で、まだ選ばれていない入札は取り下げます。退会されると、次の情報を消去します。
        </p>
        <ul>
          <li>古物商許可証の画像、古物商許可番号、会社名・屋号（「退会済み業者」の表示に置き換えます）</li>
          <li>業者申込の代表者名・所在地・担当者名・メールアドレス・電話番号・振込先口座・インボイス制度登録番号・取扱カテゴリ・対応エリア・ご質問・備考</li>
          <li>業者プロフィールの内容（対応エリア・取扱カテゴリ・得意カテゴリ・スタッフ数・営業時間・紹介文。プロフィールは非公開にします）</li>
          <li>メールアドレス（復元できない内部用の値に置き換えます）、パスワード、LINE連携</li>
        </ul>
        <p>
          成約した取引（完了・取りやめを含みます）、入札、チャット、口コミの記録は、取引の相手方であるユーザーの記録でもあるため、取引の整合と紛争への対応のために残します。
        </p>
        <p>
          退会によらない削除のお申し出は、上記の窓口で承ります。
        </p>

        <RevealLines as="h2" mark="under" id="pp-9" lines={["第9条　プライバシーポリシーの変更"]} />
        <p>
          本ポリシーは、法令の改正やサービス変更に伴い改定することがあります。重要な変更については、ウェブサイト上でお知らせします。
        </p>

        <RevealLines as="h2" mark="under" id="pp-10" lines={["第10条　お問い合わせ"]} />
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
