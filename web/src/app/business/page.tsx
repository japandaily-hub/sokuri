"use client";

/**
 * 業者向けLP（/business）。
 * デザイン正典: docs/design_handoff_katazuke/業者向け.html を Next.js 化。
 * - 独自ヘッダー（業者ナビ + #register CTA + モバイルメニュー）。共通 SiteChrome は付かない（BARE_PREFIXES 対象）。
 * - ページ内アンカー（#merit/#flow/#requirements/#faq/#register）はグローバル scroll-behavior:smooth で滑らかにスクロール。
 * - 登録フォームは "use client" + useState で送信検証 → POST /operator-applications → 完了表示。
 * client component のため export const metadata は置かない（SEOはレイアウト側で担保）。
 */

import "./business.css";
import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { Reveal, FaqAccordion } from "@/components/kdz/interactions";
import { submitOperatorApplication, toDisplayMessage } from "@/lib/katadzuke-api";

/** 共通スプライトに send が無いため inline 用の紙飛行機アイコン。 */
function SendIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={18}
      height={18}
      className={`biz-send-ic${className ? ` ${className}` : ""}`}
      aria-hidden="true"
    >
      <path d="M22 2L11 13" />
      <path d="M22 2L15 22l-4-9-9-4 20-7z" />
    </svg>
  );
}

/** ヘッダー/モバイル共通ナビ（ページ内アンカー） */
const NAV: { href: string; label: string }[] = [
  { href: "#merit", label: "参加メリット" },
  { href: "#flow", label: "掲載の流れ" },
  { href: "#requirements", label: "登録要件" },
  { href: "#faq", label: "よくある質問" },
];

/** 数値帯（事実ベースのサービス条件のみ。計測実績風の数値は景表法（優良誤認）回避のため
 *  実データ集計が配線されるまで掲載しない） */
const STATS: { num: string; unit: string; label: string }[] = [
  { num: "4", unit: "都県", label: "東京・千葉・埼玉・神奈川" },
  { num: "0", unit: "円", label: "初期費用・月額費用" },
  { num: "8", unit: "%", label: "成約時の手数料のみ" },
  { num: "12", unit: "カテゴリ", label: "家電〜ブランド品まで対応" },
  { num: "0", unit: "回", label: "下見・現地調査" },
];

/** 仕入れる3つの理由（画像付き3カラム）。効果の断定は避け、条件と手順で説明する。 */
const REASONS: { n: string; tag: string; img: string; h: ReactNode; p: string; d?: 1 | 2 }[] = [
  {
    n: "01",
    tag: "まとめ",
    img: "biz-reason-bulk",
    h: "まとめ買いで、1回の訪問がまとまる",
    p: "ユーザーは家じゅうの不用品をまとめて出品します。1回の訪問でまとまった点数を見られるため、1点ずつ集める買取に比べて移動・交渉のコストを削減しやすくなります。",
  },
  {
    n: "02",
    tag: "下見なし",
    img: "biz-reason-photo",
    /* r2 L6 是正: 3カラム幅で「写真と品目から、下／見なしで…」と語中改行されるため、
       「下見なし」だけを折り返し禁止にして読点で割れるようにする（text-wrap:balance と併用）。 */
    h: (
      <>
        写真と品目から、<span className="nw">下見なし</span>で入札できる
      </>
    ),
    p: "出品情報は写真・品目・地域（都道府県・市区町村）・住居情報などで構成。現物確認の前に買取総額の入札ができるため、下見の移動コストがかかりません。入札はすべてユーザーに一覧で提示されます。",
    d: 1,
  },
  {
    n: "03",
    tag: "入札制",
    img: "biz-reason-route",
    h: "入札制で、自社の基準に合う案件だけ選べる",
    p: "複数業者が買取総額で競う入札制。過度な値引き競争ではなく、出品された商品全体の価値に対して金額を提示できます。自社の買取基準や対応エリアに合った案件だけに入札可能です。",
    d: 2,
  },
];

