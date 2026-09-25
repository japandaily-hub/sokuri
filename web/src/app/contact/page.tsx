"use client";

/** お問い合わせ（フォーム）。デザイン handoff: docs/design_handoff_katazuke/contact.html を忠実移植。
 *  ヘッダー/フッターは共通 SiteChrome が付与するため、ここでは <main id="main"> の中身のみ描画する。
 *  POST /contact（katadzuke-api.ts submitContactMessage）へ配線済み。422/429/5xx は日本語の
 *  案内に変換して表示し、失敗時に偽の完了表示は出さない（運営導線監査 r3-operator.md H1 是正）。 */

import { Suspense, useEffect, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { Ic } from "@/components/kdz/Icons";
import { Reveal } from "@/components/kdz/interactions";
import { ILLUSTRATIONS, ILL_POSITIONS, illSrc, type IllName } from "@/lib/illustrations";
import { KdzApiError, submitContactMessage, toDisplayMessage } from "@/lib/katadzuke-api";
import { parseReviewReportSubject, withReviewReportPrefix } from "@/lib/review-report";
import "./contact.css";

/** 循環イラスト帯（ビジュアル刷新 Phase 3・architect指示）。フォーム主体の軽いページのため、
 *  トップページの6点フルセットではなく4点に絞る。円周配置(top/24%/76%/98%)上で上下左右に
 *  1点ずつ散るよう選定し、デスクトップ幅で右側に偏らないようにする(QAレビュー Medium 対応)。 */
const ILL_LOOP: IllName[] = ["box", "truck", "folding-hands", "plant"];

type FieldId = "name" | "email" | "category" | "message";

const REQUIRED: FieldId[] = ["name", "email", "category", "message"];

const SUBMIT_FAILED_MESSAGE = "送信できませんでした。しばらくしてからもう一度お試しください。";

/** 「事業者情報の開示請求」（特商法11条）の option 値。backend の ContactCategory は
 *  Literal 8値に固定されており、このスラッグをそのまま送ると 422 になる。 */
const DISCLOSURE_CATEGORY = "disclosure";
/** 開示請求を送るときに本文の先頭へ前置する種別名（運営通知メールで判別するため）。 */
const DISCLOSURE_PREFIX = "【事業者情報の開示請求】";

/**
 * 送信ペイロードの種別・本文を組み立てる。
 * 開示請求は backend に専用スラッグが無いため category は既存の "other" に畳み、
 * 本文の先頭に種別を前置して「その他」と区別できるようにする暫定策（QA H1）。
 * backend（schemas_katadzuke.ContactCategory と services/notify._CONTACT_CATEGORY_LABELS）に
 * disclosure が追加されたら、この関数ごと外して value をそのまま送る。
 * （page.tsx は Next の page エントリなので named export を増やさない。検証は実 POST の傍受で行う）
 */
function buildContactPayload(selectedCategory: string, message: string, reportedReviewId: string | null) {
  const withReviewPrefix = reportedReviewId ? withReviewReportPrefix(reportedReviewId, message) : message;
  if (selectedCategory !== DISCLOSURE_CATEGORY) {
    return { category: selectedCategory, message: withReviewPrefix };
  }
  return { category: "other", message: `${DISCLOSURE_PREFIX}\n${withReviewPrefix}` };
}

function ContactPageContent() {
  /* ログイン中なら送信に backend のアクセストークンを添える（backend が依頼者アカウントに
     問い合わせを紐付け、退会時の匿名化を本人の送信分だけに限定するため）。未ログイン・
     セッション読込中（status === "loading" で data が未確定）は session が無く、従来どおり
     トークン無しの匿名送信になる。画面の文言・入力・バリデーションには使わない。 */
  const { data: session } = useSession();
  /* vendors/[id] の「この口コミを報告する」リンクから来た場合、subject（厳密一致のときだけ）
     から口コミ ID を読み取る。無関係な subject（開示請求等）は無視する。 */
  const searchParams = useSearchParams();
  const reportedReviewId = parseReviewReportSubject(searchParams.get("subject"));
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  /* インラインエラー文言。空文字列 = エラー無し（mypage/profile の seiErr 等と同じ運用）。 */
  const [errors, setErrors] = useState<Record<FieldId, string>>({
    name: "",
    email: "",
    category: "",
    message: "",
  });

  /** 送信完了パネルの見出し。フォームが消えてパネルに差し替わるため、
   *  フォーカスが body に落ちないよう見出しへ移す（スクリーンリーダーは完了文を読み上げる）。 */
  const thanksHeadingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (sent) thanksHeadingRef.current?.focus();
  }, [sent]);

  function clearError(id: FieldId) {
    setErrors((prev) => (prev[id] ? { ...prev, [id]: "" } : prev));
  }

  /** 必須項目ごとの文言。フィールド名を主語にして「何を・どう直せばよいか」まで書く。 */
  const REQUIRED_MESSAGE: Record<FieldId, string> = {
    name: "お名前を入力してください",
    email: "メールアドレスを入力してください",
    category: "お問い合わせ種別を選択してください",
    message: "お問い合わせ内容を入力してください",
  };

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (sending) return; // 二重送信防止
    const form = e.currentTarget;
    const next: Record<FieldId, string> = {
      name: "",
      email: "",
      category: "",
      message: "",
    };
    let ok = true;
    for (const id of REQUIRED) {
      const el = form.elements.namedItem(id) as
        | HTMLInputElement
        | HTMLSelectElement
        | HTMLTextAreaElement
        | null;
      if (!el || !el.value.trim()) {
        next[id] = REQUIRED_MESSAGE[id];
        ok = false;
      } else if (id === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(el.value.trim())) {
        // メール形式の検証（noValidate のためネイティブ検証は効かない）
        next[id] = "メールアドレスの形式が正しくありません";
        ok = false;
      }
    }
    setErrors(next);
    if (!ok) return;

    const name = (form.elements.namedItem("name") as HTMLInputElement).value.trim();
    const email = (form.elements.namedItem("email") as HTMLInputElement).value.trim();
    const selectedCategory = (form.elements.namedItem("category") as HTMLSelectElement).value;
    const { category, message } = buildContactPayload(
      selectedCategory,
      (form.elements.namedItem("message") as HTMLTextAreaElement).value.trim(),
      reportedReviewId,
    );

    setSending(true);
    setSubmitError(null);
    try {
      await submitContactMessage({ name, email, category, message }, session?.accessToken);
      setSent(true);
      if (typeof window !== "undefined") {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    } catch (err) {
      if (err instanceof KdzApiError && err.status === 422) {
        setSubmitError("入力内容をご確認のうえ、もう一度お試しください。");
      } else if (err instanceof KdzApiError && err.status === 429) {
        setSubmitError("送信が集中しています。しばらく時間をおいて再度お試しください。");
      } else if (err instanceof KdzApiError && err.status === 503) {
        // r8-fix-frontend2 M7 是正: toDisplayMessage は 5xx を一律汎用文言に潰すため、
        // backend が「今は混んでいる（後で通る）」意図で返す 503 detail（Retry-After 付き）
        // が届かなかった。他の 5xx（壊れている）とは区別し detail をそのまま出す。
        setSubmitError(err.message.trim() || "ただいま混み合っています。数分後に再度お送りください。");
      } else {
        setSubmitError(toDisplayMessage(err, SUBMIT_FAILED_MESSAGE));
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <main id="main">
      {/* ============ ページヒーロー（帯上に文字を置かない） ============
          r1 レビュー（ct-band 未生成のため帯は無文字の濃紺ベタ）の時点では、情報ゼロの
          上端を詰めるため法務3ページと同じ --fixed（PC 160px／モバイル 120px）に落とし、
          「ct-band 生成後に --slim へ戻すかは画像が入ってから判断する」と保留していた。
          ラウンド4（画像投入後）で PC・SP とも「封筒とカップが上下で切れた薄片に見える／
          読み込み途中のように見える」の指摘が2件出たため、保留していた判断をここで確定し
          --slim（PC clamp(180px,22vw,240px)／モバイル clamp(160px,40vw,200px)）へ戻した。
          高さは共有の修飾子だけで決める（ページ CSS で .hero-band--* を再定義しない・
          --band-pos もページ CSS に書かない＝R4 D.1/F.0）。帯上に文字は置かないまま。

          ラウンド5 指摘（1/6/8/10/17 の5件が同一箇所）: 縦位置が未是正で封筒のフラップが
          上端、カップが右端で切れていた。是正は core の katazuke-pages.css に入り
          （.hero-band:has(> img[src*="ct-band"]) で --band-pos:50% 52% と
          min-height:clamp(200px,21vw,300px)／SP 200px を素材限定で指定）、封筒とカップが
          丸ごと画角に入る。ここで持っていた --pos-r（--band-pos:20%→80% 50% の横位置）は
          外す: 素材 1920x1080 に対し帯は常にそれより横長にトリミングされるため横成分は
          効かず、「右寄せで切っている」という誤った宣言が残るだけだった（縦位置の共有
          修飾子は core 側が :has() で当てるため、ここにクラスを足す必要はない）。 */}
      <section className="hero-band hero-band--slim hero-band--quiet">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/img/v2/ct-band.webp"
          width="1920"
          height="1080"
          alt=""
          loading="eager"
          fetchPriority="high"
          decoding="async"
        />
        <div className="hero-band__veil" aria-hidden="true" />
      </section>

      <section className="ct-head">
        <div className="ct-head__box">
          <span className="ct-head__en">CONTACT</span>
          <h1>お問い合わせ</h1>
          <p>サービスに関するご質問・ご要望など、お気軽にお問い合わせください。</p>
          <p className="ct-head__faq">
            <Link href="/faq">よくある質問で解決するかもしれません</Link>
          </p>
        </div>
      </section>

      {/* ============ 循環イラスト帯 ============
          ビジュアル刷新 Phase 3（architect指示）: 帯・見出しを読み終えた直後、フォームに入る前の
          一息の位置に置く（トップページと同じ .ill-loop を再利用。クラス定義は
          katazuke-motion.css へ移設済みで新規追加はしていない）。フォーム本体には一切かけない
          （Phase 2 の教訓: 同意チェックボックス等の演出は不可視だが操作可能な状態を生みうる）。
          装飾のみのため section 全体を aria-hidden にする。 */}
      <section className="ill-loop" aria-hidden="true">
        <div className="container">
          <div className="ill-loop-inner ill-scope">
            {ILL_LOOP.map((name, i) => {
              const meta = ILLUSTRATIONS[name];
              const pos = ILL_POSITIONS[name];
              return (
                <Reveal
                  key={name}
                  className={`ill-item ill-item--${name}`}
                  stagger={i}
                  style={{ "--ill-top": pos.top, "--ill-left": pos.left } as CSSProperties}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={illSrc(name)}
                    alt={meta.alt}
                    width={meta.w}
                    height={meta.h}
                    loading="lazy"
                    decoding="async"
                  />
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ============ フォーム ============ */}
      <div className="section tight">
        <div className="contact-wrap container">
          {/* LINE 優先案内 */}
          <div className="line-first">
            <div className="line-first-body">
              {/* ラウンド5 指摘（11/13）: 「LINEなら最短、フォームならメールで返信」は
                  1行に収まらず読点で2行に折れ、さらに隣のボタンが「LINEではじめる／LINE
                  アカウントでログインできます」＝出品のログイン導線なので、質問したいだけの
                  人には「どちらを押せば返事が来るのか」が読めなかった。見出しは意味の
                  切れ目1つ（＝LINEは依頼の導線）に絞り、返信の経路は本文で言い切る。
                  ボタンの本数・href は増やさない（R4 4.: ページ内の LINE CTA を増やさない）。 */}
              <strong>査定・出品のご依頼はLINEから</strong>
              {/* ラウンド4 指摘（High）: リンク先は自社ログイン（/login?callbackUrl=/create）で
                  友だち追加は発生しない。R4 ブリーフが CTA から外した「友だち追加」の語が本文に
                  残っていたため差し替える。公式アカウント導線が実装されるまでこの語は使わない。 */}
              <p>
                LINEアカウントでログインすれば、そのまま出品をはじめられます。ご質問は下のフォームからお送りください。ご返信はメールでお送りします。
              </p>
            </div>
            {/* LINE CTA は 7 箇所共通の 2 トーン構造（主色ブルーの面＋左端に LINE 緑のタイル）。
                タイルは aria-hidden の純装飾で、アクセシブル名はラベル＋補足の文字が担う。 */}
            {/* 2026-09-15 ユーザー指示: LINEログイン着地先を/createから/mypageへ変更（他CTAと統一） */}
            <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line btn-lg">
              <span className="btn-line__tile" aria-hidden="true" />
              <span className="btn-line__body">
                <span className="btn-line__label">LINEではじめる（無料）</span>
                <span className="btn-line__sub">LINEアカウントでログインできます</span>
              </span>
              <Ic name="arrow" className="btn-line__arr" />
            </Link>
          </div>

          <div className="or-divider">ご質問・ご相談は、下のフォームから</div>

          {/* ラウンド5 指摘（18・業者視点）: 先頭が依頼者向けの LINE ブロックだけで、業者は
              種別プルダウンを開くまで自分が対象か分からなかった。フォームの手前に1行だけ
              置く（LINE ブロックには触らない・ボタンは増やさない）。 */}
          <p className="ct-biz-note">
            業者登録をご希望の方は
            <Link href="/business">業者登録のお申し込み</Link>
            へ。審査や料金のご質問は、このフォーム（種別「業者登録・提携について」）でも承ります。
          </p>

          {/* フォームカード */}
          <div className="form-card" id="form">
            {!sent ? (
              <div id="form-body">
                <p className="form-section-label">お問い合わせフォーム</p>
                <p className="form-owner">
                  担当：カタヅケ運営事務局（メールでの対応を原則としています）
                </p>

                {reportedReviewId ? (
                  <p className="field-hint" style={{ marginBottom: 20 }}>
                    報告する口コミ: {reportedReviewId}
                  </p>
                ) : null}

                {submitError && (
                  <div className="auth-error" role="alert" style={{ marginBottom: 16 }}>
                    <svg
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                      style={{
                        width: 16,
                        height: 16,
                        fill: "none",
                        stroke: "var(--danger)",
                        strokeWidth: 2,
                        strokeLinecap: "round",
                        flexShrink: 0,
                      }}
                    >
                      <circle cx="12" cy="12" r="9" />
                      <path d="M12 8v4M12 16h.01" />
                    </svg>
                    {submitError}
                  </div>
                )}

                <form onSubmit={onSubmit} noValidate>
                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="name">
                        お名前<span className="req">必須</span>
                      </label>
                      {/* ラウンド4 指摘（Med）: 和文のプレースホルダは同じ色（4 欄とも
                          --body-soft の1値）でも欧文より濃く見え、「すでに入力済みの値」と
                          誤読される。入力値ではないことが文字で分かるよう「例）」を前置する。 */}
                      <input
                        type="text"
                        id="name"
                        name="name"
                        placeholder="例）山田 花子"
                        autoComplete="name"
                        className={errors.name ? "has-error" : undefined}
                        onInput={() => clearError("name")}
                      />
                      {errors.name ? <p className="field-error">{errors.name}</p> : null}
                    </div>
                    <div className="field">
                      <label htmlFor="kana">
                        フリガナ<span className="opt">任意</span>
                      </label>
                      <input
                        type="text"
                        id="kana"
                        name="kana"
                        placeholder="例）ヤマダ ハナコ"
                        autoComplete="off"
                      />
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="email">
                      メールアドレス<span className="req">必須</span>
                    </label>
                    <input
                      type="email"
                      id="email"
                      name="email"
                      placeholder="example@email.com"
                      autoComplete="email"
                      inputMode="email"
                      className={errors.email ? "has-error" : undefined}
                      onInput={() => clearError("email")}
                    />
                    {errors.email ? <p className="field-error">{errors.email}</p> : null}
                  </div>

                  <div className="field">
                    <label htmlFor="phone">
                      電話番号<span className="opt">任意</span>
                    </label>
                    <input
                      type="tel"
                      id="phone"
                      name="phone"
                      placeholder="例）090-0000-0000"
                      aria-describedby="phone-hint"
                      autoComplete="tel"
                    />
                    {/* R6 指摘 15: 「任意」バッジだけでは、営業電話を警戒する読者に
                        「なぜ電話番号を聞くのか」が読めず入力をためらわせていた。
                        返信の経路（メール）と、電話を使う場合を1行で言い切る。
                        フォームの返信はメール原則（/legal の運営者情報・上の .form-owner と同旨）。 */}
                    <div className="field-hint" id="phone-hint">
                      ご返信はメールでお送りします。電話番号は、内容の確認が必要な場合に運営からご連絡するときだけ使用します。
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="category">
                      お問い合わせ種別<span className="req">必須</span>
                    </label>
                    <div className="select-wrap">
                      <select
                        id="category"
                        name="category"
                        defaultValue={reportedReviewId ? "other" : ""}
                        className={errors.category ? "has-error" : undefined}
                        onChange={() => clearError("category")}
                      >
                        <option value="" disabled>
                          選択してください
                        </option>
                        <option value="service">サービスについて</option>
                        <option value="pricing">料金・費用について</option>
                        <option value="area">対応エリアについて</option>
                        <option value="privacy">個人情報の取り扱いについて</option>
                        {/* 特商法に基づく事業者情報（代表者名・詳細住所・電話番号）の開示請求。
                            QA H1 是正: 「その他」と同じ value="other" を2つ並べると選択が区別
                            できず（controlled 化した瞬間に表示も壊れる）、運営通知メールで開示
                            請求が一般問い合わせに埋もれた。option は専用の value にし、送信時に
                            buildContactPayload が category を既存の "other" へ畳んだうえで本文
                            先頭に種別を前置する（backend の ContactCategory は Literal 8値固定で、
                            新しいスラッグをそのまま送ると 422 になるため）。 */}
                        <option value={DISCLOSURE_CATEGORY}>事業者情報の開示請求</option>
                        <option value="trouble">トラブル・クレーム</option>
                        <option value="partner">業者登録・提携について</option>
                        <option value="press">取材・メディア掲載</option>
                        <option value="other">その他</option>
                      </select>
                    </div>
                    {errors.category ? <p className="field-error">{errors.category}</p> : null}
                  </div>

                  <div className="field">
                    <label htmlFor="message">
                      お問い合わせ内容<span className="req">必須</span>
                    </label>
                    <textarea
                      id="message"
                      name="message"
                      placeholder="ご質問・ご要望をできるだけ詳しくご記入ください。"
                      className={errors.message ? "has-error" : undefined}
                      onInput={() => clearError("message")}
                    />
                    {errors.message ? <p className="field-error">{errors.message}</p> : null}
                  </div>

                  <div className="submit-area">
                    <button type="submit" className="btn-submit" disabled={sending}>
                      <svg
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                        style={{
                          width: 20,
                          height: 20,
                          fill: "none",
                          stroke: "#fff",
                          strokeWidth: 1.9,
                          strokeLinecap: "round",
                          strokeLinejoin: "round",
                          flexShrink: 0,
                        }}
                      >
                        <path d="M22 2L11 13" />
                        <path d="M22 2L15 22l-4-9-9-4 20-7z" />
                      </svg>
                      {sending ? "送信中…" : "送信する"}
                    </button>
                    <p className="note">
                      お送りいただいた内容には、通常3営業日以内にご返信します。
                      <br />
                      ご送信をもって
                      <Link href="/privacy">プライバシーポリシー</Link>
                      に同意したものとみなします。
                    </p>
                  </div>
                </form>
              </div>
            ) : (
              /* 送信完了 */
              <div className="thanks" id="thanks">
                <div className="thanks-ic">
                  <svg
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                    style={{
                      width: 32,
                      height: 32,
                      fill: "none",
                      stroke: "var(--blue)",
                      strokeWidth: 2,
                      strokeLinecap: "round",
                      strokeLinejoin: "round",
                    }}
                  >
                    <circle cx="12" cy="12" r="9" />
                    <path d="M8 12l2.5 2.5L16 9" />
                  </svg>
                </div>
                <h2 ref={thanksHeadingRef} tabIndex={-1}>
                  送信を受け付けました
                </h2>
                <p>
                  お問い合わせありがとうございます。
                  <br />
                  ご入力いただいたメールアドレス宛に、3営業日以内にご連絡します。自動の受付確認メールはお送りしていません。
                </p>
                <Link href="/" className="btn btn-ghost btn-lg">
                  トップページへ戻る
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

/** useSearchParams（?subject=）を使うため Suspense 境界で包む（本番ビルドの静的プリレンダー要件。他ページと同型）。 */
export default function ContactPage() {
  return (
    <Suspense fallback={null}>
      <ContactPageContent />
    </Suspense>
  );
}
