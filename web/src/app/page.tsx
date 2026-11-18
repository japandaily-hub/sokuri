/* eslint-disable @next/next/no-img-element */
import type { Metadata } from "next";
import Link from "next/link";
import "./top.css";

/** 2026-09-18 本採用のトップ。title・description・canonical は検索結果に出ているため変えない。 */
export const metadata: Metadata = {
  title: "カタヅケ｜家まるごと、まとめて片付け買取",
  description:
    "家じゅうの不用品を、1点ずつ撮って、あとは待つだけ。登録業者が買取総額で入札し、連絡が来るのはあなたが選んだ1社だけ。営業電話に追われない、家まるごとの片付け買取マッチング。",
  alternates: { canonical: "/" },
};

/**
 * 2026-11-19 見本 v12 へ作り直し（計画 C4）。
 * - 構成: ヒーロー → 営業電話が来ない理由（#trust）→ 使い方（#daily）→ 料金（#fee）→ 運営者（#founder）。
 * - ヘッダー・フッター・Dock は SiteChrome が描く。ここは <main> だけ。
 * - 業者向け区画・モデルケース区画は置かない（フッターの /examples・/business と、使い方の本文内リンクで足りる）。
 * - 運営者の値は company/page.tsx の COMPANY_ROWS と一致させる（変えるときは両方）。
 */

/** LINE ログイン後の着地先は /mypage（chrome.tsx の Dock・SiteHeader と同じ）。 */
const LINE_HREF = "/login?callbackUrl=%2Fmypage";
const EMAIL_SIGNUP_HREF = "/signup";

/**
 * LINE ボタン。アイコンは置かない（緑地＋白吹き出しは LINE アプリの模倣になるため。katazuke.css の方針）。
 * 見た目は .btn-line（katazuke.css）が担う。
 */
function LineButton() {
  return (
    <Link href={LINE_HREF} className="btn btn-line">
      <span className="btn-line__body">
        <span className="btn-line__label">LINEではじめる（無料）</span>
        <span className="btn-line__sub">規約に同意のうえ登録・ログイン</span>
      </span>
    </Link>
  );
}

/** ヒーロー下の3つの事実。 */
const FACTS: { dt: string; dd: React.ReactNode }[] = [
  { dt: "業者からの営業電話", dd: "選ぶまで、来ません" },
  {
    dt: "業者に伝わる連絡先",
    dd: (
      <>
        住所とメールだけ。
        <br />
        選んだ1社にのみ
      </>
    ),
  },
  { dt: "対応エリア", dd: "東京・千葉・埼玉・神奈川" },
];

/** 業者に見えるもの（入札中／選んだあと）。事実の出典は privacy 第4条と backend の build_case_masked_out。 */
const WHO_SEES: { what: string; during: { text: string; seen: boolean }; after: { text: string; seen: boolean } }[] = [
  { what: "品物の写真・品目", during: { text: "見える", seen: true }, after: { text: "見える", seen: true } },
  { what: "地域（市区町村まで）", during: { text: "見える", seen: true }, after: { text: "見える", seen: true } },
  {
    what: "住まいの情報（間取り・階数など）",
    during: { text: "見える", seen: true },
    after: { text: "見える", seen: true },
  },
  {
    what: "番地までの住所・メール",
    during: { text: "見えない", seen: false },
    after: { text: "選んだ1社だけ", seen: true },
  },
  { what: "お名前・電話番号", during: { text: "見えない", seen: false }, after: { text: "見えない", seen: false } },
];

/** 料金の行。0円なのはカタヅケの利用料に限る（出張・運搬・処分は下の注記）。 */
const FEE_ROWS = ["出品する", "入札を受け取る", "お断りする", "業者を決める"] as const;