/** 安心して参加できる理由（04〜06・ヘアラインリスト） */
const ASSURANCES: { n: string; h: string; p: string }[] = [
  {
    n: "04",
    h: "営業電話の一斉架電なし",
    p: "ユーザーへ連絡できるのは、選ばれた業者のみ。無駄な営業電話をかける必要がなく、成約に進んだユーザーとだけ丁寧にやりとりできます。信頼関係を築きやすい環境です。",
  },
  {
    n: "05",
    h: "費用は成約時の8%（税別）のみ",
    p: "登録・掲載・入札はすべて無料。成約が決まった際に、買取金額の8%（税別・消費税を別途加算）のみ手数料として発生します。それ以外の費用は一切かかりません。固定費ゼロで始められます。※ サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします。",
  },
  {
    n: "06",
    h: "顧客・業者・社会、三者に喜びと安心を",
    p: "顧客は手軽に手放せ、業者はまとめて仕入れられる。双方が納得できる取引が成立し、不用品が社会に循環する。カタヅケは「三方よし」の仕組みだからこそ、長く安定したプラットフォームになれると考えています。",
  },
];

/** 業者視点のフロー（4ステップ）。アイコンは既存 3D シリーズ（/img/real/*.webp・512px）。 */
const FLOW: { n: string; img: string; h: string; p: string; d?: 1 | 2 | 3 }[] = [
  { n: "1", img: "how-camera", h: "案件を確認", p: "出品された「まとめ」の写真・品目リストを確認。気になる案件に入札します。" },
  { n: "2", img: "how-trend", h: "買取総額で入札", p: "出品された商品すべてに対して、買取総額を提示。他社と競い合います。", d: 1 },
  { n: "3", img: "how-crown", h: "ユーザーが1社を選択", p: "全入札がユーザーに提示され、見比べて1社を選択。選ばれると連絡先が開示されます。", d: 2 },
  { n: "4", img: "how-truck", h: "訪問・引き取り", p: "成約後に訪問日時を決定。まとめて引き取りを行います。", d: 3 },
];

/** 登録要件 */
const REQUIREMENTS: { icon: "shield" | "people" | "tag" | "check-circle"; h: string; p: string }[] = [
  { icon: "shield", h: "古物商許可証", p: "古物営業法に基づく古物商許可を取得していること。登録時に許可証のコピーをご提出いただきます。" },
  { icon: "people", h: "法人または個人事業主", p: "事業として買取・リユースを営んでいること。個人での副業・転売目的の登録はお断りしています。" },
  { icon: "tag", h: "対応エリア内での訪問買取", p: "東京都・千葉県・埼玉県・神奈川県のいずれかで訪問買取ができること。" },
  { icon: "check-circle", h: "特定商取引法の遵守", p: "訪問買取において特定商取引法（法定書面の交付、クーリング・オフが適用される取引への対応等）を遵守していること。審査時に確認させていただきます。" },
];

/** 業者向けFAQ（共通 FaqAccordion で描画） */
const FAQ_ITEMS = [
  { q: "手数料はいくらですか？", a: "登録・掲載・入札はすべて無料です。費用が発生するのは成約時のみで、買取金額の8%（税別・消費税を別途加算）が手数料として発生します。それ以外の費用は一切かかりません。なお、サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします。" },
  { q: "古物商許可がなくても登録できますか？", a: "いいえ。カタヅケへの業者登録には、有効な古物商許可証が必要です。許可取得後に改めてお申し込みください。" },
  { q: "入札した案件はすべて交渉できますか？", a: "ユーザーが届いた入札を見比べて1社を選びます。選ばれた場合のみ連絡先が開示され、取引に進めます。選ばれなかった入札は自動でお断りとなり、ユーザーへの連絡はできません。" },
  { q: "入札した金額はあとから変更できますか？", a: "ユーザーが業者を選ぶまでの間、案件詳細から入札額を現在の金額より高い方向へ何度でも引き上げられます（引き下げはできません）。他社の入札額は匿名で表示されます（社名・コメントは非開示）。" },
  { q: "他社の入札額は見えますか？", a: "案件詳細で「現在の最高額」と、匿名化された他社の入札額（社名・コメントは非開示）を確認できます。自社の入札が最高額でない場合は差額も表示されるため、引き上げの判断材料としてご利用いただけます。" },
  { q: "エリア外の案件に入札できますか？", a: "現在は東京都・千葉県・埼玉県・神奈川県が対応エリアです。エリア外への訪問買取は受け付けていません。" },
  { q: "最終的な買取額は入札額と異なってもいいですか？", a: "提示した買取金額を下回る変更は、査定現場で商品を確認し、理由を明示したうえで顧客の了解を得た場合にのみ可能です。顧客の同意なく一方的に減額することはできません。" },
  { q: "審査にはどのくらい時間がかかりますか？", a: "お申し込みから通常3営業日以内に審査結果をご連絡します。古物商許可証の確認が必要なため、書類に不備がある場合は時間がかかることがあります。" },
  // r10 H2 是正: 依頼者側には「代金の受け取り方法は業者とチャットで調整」と案内しているのに、
  // 業者向けの説明がどこにも無かった（当事者間精算であることを明示する）。
  { q: "買取代金はどのように支払いますか？", a: "買取代金は依頼者と直接精算します（現金またはお振込み。方法はチャットで調整してください）。カタヅケは送金を仲介しません。カタヅケがやり取りするのは成約時の手数料のみです。" },
];

type FormState = {
  company: string;
  rep: string;
  repName: string;
  registeredAddress: string;
  email: string;
  phone: string;
  bizType: string;
  area: string;
  cats: string;
  message: string;
  licenseNumber: string;
  invoiceNumber: string;
  bankName: string;
  branchName: string;
  accountType: string;
  accountNumber: string;
  accountHolder: string;
  agree: boolean;
};

const EMPTY_FORM: FormState = {
  company: "",
  rep: "",
  repName: "",
  registeredAddress: "",
  email: "",
  phone: "",
  bizType: "",
  area: "",
  cats: "",
  message: "",
  licenseNumber: "",
  invoiceNumber: "",
  bankName: "",
  branchName: "",
  accountType: "",
  accountNumber: "",
  accountHolder: "",
  agree: false,
};

/** 案件エリアの select value → バックエンド service_area 文字列（人が読める表記） */
const AREA_LABEL: Record<string, string> = {
  tokyo: "東京都",
  chiba: "千葉県",
  saitama: "埼玉県",
  kanagawa: "神奈川県",
  multi: "複数都県",
};

/** 必須項目（空ならエラー表示） */
const REQUIRED_KEYS: (keyof FormState)[] = [
  "company",
  "rep",
  "repName",
  "registeredAddress",
  "email",
  "phone",
  "bizType",
  "area",
  "licenseNumber",
  "bankName",
  "branchName",
  "accountType",
  "accountNumber",
  "accountHolder",
];