export default function HomePage() {
  return (
    <main id="main" className="tp-main">
      {/* ============ ヒーロー ============ */}
      <section className="tp-hero">
        <div className="tp-wrap">
          <div className="tp-hero-grid">
            <div>
              <p className="label">家まるごと、まとめて買取</p>
              <h1>
                家じゅうの不用品を、
                <br />
                写真でまとめて出品。
                <br />
                買い取る業者は、
                <br />
                金額を見て選べます。
              </h1>
              <p className="tp-lead">
                品物を撮って登録すると、審査を通った買取業者が、品物すべての買取総額で入札します。届いた金額を見比べて、納得できる1社を選んでください。選ぶまで、業者から連絡は来ません。
              </p>
              {/* .hero-cta は Dock の監視対象（画面内にある間は下の追従 CTA を隠す）。外さない */}
              <div className="tp-sub hero-cta">
                <LineButton />
                <Link href={EMAIL_SIGNUP_HREF} className="link">
                  メールアドレスで登録する
                </Link>
              </div>
            </div>
            <div>
              <div className="tp-visual">
                <figure className="tp-photo">
                  {/* LCP 画像。lazy にせず優先度を上げる。スマホ（900px 以下）は別の写真 */}
                  <picture>
                    <source media="(max-width:900px)" srcSet="/img/lp/fee-empty-room.webp" />
                    <img
                      src="/img/lp/register-listing.webp"
                      alt="片付けを進める部屋のイメージ"
                      width={1024}
                      height={1024}
                      fetchPriority="high"
                      decoding="async"
                    />
                  </picture>
                </figure>
                <div className="tp-device" role="img" aria-label="入札が届いたときの画面の例">
                  <div className="tp-screen">
                    <div className="tp-bar">
                      <b>カタヅケ</b>
                      <span>マイページ</span>
                    </div>
                    <div className="tp-ttl">
                      <p>リビングと和室の片付け</p>
                      <h3>
                        届いた入札　<span className="tp-num">3</span>件
                      </h3>
                    </div>
                    <ol className="tp-bids">
                      <li className="tp-top">
                        <span>リユース青葉</span>
                        <b>
                          42,000<small>円</small>
                        </b>
                      </li>
                      <li>
                        <span>ふるどうぐ南町</span>
                        <b>
                          38,500<small>円</small>
                        </b>
                      </li>
                      <li>
                        <span>まるやま商店</span>
                        <b>
                          31,000<small>円</small>
                        </b>
                      </li>
                    </ol>
                    <div className="tp-act">
                      <div>この業者に決める</div>
                    </div>
                  </div>
                </div>
              </div>
              <p className="tp-cap">
                入札が届くと、こう並びます。
                <br />
                （写真はイメージ、業者名・金額は説明用の例です）
              </p>
            </div>
          </div>
          <dl className="tp-facts">
            {FACTS.map((f) => (
              <div key={f.dt}>
                <dt>{f.dt}</dt>
                <dd>{f.dd}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* ============ 営業電話が来ない理由 ============ */}
      <section id="trust" className="tp-sec tp-promise-sec">
        <div className="tp-wrap">
          <div className="sec-head">
            <div>
              <p className="label">営業電話が来ない理由</p>
              <h2>
                選ぶまで、業者は
                <br />
                あなたの連絡先を知りません。
              </h2>
            </div>
            <p>
              一括見積もりに申し込んだら電話が鳴りやまなかった、という話をよく聞きます。カタヅケで業者が入札のときに見られるのは、品物の写真と、市区町村までの地域などの情報だけです。だから、電話のかけようがありません。
            </p>
          </div>
          <ol className="tp-promise">
            <li>
              <h3>連絡先は、選んだ1社にだけ</h3>
              <p>
                あなたが1社を選んで交渉が成立したとき、はじめて住所とご登録のメールアドレスがその1社に伝わります（LINEだけで登録した方はメールが渡らず、LINEでの連絡のご案内になります）。お名前と電話番号は、どの業者にも渡りません。訪問時には、業者が法令に基づき本人確認をする場合があります。
              </p>
            </li>
            <li>
              <h3>お断りは、カタヅケから</h3>
              <p>選ばなかった業者には、カタヅケから自動でお断りを入れます。あなたが1社ずつ断りの連絡をする必要はありません。</p>
            </li>
            <li>
              <h3>入札できるのは、審査を通った業者だけ</h3>
              <p>登録の審査で、古物商許可番号と許可証の画像を確認しています。確認が取れない業者は入札できません。</p>
            </li>
          </ol>
          <div className="tp-who">
            <table>
              <caption>業者に見えるもの</caption>
              <thead>
                <tr>
                  <th scope="col">情報</th>
                  <th scope="col">入札中</th>
                  <th scope="col">選んだあと</th>
                </tr>
              </thead>
              <tbody>
                {WHO_SEES.map((row) => (
                  <tr key={row.what}>
                    <th scope="row">{row.what}</th>
                    <td className={row.during.seen ? "tp-yes" : "tp-no"}>{row.during.text}</td>
                    <td className={row.after.seen ? "tp-yes" : "tp-no"}>{row.after.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="tp-who__note">チャットに書いた内容は、選んだ業者に届きます。</p>
          </div>
        </div>
      </section>

      {/* ============ 使い方 ============ */}
      <section id="daily" className="tp-sec tp-flow">
        <div className="tp-wrap">
          <div className="sec-head">
            <div>
              <p className="label">使い方</p>
              <h2>出品から引き取りまで</h2>
            </div>
            <p>
              ジャンルが混ざっていても大丈夫です。大型の家具や、量の多い品物も、まとめてご相談いただけます。どんな使い方になるかは、
              <Link href="/examples" className="link">
                利用イメージ
              </Link>
              でも紹介しています。
            </p>
          </div>
          <ol className="tp-steps">
            <li>
              <div className="tp-step-t">
                <span className="tp-step-n tp-num">1</span>
                <h3>品物を撮って、まとめて出品</h3>
              </div>
              <p>
                家じゅうの品物を1点ずつ撮影して、品目を選んで登録します。思いついた物から撮っていけば大丈夫です。
                <small>スマートフォンのカメラだけでできます。</small>
              </p>
            </li>
            <li>
              <div className="tp-step-t">
                <span className="tp-step-n tp-num">2</span>
                <h3>入札が届くのを待つ</h3>
              </div>
              <p>業者が写真を見て、品物すべての買取総額で入札します。入札が届くと、LINE かメールでお知らせします。</p>
            </li>
            <li>
              <div className="tp-step-t">
                <span className="tp-step-n tp-num">3</span>
                <h3>金額を見比べて、1社を選ぶ</h3>
              </div>
              <p>
                届いた入札は高い順に並びます。業者の口コミも見ながら、納得できる1社を選んでください。
                <small>選ばなかった業者には、自動でお断りが入ります。</small>
              </p>
            </li>
            <li>
              <div className="tp-step-t">
                <span className="tp-step-n tp-num">4</span>
                <h3>都合のいい日に引き取り</h3>
              </div>
              <p>
                業者が出した訪問日時の候補から、ボタンで選びます。当日、業者が現物を確認して、買取額が決まります。
                <small>当日の現物確認で状態が違えば、金額のご相談が届くことがあります。納得できなければお断りできます。</small>
              </p>
              <figure className="tp-step-photo">
                <img
                  src="/img/lp/message-hands.webp"
                  alt="引き取りに出す毛布を段ボールにまとめている手元"
                  width={1024}
                  height={1024}
                  loading="lazy"
                  decoding="async"
                />
                <figcaption>
                  引き取りの日までに、出す物をひとまとめにしておくだけ。当日は業者が品物を確認して引き取ります。
                  <span>（写真はイメージです）</span>
                </figcaption>
              </figure>
            </li>
          </ol>
        </div>
      </section>

      {/* ============ 料金 ============ */}
      <section id="fee" className="tp-sec tp-fee-sec">
        <div className="tp-wrap tp-fee">
          <div>
            <p className="label">カタヅケの利用料</p>
            <p className="tp-fee-big tp-num">
              0<small>円</small>
            </p>
            <h2>
              <span className="tp-nb">出品から成約まで、</span>
              <br />
              <span className="tp-nb">カタヅケの利用料は</span>
              <span className="tp-nb">かかりません。</span>
            </h2>
          </div>
          <div>
            <ul className="tp-fee-list">
              {FEE_ROWS.map((label) => (
                <li key={label}>
                  <span>{label}</span>
                  <span>0円</span>
                </li>
              ))}
            </ul>
            <div className="tp-sub hero-cta">
              <LineButton />
              <Link href={EMAIL_SIGNUP_HREF} className="link">
                メールアドレスで登録する
              </Link>
            </div>
            {/* N-1: 無料なのはカタヅケの利用料に限る。業者との取引の費用は 0円 と同じ視野・同じ大きさで断る */}
            <p className="tp-fee-note">出張・運搬・処分にかかる費用の扱いは業者ごとに異なります。成約前にお確かめください。</p>
            <p className="tp-fee-note">最終的な買取額は、業者が現物を見て決めます。</p>
          </div>
        </div>
      </section>

      {/* ============ 運営者 ============ */}
      <section id="founder" className="tp-sec tp-operator">
        <div className="tp-wrap">
          <p className="label">運営者</p>
          <dl>
            <div>
              <dt>運営</dt>
              <dd>
                カタヅケ運営事務局
                <small>個人事業（法人ではありません）</small>
              </dd>
            </div>
            <div>
              <dt>所在地</dt>
              <dd>神奈川県横浜市</dd>
            </div>
            <div>
              <dt>お問い合わせ</dt>
              <dd>
                <Link href="/contact" className="link">
                  お問い合わせフォーム
                </Link>
                <small>メールで、通常3営業日以内にご返信します</small>
              </dd>
            </div>
            <div>
              <dt>関連ページ</dt>
              <dd>
                <Link href="/company" className="link">
                  運営者情報
                </Link>
                <br />
                <Link href="/legal" className="link">
                  特定商取引法に基づく表記
                </Link>
                <br />
                <Link href="/privacy" className="link">
                  個人情報の取り扱い
                </Link>
              </dd>
            </div>
          </dl>
          <p className="tp-operator-note">
            個人で運営しているため、代表者名・詳細住所（番地等）・電話番号は常時掲載していません。請求があれば遅滞なく開示します。
          </p>
        </div>
      </section>
    </main>
  );
}