export default function BusinessPage() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [invalid, setInvalid] = useState<Set<string>>(new Set());
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (invalid.has(key)) {
      setInvalid((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const next = new Set<string>();
    REQUIRED_KEYS.forEach((k) => {
      const v = form[k];
      if (typeof v === "string" && !v.trim()) next.add(k);
    });
    if (form.licenseNumber.trim() && form.licenseNumber.trim().length < 5) next.add("licenseNumber");
    if (!form.agree) next.add("agree");
    setInvalid(next);
    if (next.size > 0) return;

    setSubmitError(null);
    setBusy(true);
    try {
      await submitOperatorApplication({
        company_name: form.company,
        representative_name: form.repName,
        registered_address: form.registeredAddress,
        contact_name: form.rep,
        email: form.email,
        phone: form.phone,
        business_type: form.bizType as "corp" | "sole",
        service_area: AREA_LABEL[form.area] ?? form.area,
        categories: form.cats.trim() || undefined,
        message: form.message.trim() || undefined,
        license_number: form.licenseNumber,
        invoice_number: form.invoiceNumber.trim() || undefined,
        bank_account: {
          bank_name: form.bankName,
          branch_name: form.branchName,
          account_type: form.accountType as "ordinary" | "checking",
          account_number: form.accountNumber,
          account_holder: form.accountHolder,
        },
        agreed: form.agree,
      });
      setSubmitted(true);
      const target = document.getElementById("register");
      if (target) window.scrollTo({ top: target.offsetTop - 80, behavior: "smooth" });
    } catch (err) {
      setSubmitError(toDisplayMessage(err, "送信に失敗しました。もう一度お試しください。"));
    } finally {
      setBusy(false);
    }
  };

  const invClass = (key: string) => (invalid.has(key) ? " is-invalid" : "");

  return (
    <div className="business-page bare-scope">
      {/* ============ 独自ヘッダー ============ */}
      <header className={`header scrolled${menuOpen ? " menu-open" : ""}`}>
        <div className="container inner">
          <Link href="/" className="logo" aria-label="カタヅケ トップへ">
            <KdzLogo size={23} />
          </Link>
          <nav className="nav" aria-label="業者向けナビゲーション">
            {NAV.map((n) => (
              <a key={n.href} href={n.href}>
                {n.label}
              </a>
            ))}
          </nav>
          <a href="#register" className="btn btn-primary h-cta">
            <SendIcon />
            業者登録を申し込む
          </a>
          <button
            type="button"
            className="hamburger"
            aria-label="メニュー"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((o) => !o)}
          >
            <Ic name={menuOpen ? "x" : "menu"} />
          </button>
        </div>
      </header>
      <div className="mobile-menu" id="mobile-menu">
        {NAV.map((n) => (
          <a key={n.href} href={n.href} onClick={() => setMenuOpen(false)}>
            {n.label}
          </a>
        ))}
        <a href="#register" className="btn btn-primary btn-block mm-cta" onClick={() => setMenuOpen(false)}>
          <SendIcon />
          業者登録を申し込む
        </a>
      </div>

      <main id="main">
        {/* ============ HERO ============
            ファーストビューのため Reveal は付けない（無 JS でも読める）。
            画像は LCP 候補なのでページ内で唯一 eager + fetchPriority="high"。 */}
        <section className="biz-hero">
          <div className="container">
            <div className="media-split media-split--rev biz-hero-split">
              <div className="img-frame img-frame--2x3 img-frame--pale biz-hero-fig sp-bleed">
                {/* eslint-disable @next/next/no-img-element */}
                {/* r2 H4 是正: 枠の意味は隣接する h1・hero-sub が担保しており、この写真は
                    仕入れ現場の雰囲気を伝える装飾。未生成・取得失敗時に alt 文がヒーロー枠へ
                    流れて第一印象を壊すため、ページ内の他の v2 画像と同じく alt="" に揃える。 */}
                <img
                  src="/img/v2/biz-hero.webp"
                  width={900}
                  height={1350}
                  alt=""
                  loading="eager"
                  fetchPriority="high"
                  decoding="async"
                />
                {/* eslint-enable @next/next/no-img-element */}
              </div>
              <div className="biz-hero-copy">
                <span className="eyebrow">買取業者の方へ</span>
                <h1>
                  まとめ買取の<br className="sp-br" />仕入れルートを、
                  <br />
                  <span className="hl">カタヅケ</span>で開拓する。
                </h1>
                <p className="hero-sub">
                  個人が家じゅうの不用品を、まとめて1件として出品します。
                  <br />
                  業者は写真と品目から買取総額を入札し、選ばれた1社だけがユーザーと直接やりとりします。
                  <br />
                  登録・掲載・入札は無料。費用は成約時の
                  <strong>買取金額8%（税別・消費税を別途加算）のみ</strong>です。
                </p>
                <div className="biz-hero-cta">
                  <a href="#merit" className="btn btn-primary btn-lg">
                    参加メリットを見る
                    <Ic name="arrow" />
                  </a>
                  <a href="#register" className="btn btn-ghost btn-lg">
                    <SendIcon />
                    業者登録を申し込む
                  </a>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ============ β期間の注記（8% を書く全箇所で条件を同一視野に置く） ============ */}
        <section className="biz-beta" aria-label="手数料について">
          <div className="container">
            <p className="biz-beta-note">
              いまは手数料0円（β期間）。請求開始は事前にメールでお知らせします。成約時8%（税別・消費税別途）。
            </p>
          </div>
        </section>

        {/* ============ 数値帯（事実ベースのみ） ============ */}
        <section className="biz-stats" aria-label="サービスの条件">
          <div className="container">
            <div className="inner">
              {STATS.map((s) => (
                <div className="stat-item" key={s.label}>
                  <div className="stat-num">
                    {s.num}
                    <span>{s.unit}</span>
                  </div>
                  <div className="stat-label">{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ============ 章の切れ目（写真帯・veil .65 = 見出し＋14px 以上の注記） ============ */}
        <section className="hero-band hero-band--mid biz-band-sorting">
          {/* eslint-disable @next/next/no-img-element */}
          <img
            src="/img/v2/biz-band-sorting.webp"
            width={1920}
            height={1080}
            alt=""
            loading="lazy"
            decoding="async"
          />
          {/* eslint-enable @next/next/no-img-element */}
          <div className="hero-band__veil" aria-hidden="true" />
          <div className="container hero-band__copy">
            <h2>写真と品目から、入札できる。</h2>
            <p className="biz-band-note">最終額は現物査定で決まります。</p>
          </div>
        </section>

        {/* ============ 参加メリット ============ */}
        <section className="section" id="merit">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">カタヅケの強み</span>
              <h2>カタヅケで仕入れる、3つの理由</h2>
              <p className="sub">家まるごとの一括出品だからこそ、まとめて見に行ける仕入れルートになります。</p>
            </div>
            <div className="biz-reason-grid">
              {REASONS.map((r) => (
                <Reveal as="article" className="biz-reason" delay={r.d} key={r.n}>
                  <div className="img-frame img-frame--1x1 img-frame--pale biz-reason-fig">
                    {/* eslint-disable @next/next/no-img-element */}
                    <img
                      src={`/img/v2/${r.img}.webp`}
                      width={800}
                      height={800}
                      alt=""
                      loading="lazy"
                      decoding="async"
                    />
                    {/* eslint-enable @next/next/no-img-element */}
                  </div>
                  <div className="biz-reason-num">
                    {r.n}
                    <span className="biz-reason-tag">{r.tag}</span>
                  </div>
                  <h3>{r.h}</h3>
                  <p>{r.p}</p>
                </Reveal>
              ))}
            </div>

            {/* 04〜06 は「3つの理由」の数と衝突しないよう別見出しのヘアラインリストに分ける */}
            <div className="biz-assure">
              {/* r2 L4 是正: 同ページの .section-head と同じ語彙（eyebrow ＋ 明朝見出し ＋ 短罫）に揃える。
                  見出しレベルは #merit の h2 配下なので h3 のまま。 */}
              <div className="biz-assure-head-wrap">
                <span className="eyebrow">運営のしくみ</span>
                <h3 className="biz-assure-head">安心して参加できる理由</h3>
              </div>
              <ul className="biz-assure-list">
                {ASSURANCES.map((a) => (
                  <li key={a.n}>
                    <span className="biz-assure-n" aria-hidden="true">{a.n}</span>
                    <div className="biz-assure-body">
                      <h4>{a.h}</h4>
                      <p>{a.p}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* ============ 業者視点のフロー ============ */}
        <section className="section bg-pale" id="flow">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">入札の流れ</span>
              <h2>入札から成約までの流れ</h2>
              <p className="sub">登録後はシンプルな4ステップ。下見なし・一斉架電なしで進められます。</p>
            </div>
            <div className="biz-flow">
              {FLOW.map((f) => (
                <Reveal className="biz-step" delay={f.d} key={f.n}>
                  <div className="img-frame img-frame--1x1 img-frame--contain img-frame--pale biz-step-fig">
                    {/* eslint-disable @next/next/no-img-element */}
                    <img
                      src={`/img/real/${f.img}.webp`}
                      width={512}
                      height={512}
                      alt=""
                      loading="lazy"
                      decoding="async"
                    />
                    {/* eslint-enable @next/next/no-img-element */}
                  </div>
                  <div className="biz-step-n" aria-hidden="true">{f.n}</div>
                  <h4>{f.h}</h4>
                  <p>{f.p}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ============ 登録要件 ============ */}
        <section className="section" id="requirements">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">ご利用条件</span>
              <h2>参加に必要な要件</h2>
              <p className="sub">ユーザーの安心のため、登録時に以下を確認させていただきます。</p>
            </div>
            <Reveal className="media-split media-split--rev biz-req-split">
              <div className="img-frame img-frame--1x1 img-frame--pale biz-req-fig sp-bleed">
                {/* eslint-disable @next/next/no-img-element */}
                <img
                  src="/img/v2/biz-req-docs.webp"
                  width={800}
                  height={800}
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
                {/* eslint-enable @next/next/no-img-element */}
              </div>
              <ul className="req-list">
                {REQUIREMENTS.map((r) => (
                  <li className="req-item" key={r.h}>
                    <div className="req-ic" aria-hidden="true">
                      <Ic name={r.icon} />
                    </div>
                    <div className="req-body">
                      <h4>{r.h}</h4>
                      <p>{r.p}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </Reveal>
          </div>
        </section>

        {/* ============ FAQ ============ */}
        <section className="section bg-pale" id="faq">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">よくある質問</span>
              <h2>業者向けよくある質問</h2>
            </div>
            <div style={{ maxWidth: 760, margin: "0 auto" }}>
              <FaqAccordion items={FAQ_ITEMS} defaultOpen={null} />
            </div>
          </div>
        </section>

        {/* ============ 登録フォーム ============ */}
        <section className="section" id="register">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">お申し込み</span>
              <h2>業者登録を申し込む</h2>
              <p className="sub">内容を確認のうえ、担当者よりご連絡いたします。</p>
            </div>

            <Reveal className="reg-card">
              {!submitted ? (
                <form onSubmit={onSubmit} noValidate>
                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="company">
                        会社名・屋号<span className="req">必須</span>
                      </label>
                      <input
                        type="text"
                        id="company"
                        name="company"
                        placeholder="株式会社〇〇"
                        className={invClass("company").trim()}
                        value={form.company}
                        onChange={(e) => update("company", e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="rep">
                        担当者名<span className="req">必須</span>
                      </label>
                      <input
                        type="text"
                        id="rep"
                        name="rep"
                        placeholder="山田 太郎"
                        className={invClass("rep").trim()}
                        value={form.rep}
                        onChange={(e) => update("rep", e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="rep-name">
                        代表者名<span className="req">必須</span>
                      </label>
                      <input
                        type="text"
                        id="rep-name"
                        name="rep-name"
                        placeholder="代表取締役 山田 太郎"
                        className={invClass("repName").trim()}
                        value={form.repName}
                        onChange={(e) => update("repName", e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="registered-address">
                        法人登録住所<span className="req">必須</span>
                      </label>
                      <input
                        type="text"
                        id="registered-address"
                        name="registered-address"
                        placeholder="東京都千代田区〇〇1-2-3"
                        className={invClass("registeredAddress").trim()}
                        value={form.registeredAddress}
                        onChange={(e) => update("registeredAddress", e.target.value)}
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
                      placeholder="info@company.co.jp"
                      className={invClass("email").trim()}
                      value={form.email}
                      onChange={(e) => update("email", e.target.value)}
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="phone">
                      電話番号<span className="req">必須</span>
                    </label>
                    <input
                      type="tel"
                      id="phone"
                      name="phone"
                      placeholder="03-0000-0000"
                      className={invClass("phone").trim()}
                      value={form.phone}
                      onChange={(e) => update("phone", e.target.value)}
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="biz-type">
                      事業形態<span className="req">必須</span>
                    </label>
                    <div className="select-wrap">
                      <select
                        id="biz-type"
                        name="biz-type"
                        className={invClass("bizType").trim()}
                        value={form.bizType}
                        onChange={(e) => update("bizType", e.target.value)}
                      >
                        <option value="" disabled>
                          選択してください
                        </option>
                        <option value="corp">法人</option>
                        <option value="sole">個人事業主</option>
                      </select>
                    </div>
                  </div>

                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="license-number">
                        古物商許可番号<span className="req">必須</span>
                      </label>
                      <input
                        type="text"
                        id="license-number"
                        name="license-number"
                        placeholder="東京都公安委員会 第XXXXXXXXXX号"
                        className={invClass("licenseNumber").trim()}
                        value={form.licenseNumber}
                        onChange={(e) => update("licenseNumber", e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="invoice-number">
                        インボイス制度登録番号<span className="opt">任意</span>
                      </label>
                      <input
                        type="text"
                        id="invoice-number"
                        name="invoice-number"
                        placeholder="T1234567890123"
                        value={form.invoiceNumber}
                        onChange={(e) => update("invoiceNumber", e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="area">
                      主な対応エリア<span className="req">必須</span>
                    </label>
                    <div className="select-wrap">
                      <select
                        id="area"
                        name="area"
                        className={invClass("area").trim()}
                        value={form.area}
                        onChange={(e) => update("area", e.target.value)}
                      >
                        <option value="" disabled>
                          選択してください
                        </option>
                        <option value="tokyo">東京都</option>
                        <option value="chiba">千葉県</option>
                        <option value="saitama">埼玉県</option>
                        <option value="kanagawa">神奈川県</option>
                        <option value="multi">複数都県</option>
                      </select>
                    </div>
                  </div>

                  <div className="biz-bank-section">
                    <h4 className="biz-bank-heading">振込先情報</h4>
                    <p className="biz-bank-lead">
                      手数料の請求・精算のためにお伺いします。審査結果の通知前に請求は発生しません。
                    </p>
                    <p className="biz-bank-note">※お申し込み内容の確認と、手数料の請求・精算に関する連絡（返金が生じた場合の振込先を含む）にのみ使用します</p>

                    <div className="field-row">
                      <div className="field">
                        <label htmlFor="bank-name">
                          銀行名<span className="req">必須</span>
                        </label>
                        <input
                          type="text"
                          id="bank-name"
                          name="bank-name"
                          placeholder="〇〇銀行"
                          className={invClass("bankName").trim()}
                          value={form.bankName}
                          onChange={(e) => update("bankName", e.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="branch-name">
                          支店名<span className="req">必須</span>
                        </label>
                        <input
                          type="text"
                          id="branch-name"
                          name="branch-name"
                          placeholder="〇〇支店"
                          className={invClass("branchName").trim()}
                          value={form.branchName}
                          onChange={(e) => update("branchName", e.target.value)}
                        />
                      </div>
                    </div>

                    <div className="field-row">
                      <div className="field">
                        <label htmlFor="account-type">
                          預金種別<span className="req">必須</span>
                        </label>
                        <div className="select-wrap">
                          <select
                            id="account-type"
                            name="account-type"
                            className={invClass("accountType").trim()}
                            value={form.accountType}
                            onChange={(e) => update("accountType", e.target.value)}
                          >
                            <option value="" disabled>
                              選択してください
                            </option>
                            <option value="ordinary">普通</option>
                            <option value="checking">当座</option>
                          </select>
                        </div>
                      </div>
                      <div className="field">
                        <label htmlFor="account-number">
                          口座番号<span className="req">必須</span>
                        </label>
                        <input
                          type="text"
                          id="account-number"
                          name="account-number"
                          placeholder="1234567"
                          className={invClass("accountNumber").trim()}
                          value={form.accountNumber}
                          onChange={(e) => update("accountNumber", e.target.value)}
                        />
                      </div>
                    </div>

                    <div className="field">
                      <label htmlFor="account-holder">
                        口座名義<span className="req">必須</span>
                      </label>
                      <input
                        type="text"
                        id="account-holder"
                        name="account-holder"
                        placeholder="カ）〇〇"
                        className={invClass("accountHolder").trim()}
                        value={form.accountHolder}
                        onChange={(e) => update("accountHolder", e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="cats">
                      得意なカテゴリ<span className="opt">任意</span>
                    </label>
                    <input
                      type="text"
                      id="cats"
                      name="cats"
                      placeholder="例：家電・ブランド品・家具"
                      value={form.cats}
                      onChange={(e) => update("cats", e.target.value)}
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="message">
                      ご質問・備考<span className="opt">任意</span>
                    </label>
                    <textarea
                      id="message"
                      name="message"
                      placeholder="ご質問や確認したいことがあればご記入ください。"
                      value={form.message}
                      onChange={(e) => update("message", e.target.value)}
                    />
                  </div>

                  <div className={`check-field${invalid.has("agree") ? " is-invalid" : ""}`}>
                    <input
                      type="checkbox"
                      id="agree"
                      name="agree"
                      checked={form.agree}
                      onChange={(e) => update("agree", e.target.checked)}
                    />
                    {/* 同意リンクは 3 本とも /terms を指していたため、それぞれの正しい文書へ配線し直す */}
                    <label htmlFor="agree">
                      <Link href="/legal">特定商取引法に基づく表記</Link>・
                      <Link href="/privacy">プライバシーポリシー</Link>および
                      <Link href="/terms">業者利用規約</Link>に同意します
                    </label>
                  </div>

                  {submitError ? (
                    <p className="biz-submit-error" role="alert">
                      {submitError}
                    </p>
                  ) : null}

                  <div className="submit-area">
                    <button type="submit" className="btn-submit" disabled={busy}>
                      <SendIcon />
                      {busy ? "送信中…" : "登録を申し込む"}
                    </button>
                    <p className="submit-note">送信後、担当者より3営業日以内にご連絡します。</p>
                  </div>
                </form>
              ) : (
                <div className="thanks" style={{ display: "block" }}>
                  <div className="thanks-ic">
                    <Ic name="check-circle" />
                  </div>
                  <h3>お申し込みを受け付けました</h3>
                  {/* r10 H4 是正: 旧CTAは「招待コードでアカウントを作成」を主導線として押し出しており、
                      まだコードが手元に無い申込直後の事業者がアカウント作成に進んで詰まっていた。
                      次の行動は「承認メールを待つ」であることを本文で明示し、リンクは
                      コードが届いた後の入口として説明付きで残す。 */}
                  <p>
                    ご入力内容を確認のうえ、担当者より3営業日以内にメールでご連絡します。
                    <br />
                    <strong>承認メールに記載の招待コードでアカウントを作成してください（メール到着までお待ちください）。</strong>
                  </p>
                  <p style={{ fontSize: 13, lineHeight: 1.9, marginBottom: 10 }}>
                    招待コードがお手元に届いている方は、こちらからアカウントを作成できます。
                  </p>
                  <Link href="/operator/signup" className="btn btn-ghost btn-lg" style={{ marginBottom: 10 }}>
                    招待コードでアカウントを作成
                    <Ic name="arrow" />
                  </Link>
                  <Link href="/" className="btn btn-ghost btn-lg">
                    トップページへ戻る
                  </Link>
                </div>
              )}
            </Reveal>
          </div>
        </section>
      </main>

      {/* ============ モバイル固定バー（BARE ページなので共通 .dock は描かれない） ============ */}
      <a href="#register" className="biz-dock">
        <SendIcon />
        業者登録を申し込む
      </a>

      {/* ============ FOOTER ============ */}
      <footer className="footer">
        <div className="container">
          <div className="footer-grid">
            <div>
              {/* r2 M2 是正: 共通 .footer は白地なので variant="white" だと明朝の「カタヅケ」が
                  白抜きで消え、--lime の小さな英字「KATAZUKE」だけが残っていた。共通 SiteFooter と
                  同じ brand（墨の明朝 ＋ --primary の英字ラベル）・同じ size に揃える。 */}
              <Link href="/" className="logo footer-logo" aria-label="カタヅケ トップへ">
                <KdzLogo size={22} />
              </Link>
              <p className="about">
                家まるごと、まとめて片付け買取。業者が買取総額で競い合う、営業電話に追われない不用品買取マッチング。東京・千葉・埼玉・神奈川対応。
              </p>
            </div>
            <div>
              <h5>業者の方へ</h5>
              <ul>
                <li><a href="#merit">参加メリット</a></li>
                <li><a href="#flow">掲載の流れ</a></li>
                <li><a href="#requirements">登録要件</a></li>
                <li><a href="#register">業者登録を申し込む</a></li>
              </ul>
            </div>
            <div>
              <h5>ユーザーの方へ</h5>
              <ul>
                <li><Link href="/#flow">使い方</Link></li>
                <li><Link href="/#auction">仕組み</Link></li>
                <li><Link href="/#trust">安心の取り組み</Link></li>
                <li><Link href="/faq">よくある質問</Link></li>
              </ul>
            </div>
            <div>
              <h5>カタヅケについて</h5>
              <ul>
                <li><Link href="/#founder">運営者メッセージ</Link></li>
                <li><Link href="/faq">お問い合わせ</Link></li>
                <li><Link href="/legal">特定商取引法に基づく表記</Link></li>
                <li><Link href="/privacy">プライバシーポリシー</Link></li>
                <li><Link href="/terms">利用規約</Link></li>
              </ul>
            </div>
          </div>
          <div className="footer-bottom">
            <span>© 2026 カタヅケ</span>
            <span>東京都・千葉県・埼玉県・神奈川県（順次拡大）</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
