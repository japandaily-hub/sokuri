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
import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { Notice } from "@/components/kdz/Notice";
import { Reveal, RevealLines, FaqAccordion } from "@/components/kdz/interactions";
import { submitOperatorApplication, toDisplayMessage } from "@/lib/katadzuke-api";
import { MODEL_CASE_CHIP, VENDOR_CASES, VENDOR_CASE_NOTE } from "@/lib/model-cases";
import { useBankSuggestions, useBranchSuggestions } from "@/lib/bank-lookup";

/**
 * 銀行名・支店名のオートコンプリート入力欄（bank.teraren.com 公開APIの候補を表示）。
 * postal-lookup と同じ「入力の補助」の思想: 候補が取得できない・0件でも、
 * 通常の <input> と同じように自由入力を続けられる（何も表示しないだけ）。
 */
function BankAutocompleteInput({
  id,
  value,
  onChange,
  onSelect,
  suggestions,
  loading,
  placeholder,
  hasError,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  onSelect: (suggestion: { code: string; name: string }) => void;
  suggestions: { code: string; name: string }[];
  loading: boolean;
  placeholder?: string;
  hasError?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const listboxId = `${id}-listbox`;

  useEffect(() => {
    setHighlight(-1);
  }, [suggestions]);

  useEffect(() => {
    if (!open) return;
    const onDocPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocPointerDown);
    return () => document.removeEventListener("mousedown", onDocPointerDown);
  }, [open]);

  const commit = (s: { code: string; name: string }) => {
    onSelect(s);
    setOpen(false);
  };

  return (
    <div className="bank-autocomplete" ref={wrapRef}>
      <input
        type="text"
        id={id}
        name={id}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open && suggestions.length > 0}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={highlight >= 0 ? `${id}-option-${highlight}` : undefined}
        className={hasError ? "has-error" : undefined}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          if (suggestions.length > 0) setOpen(true);
        }}
        onBlur={(e) => {
          // Tab等でフォーカスが自コンポーネント外へ移った場合は候補を閉じる。候補クリックは
          // onMouseDown(preventDefault)で先に確定させているため、ここでの close と競合しない。
          if (wrapRef.current && wrapRef.current.contains(e.relatedTarget as Node)) return;
          setOpen(false);
        }}
        onKeyDown={(e) => {
          if (!open || suggestions.length === 0) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => (h + 1) % suggestions.length);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => (h <= 0 ? suggestions.length - 1 : h - 1));
          } else if (e.key === "Enter") {
            if (highlight >= 0) {
              e.preventDefault();
              commit(suggestions[highlight]);
            }
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && suggestions.length > 0 ? (
        <ul className="bank-autocomplete-list" role="listbox" id={listboxId}>
          {suggestions.map((s, i) => (
            <li
              key={s.code}
              id={`${id}-option-${i}`}
              role="option"
              aria-selected={i === highlight}
              className={`bank-autocomplete-option${i === highlight ? " is-active" : ""}`}
              onMouseDown={(e) => {
                // クリックより先に input の blur が発火し候補が消えてしまうため mousedown で確定する。
                e.preventDefault();
                commit(s);
              }}
              onMouseEnter={() => setHighlight(i)}
            >
              {s.name}
            </li>
          ))}
        </ul>
      ) : null}
      {loading ? <div className="field-hint">候補を検索しています…</div> : null}
    </div>
  );
}

/** 3桁区切り。ロケール実装に依存しないよう自前で整形する（SSR とクライアントで同じ文字列にするため）。 */
function yen(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** モデルケース1件あたりの成約手数料（買取金額の8%）を百円単位に丸めた概算。
 *  利得側の数値（成約・買取総額・引き取り）と同じ視野に業者の負担を置くための表示で、
 *  率・課税条件ともヒーロー／ASSURANCES 05／FAQ の既存表記の再掲。新しい約束・割引は足さない。 */
function feeApprox(amount: number): string {
  return yen(Math.round((amount * 0.08) / 100) * 100);
}

/** 同じ概算の税込（消費税10%）表示。r5 #31: 例示が税別だけでは実際の支払額が読めないため、
 *  実額が出る .vc-fee にだけ併記する。率（8%）と課税条件の表記自体は変えない。 */
function feeApproxIncl(amount: number): string {
  return yen(Math.round((amount * 0.08 * 1.1) / 100) * 100);
}

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
  { href: "#flow", label: "入札の流れ" },
  { href: "#requirements", label: "登録要件" },
  { href: "#faq", label: "よくある質問" },
];

/** 数値帯（事実ベースのサービス条件のみ。計測実績風の数値は景表法（優良誤認）回避のため
 *  実データ集計が配線されるまで掲載しない） */
const STATS: { num: string; unit: string; label: string }[] = [
  /* R4 E.2-2: 業者が最初に見る数字を「下見0回」にする（下見の空振りが最大の痛点のため）。
     並び替えのみで、項目・文言・値は一切変えない。 */
  { num: "0", unit: "回", label: "下見・現地調査" },
  { num: "4", unit: "都県", label: "東京・千葉・埼玉・神奈川" },
  { num: "0", unit: "円", label: "初期費用・月額費用" },
  { num: "8", unit: "%", label: "成約時の手数料のみ" },
  { num: "12", unit: "カテゴリ", label: "家電からブランド品まで対応" },
];

/** 仕入れる3つの理由（画像付き3カラム）。効果の断定は避け、条件と手順で説明する。 */
const REASONS: { n: string; tag: string; img: string; h: ReactNode; p: string }[] = [
  {
    n: "01",
    tag: "まとめ",
    img: "biz-reason-bulk",
    h: "まとめ買取で、1回の訪問にまとまる",
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
  },
  {
    n: "03",
    tag: "入札制",
    img: "biz-reason-route",
    h: "入札制で、自社の基準に合う案件だけ選べる",
    p: "複数業者が買取総額で競う入札制。過度な価格競争ではなく、出品された品物全体の価値に対して金額を提示できます。自社の買取基準や対応エリアに合った案件だけに入札可能です。",
  },
];

/** 安心して参加できる理由（04〜06・ヘアラインリスト） */
const ASSURANCES: { n: string; h: string; p: string }[] = [
  {
    n: "04",
    h: "一斉の営業電話なし",
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

/** 業者視点のフロー（4ステップ）。
 *  r5 #2/#15/#21/#34: 旧 3D アイコン（/img/real/how-camera・how-trend・how-crown・how-truck）を外した。
 *  理由は3つ: ①素材集の借り物に見え、他ページのフォトリアル生活空間シリーズから浮いていた
 *  ②「選ばれる＝王冠」は「ユーザーが1社を選択」と結び付かない広告表現 ③右肩上がりの棒グラフを
 *  買取総額の近傍に置くと、集計統計を出さない方針の隣で成果の上昇を示唆する（有利誤認の入口）。
 *  差し替え素材（入札票が並ぶ机上・1枚だけ選ばれた札）は今回の画像セットに無いため、
 *  #15 の代替どおり番号＋見出し＋本文のヘアラインリストにして情報量は落とさない。 */
const FLOW: { n: string; h: string; p: string }[] = [
  { n: "1", h: "案件を確認", p: "出品された案件の写真・品目リストを確認し、入札する案件を選びます。" },
  { n: "2", h: "買取総額で入札", p: "出品された商品すべてに対して、買取総額を提示。他社と競い合います。" },
  { n: "3", h: "ユーザーが1社を選択", p: "すべての入札がユーザーに提示され、ユーザーが見比べて1社を選びます。選ばれると連絡先が開示されます。" },
  { n: "4", h: "訪問・引き取り", p: "成約後に訪問日時を決定。まとめて引き取りを行います。" },
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
  { q: "入札した案件は、すべてユーザーと連絡を取れますか？", a: "ユーザーが届いた入札を見比べて1社を選びます。選ばれた場合のみ連絡先が開示され、取引に進めます。選ばれなかった入札は自動でお断りとなり、ユーザーへの連絡はできません。" },
  { q: "入札した金額はあとから変更できますか？", a: "ユーザーが業者を選ぶまでの間、案件詳細から入札額を何度でも引き上げられます（引き下げはできません）。他社の入札額は匿名で表示されます（社名・コメントは非開示）。" },
  { q: "他社の入札額は見えますか？", a: "案件詳細で「現在の最高額」と、匿名化された他社の入札額（社名・コメントは非開示）を確認できます。自社の入札が最高額でない場合は差額も表示されるため、引き上げの判断材料としてご利用いただけます。" },
  { q: "エリア外の案件に入札できますか？", a: "現在は東京都・千葉県・埼玉県・神奈川県が対応エリアです。エリア外への訪問買取は受け付けていません。" },
  { q: "最終的な買取額は入札額と異なってもいいですか？", a: "提示した買取金額を下回る変更は、査定現場で商品を確認し、理由を明示したうえで顧客の了解を得た場合にのみ可能です。顧客の同意なく一方的に減額することはできません。" },
  { q: "審査にはどのくらい時間がかかりますか？", a: "お申し込みから通常3営業日以内に審査結果をご連絡します。古物商許可証の確認が必要なため、書類に不備がある場合は時間がかかることがあります。" },
  // r10 H2 是正: 依頼者側には「代金の受け取り方法は業者とチャットで調整」と案内しているのに、
  // 業者向けの説明がどこにも無かった（当事者間精算であることを明示する）。
  { q: "買取代金はどのように支払いますか？", a: "買取代金はユーザーと直接精算します（現金またはお振込み。方法はチャットで調整してください）。カタヅケは送金を仲介しません。カタヅケがやり取りするのは成約時の手数料のみです。" },
  // r5 #30: 評価・口コミは成約したユーザーの投稿をそのまま掲載する方針のため、掲載される側から
  // 「事実と異なる投稿の扱い」が読めなかった（店の看板を預ける判断ができない）。
  // 削除の断定は運用として確認できていないので、受付窓口があることだけを書く。
  { q: "事実と異なる口コミが投稿された場合は？", a: "評価・口コミは、成約したユーザーの投稿をそのまま掲載する方針です。そのうえで、事実と異なる内容が含まれるとお考えの場合は、お問い合わせから内容をお知らせください。運営が個別に確認します。" },
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

/** 必須項目が未入力のときのインラインエラー文言。select 系は「選択」、それ以外は「入力」で言い切る。 */
const REQUIRED_MESSAGE: Partial<Record<keyof FormState, string>> = {
  company: "必須項目です",
  rep: "必須項目です",
  repName: "必須項目です",
  registeredAddress: "必須項目です",
  email: "必須項目です",
  phone: "必須項目です",
  bizType: "選択してください",
  area: "選択してください",
  licenseNumber: "必須項目です",
  bankName: "必須項目です",
  branchName: "必須項目です",
  accountType: "選択してください",
  accountNumber: "必須項目です",
  accountHolder: "必須項目です",
};

/** 古物商許可番号は必須チェックとは別に、文字数の下限を持つ（形式チェック）。 */
const LICENSE_NUMBER_MIN_LENGTH = 5;
const LICENSE_NUMBER_TOO_SHORT_MESSAGE = `古物商許可番号は${LICENSE_NUMBER_MIN_LENGTH}文字以上で入力してください`;
const AGREE_REQUIRED_MESSAGE = "内容をご確認のうえ、チェックを入れてください";

export default function BusinessPage() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  /* キー→エラー文言。値が無ければエラー無し（フィールド直下にそのまま表示できるよう
     真偽値の Set ではなく文言そのものを保持する）。 */
  const [invalid, setInvalid] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // 銀行名の候補から選択した場合にだけ入る全銀コード（支店検索の絞り込みに使う）。
  // 手入力・未選択の間は null のままで、その場合は支店名も自由入力のまま候補を出さない。
  const [bankCode, setBankCode] = useState<string | null>(null);
  const bankSuggestions = useBankSuggestions(form.bankName);
  const branchSuggestions = useBranchSuggestions(bankCode, form.branchName);
  /* R4 r4 #11/#17: 固定バーが常時出ているため、ヒーローのリード文に重なり（390px 実測で
     「…カタヅケで開拓する。」の次の行が隠れる）、同じ文言のボタンが画面に2つ並んでいた。
     監視対象はヒーロー節そのもの（CTA 単体だと、390px では画像 487px の下にある CTA が
     初期表示で画面外のため固定バーが即出て h1 に重なる）。ヒーローが一部でも見えている間は
     出さず、読み終えてから確約 CTA を出す。IntersectionObserver が無い環境では常時表示。 */
  const heroRef = useRef<HTMLElement | null>(null);
  const [dockOn, setDockOn] = useState(false);
  useEffect(() => {
    const el = heroRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setDockOn(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => setDockOn(!entries[0].isIntersecting),
      { threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (invalid[key]) {
      setInvalid((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    REQUIRED_KEYS.forEach((k) => {
      const v = form[k];
      if (typeof v === "string" && !v.trim()) next[k] = REQUIRED_MESSAGE[k] ?? "必須項目です";
    });
    if (form.licenseNumber.trim() && form.licenseNumber.trim().length < LICENSE_NUMBER_MIN_LENGTH) {
      next.licenseNumber = LICENSE_NUMBER_TOO_SHORT_MESSAGE;
    }
    if (!form.agree) next.agree = AGREE_REQUIRED_MESSAGE;
    setInvalid(next);
    if (Object.keys(next).length > 0) return;

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

  const invClass = (key: string) => (invalid[key] ? " has-error" : "");
  /** フィールド直下に置くインラインエラー。無ければ何も描画しない
   *  （JSX を返す関数であってコンポーネントではないため、レンダーごとの再定義でも再マウントは起きない）。 */
  const fieldError = (key: string) => (invalid[key] ? <p className="field-error">{invalid[key]}</p> : null);

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
            aria-controls="mobile-menu"
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
          {/* r5 #16 と同じ理由（ページ内アンカーに送信アイコンを付けない） */}
          <Ic name="arrow" />
          業者登録を申し込む
        </a>
      </div>

      <main id="main">
        {/* ============ HERO ============
            ファーストビューのため Reveal は付けない（無 JS でも読める）。
            画像は LCP 候補なのでページ内で唯一 eager + fetchPriority="high"。 */}
        <section className="biz-hero" ref={heroRef}>
          <div className="container">
            <div className="media-split media-split--rev biz-hero-split">
              <div className="img-frame img-frame--2x3 img-frame--pale biz-hero-fig sp-bleed">
                {/* eslint-disable @next/next/no-img-element */}
                {/* R4 D.2 #5: 素材を人物入り（仕分けた棚の前に立つスタッフ）に差し替えたため、
                    「誰が入札する側なのか」を伝える意味を持つ画像になった。alt は spec_people.json の
                    文言をそのまま使う。r2 H4 で alt="" にした理由（取得失敗時に alt 文が枠内へ流れる）は、
                    共有部品側の `.img-frame img{color:transparent;font-size:0}` で解消済み。
                    枠 2:3 と素材 1024x1536 は AR 一致で無トリミングのため --pos は書かない
                    （859px 以下の 4:5 だけ business.css で --pos:50% 42% を与える）。 */}
                <img
                  src="/img/v2/biz-hero.webp"
                  width={900}
                  height={1350}
                  alt="仕分けた棚の前に立つリユース業者のスタッフ（イメージ）"
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
                  <strong>買取金額の8%（税別・消費税を別途加算）のみ</strong>です。
                </p>
                {/* R4 r4 #11: ヒーロー・固定バー・ページ末尾の3か所に同じ「業者登録を申し込む」が
                    並び、どれが正規の入口か分からなかった。確約の CTA は固定バーとページ末尾
                    （#register）に絞り、ヒーローの2本目は先に条件を確かめる導線にする。 */}
                <div className="biz-hero-cta">
                  <a href="#merit" className="btn btn-primary btn-lg">
                    参加メリットを見る
                    <Ic name="arrow" />
                  </a>
                  <a href="#requirements" className="btn btn-ghost btn-lg btn-swipe">
                    登録要件を確認する
                  </a>
                </div>
                {/* R4 r4 #22: 申し込みの所要時間・審査期間・入札が使えるようになる時点を、
                    CTA を押す前に1行で置く。E.2-1（CTA 直下に条件1行を足さない）は費用条件の
                    反復と 8% 欠落による有利誤認を避けるための判断なので、費用に触れない
                    手続きの1行はその対象外。件数は実際の必須項目数（14）。 */}
                <p className="biz-hero-steps">
                  入力は3ステップ（必須14項目）。送信後3営業日以内にご連絡します。審査の通過後に入札できるようになります。
                  {/* r5 #25: 依頼者が「業者の方へ」から入ってしまったとき、ヒーロー付近に
                      戻る導線がなく業者向けの条件だけを読み続けることになっていた。 */}
                  <Link href="/" className="biz-hero-alt">
                    ご依頼（売りたい）の方はこちら →
                  </Link>
                </p>
                {/* 最終検査（legal）: 顔のある人物を2点出すページなので、可視の打消しを /vendors・/login と同じ文言で置く */}
                <p className="biz-photo-note">※ 写真はイメージです。</p>
              </div>
            </div>
          </div>
        </section>

        {/* ============ β期間の注記（8% を書く全箇所で条件を同一視野に置く） ============ */}
        <section className="biz-beta" aria-label="手数料について">
          <div className="container">
            <p className="biz-beta-note">
              いまは手数料0円（β期間）。請求開始は事前にメールでお知らせします。成約時8%（税別・消費税別途）。
              {/* r6 #18: 登録後に案件が少ないことを先に伝える（登録前に最も知りたい「案件がどれくらい
                  出てくるか」に触れる行がなく、「話が違う」と受け取られる余地があった）。
                  集計値・目標件数は書かない。指摘の「件数が増え次第メールでお知らせします」は
                  未実装の通知の約束になるため書かない（CONSTRAINTS §3）。 */}
              <span className="biz-beta-status">
                サービスは公開前の準備段階のため、いまご覧いただける案件数は限られます。
              </span>
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

        {/* ============ 章の切れ目（写真帯・veil .65 = 見出し＋14px 以上の注記） ============
            R4 D.2 #6: 素材が人物入り（作業台で仕分ける2人）に替わるため、縦位置を持つ
            .hero-band--face を足す（横位置の修飾子は帯が常に素材より横長で効かないため無い）。 */}
        <section className="hero-band hero-band--mid hero-band--face biz-band-sorting">
          {/* eslint-disable @next/next/no-img-element */}
          <img
            src="/img/v2/biz-band-sorting.webp"
            width={1920}
            height={1088}
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
              <RevealLines mark="under" lines={["カタヅケで仕入れる、3つの理由"]} />
              <p className="sub">家まるごとの一括出品だからこそ、1回の訪問でまとめて仕入れられるルートになります。</p>
            </div>
            <div className="biz-reason-grid">
              {REASONS.map((r, i) => (
                <Reveal as="article" className="biz-reason" stagger={i} key={r.n}>
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

        {/* ============ 参加のモデルケース（架空） ============
            R4 C.2: 抽象（#merit の3つの理由）→ 具体（モデルケース）→ 手順（#flow）の順に読ませる。
            面は白のまま（bg-pale を付けない）。直後の #flow が淡青なので章の境界はそちらで立つ。
            景表法: ①架空であることの明示 .model-chip を金額より手前・カード先頭に、
            ②注記 .model-note をカード群より手前に置く。③サイト全体の集計値（累計・平均・成約率・
            登録業者数）は出さない。④入札数は持たない（成約数と並べると割り算で成約率が出るため）。
            ⑤業者が負担する成約手数料 .vc-fee を利得側の数値と同一視野に置く。 */}
        <section className="section vc-cases" id="model-cases" aria-labelledby="vc-cases-h">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">参加のモデルケース</span>
              <h2 id="vc-cases-h">こんな使い方をイメージしています</h2>
              <p className="sub">参加した場合の使われ方をイメージしていただくための、架空のモデルケースです。</p>
            </div>
            <p className="model-note" role="note">{VENDOR_CASE_NOTE}</p>
            <div className="vc-grid">
              {VENDOR_CASES.map((v) => (
                <article className="vc-card" key={v.id}>
                  <span className="model-chip">{MODEL_CASE_CHIP}</span>
                  <div className="vc-head">
                    <div className="img-frame img-frame--1x1 vc-fig">
                      {/* eslint-disable @next/next/no-img-element */}
                      {/* 表示は 220px（859px 以下 140px）。原寸 800 では表示幅の2倍を超えるため
                          440px の派生 webp を参照する。1:1 枠 × 1:1 素材はトリミングが起きないので
                          --pos は書かない（書いても効かない）。円形にもしない。 */}
                      <img
                        src={`/img/v2/${v.portrait}-440.webp`}
                        width={440}
                        height={440}
                        alt={v.portraitAlt}
                        loading="lazy"
                        decoding="async"
                      />
                      {/* eslint-enable @next/next/no-img-element */}
                    </div>
                    <div className="vc-meta">
                      <h3>{v.shop}</h3>
                      <p className="vc-attr">
                        {v.area}／{v.kind}
                      </p>
                    </div>
                  </div>
                  {/* R4 r4 #3: 「引き取り 4回／成約 4件」は定義上つねに同数で、行数を稼いだ表に
                      見えていた。引き取りの行を削り、サービスの仕様である「下見・現地調査 0回」を
                      表の1行目に格上げする（表の上の小さな文から昇格）。
                      #20（入札件数の行を足して勝率を読ませる）は採らない: 入札数と成約数を並べると
                      読者が割り算で成約率を得るため、CONSTRAINTS R4 §2 と model-cases.ts の
                      「bids は持たない」ガードに反する。
                      「0回」が「一切現物を見ない」と読まれないよう（現物査定は成約後）を必ず伴わせる。 */}
                  {/* r5 #10/#12: 「下見・現地調査 0回」は架空値ではなくサービスの仕様なので、
                      R4 C.2 の指定どおり dl の外・.vc-facts-label の上に独立した事実行として出す
                      （行内に長い注記が入って行高が他行の2倍になり、台帳のリズムが崩れていた）。 */}
                  <p className="vc-visit">下見・現地調査は0回（現物査定は成約後）。</p>
                  <p className="vc-facts-label">ある1か月のイメージ</p>
                  <dl className="vc-facts">
                    <div>
                      <dt>成約</dt>
                      <dd>
                        <b>{v.month.deals}</b>
                        <span>件</span>
                      </dd>
                    </div>
                    <div>
                      {/* r6 #12: 「成約1件あたり」は同カードの「成約 4件」と並ぶと平均値（集計統計）に
                          読める。R4 の禁止語は「平均」「累計」だが同義に読まれる語は避け、単一の
                          例示であることが語尾で分かる表現にする。数値・注記・チップは変えない。 */}
                      <dt>このケースの1件の買取総額（例）</dt>
                      <dd>
                        <b>{yen(v.month.amount)}</b>
                        <span>円</span>
                      </dd>
                    </div>
                  </dl>
                  {/* r5 #4/#12: 現物確認の但し書き（R4 r4 #21）は、カード内で表の下に注記が
                      3段続く原因だったため節末（.vc-terms）に1回だけ置く。カード内は
                      水準差の1行 ＋ 手数料1行 ＋ 引用に絞る。 */}
                  {/* r5 #32: /examples の依頼者モデルケース（31,000〜148,000円）と水準が違って見える
                      理由を、金額の直下に1行だけ置く。集計値ではなく既存モデルケースの範囲の再掲。
                      r6 #1/#9: 本文の中に生の URL パス（/examples）が露出していたため、
                      「利用イメージ（モデルケース）」をリンクテキストにしてパスを本文から外す。
                      数値・範囲・約束は変えない（/examples 側の CASES と同じ 31,000〜148,000 円）。 */}
                  <p className="vc-range">
                    品物の内容により幅があります（
                    <Link href="/examples">利用イメージ（モデルケース）</Link>
                    では31,000〜148,000円）。
                  </p>
                  {/* r5 #31: 例示が税別だけだと実際の支払額が読めないため、実額が出るこの箇所だけ
                      税込（消費税10%）を併記する。率とヒーロー・数値帯の 8% 表記は変えない。 */}
                  <p className="vc-fee">
                    費用は成約時の買取金額の8%（税別・消費税を別途加算）のみ。この例では1件あたり約
                    {feeApprox(v.month.amount)}円（消費税10%込みで約{feeApproxIncl(v.month.amount)}円）にあたります。
                  </p>
                  <blockquote className="vc-quote">
                    <p>{v.quote}</p>
                    <footer>{v.speaker}</footer>
                  </blockquote>
                </article>
              ))}
            </div>
            {/* r6 #19: 「何社と競るのか」の手触りが業者向けページに無かったため、定性1行を置く。
                件数・平均・上限は書かない（数値を出すと入札数の集計値の提示になる）。
                カードごとに繰り返すと2枚の非対称になるため、節末に1回だけ置く。 */}
            <p className="vc-bids">
              1件の案件には複数の業者が入札できます（入札の数は案件によって異なります）。
            </p>
            {/* r5 #4: 現物確認の但し書きは節末に1回だけ置く（カードごとに繰り返すと
                表の下に細字の注記が3段続き、読む前に疲れる）。文面は R4 r4 #21 のまま、
                FAQ「最終的な買取額は入札額と異なってもいいですか？」と同義。 */}
            <p className="model-note vc-terms" role="note">
              現物確認で条件が合わない場合、ユーザーが取引を断ることがあります。提示額を下回る変更は、
              理由を明示してユーザーの了解を得た場合にのみ可能です。
            </p>
          </div>
        </section>

        {/* ============ 業者視点のフロー ============ */}
        <section className="section bg-pale" id="flow">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">入札の流れ</span>
              <RevealLines mark="under" lines={["入札から引き取りまでの流れ"]} />
              <p className="sub">登録後はシンプルな4ステップ。下見なし・一斉の営業電話なしで進められます。</p>
            </div>
            {/* r5 #15: 画像を外し、番号タイル＋見出し＋本文のヘアラインリストにする（手順なので ol）。 */}
            <ol className="biz-flow">
              {FLOW.map((f, i) => (
                <Reveal as="li" className="biz-step" stagger={i} key={f.n}>
                  <div className="biz-step-n" aria-hidden="true">{f.n}</div>
                  <h4>{f.h}</h4>
                  <p>{f.p}</p>
                </Reveal>
              ))}
            </ol>
          </div>
        </section>

        {/* ============ 登録要件 ============ */}
        <section className="section" id="requirements">
          <div className="container">
            <div className="section-head">
              <span className="eyebrow">ご利用条件</span>
              <h2>登録要件</h2>
              <p className="sub">ユーザーの安心のため、登録時に以下を確認させていただきます。</p>
            </div>
            <Reveal className="media-split media-split--rev biz-req-split">
              <Reveal as="figure" variant="zoom" className="img-frame img-frame--1x1 img-frame--pale biz-req-fig sp-bleed">
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
              </Reveal>
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

            {/* セキュリティレビュー対応: 個人情報・利用規約同意チェックボックスを含む申込フォーム全体を
                スクロール演出でラップすると、JS遅延時に「同意UIが不可視だが操作可能」な状態が生じうるため、
                演出をかけない素のdivに変更する(演出はsection-headの見出し側にのみ残す)。 */}
            <div className="reg-card">
              {!submitted ? (
                <form onSubmit={onSubmit} noValidate>
                  {/* R4 r4 #22: フォームの長さと審査期間の予告を冒頭に置く。会社情報 →
                      許可・エリア → 精算の3見出しに分け、どこまで進んだか分かるようにする。 */}
                  <p className="biz-form-flow">
                    入力は3ステップ（必須14項目）。送信後3営業日以内にご連絡します。審査の通過後に入札できるようになります。
                  </p>
                  {/* R4 r4 #23: 重い申込フォームだけが入口に見えていた。/operator/signup は招待コード
                      なしでもアカウントを作成でき、案件の閲覧まで進める（入札は審査の通過後。
                      lib/katadzuke-api.ts OPERATOR_CASE_VIEW_STATUSES の仕様）。役割差を1行添えて
                      軽い入口を併置する。 */}
                  {/* r5 #13: 退避路が説明の文中の小さなテキストリンクで、重さを感じた業者が
                      気付かなかった。説明の外・フォーム開始位置の直前に .btn-ghost で置く。 */}
                  <div className="biz-form-alt">
                    <p>案件を先に見たい方は、アカウントだけ作ることもできます（入札は審査の通過後）。</p>
                    <Link href="/operator/signup" className="btn btn-ghost btn-swipe">
                      まずアカウントだけ作って案件を見る
                    </Link>
                  </div>
                  <div className="biz-form-group">
                    <h4 className="biz-form-heading">
                      <span aria-hidden="true">1</span>
                      会社情報
                    </h4>
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
                        {fieldError("company")}
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
                        {fieldError("rep")}
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
                        {fieldError("repName")}
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
                        {fieldError("registeredAddress")}
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
                      {fieldError("email")}
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
                      {fieldError("phone")}
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
                      {fieldError("bizType")}
                    </div>
                  </div>

                  <div className="biz-form-group">
                    <h4 className="biz-form-heading">
                      <span aria-hidden="true">2</span>
                      許可・対応エリア
                    </h4>
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
                        {fieldError("licenseNumber")}
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
                      {fieldError("area")}
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
                  </div>

                  <div className="biz-bank-section">
                    {/* R4 r4 #10/#19: 初回接触の時点で口座を必須で聞く心理的負担が最大だったため、
                        ブロックをフォームの最後（会社情報・許可の後）へ移した。任意化・別ステップ化は
                        API 契約（submitOperatorApplication の bank_account は必須）の変更が必要なため
                        ここでは行わず、「いつ請求が始まるのか」を必須ラベルより先に読ませる。 */}
                    <h4 className="biz-bank-heading biz-form-heading">
                      <span aria-hidden="true">3</span>
                      精算（手数料の請求・返金）
                    </h4>
                    <p className="biz-bank-lead">
                      手数料の請求・精算（返金が生じた場合の振込先を含む）のために、口座情報をお伺いします。
                      お申し込みの時点では請求は発生せず、請求開始は事前にメールでお知らせします。
                    </p>
                    <p className="biz-bank-note">※お申し込み内容の確認と、手数料の請求・精算に関する連絡（返金が生じた場合の振込先を含む）にのみ使用します</p>
                    {/* r5 #27: 口座5項目は API 契約（submitOperatorApplication の bank_account）が
                        必須のため任意化できない。代わりに、口座を出さずに案件を見る道を
                        このブロックと同じ視野に置く（#13 の退避路と同じ行き先）。
                        「審査通過後に登録できます」は現在の実装で確認できないため書かない。 */}
                    <p className="biz-bank-alt">
                      口座の登録が難しい場合は、
                      <Link href="/operator/signup">アカウントだけ作って案件を見る</Link>
                      こともできます（入札は審査の通過後）。
                    </p>

                    <div className="field-row">
                      <div className="field">
                        <label htmlFor="bank-name">
                          銀行名<span className="req">必須</span>
                        </label>
                        <BankAutocompleteInput
                          id="bank-name"
                          value={form.bankName}
                          onChange={(v) => {
                            update("bankName", v);
                            setBankCode(null);
                          }}
                          onSelect={(s) => {
                            update("bankName", s.name);
                            setBankCode(s.code);
                          }}
                          suggestions={bankSuggestions.suggestions}
                          loading={bankSuggestions.loading}
                          placeholder="〇〇銀行"
                          hasError={!!invalid.bankName}
                        />
                        {fieldError("bankName")}
                      </div>
                      <div className="field">
                        <label htmlFor="branch-name">
                          支店名<span className="req">必須</span>
                        </label>
                        <BankAutocompleteInput
                          id="branch-name"
                          value={form.branchName}
                          onChange={(v) => update("branchName", v)}
                          onSelect={(s) => update("branchName", s.name)}
                          suggestions={branchSuggestions.suggestions}
                          loading={branchSuggestions.loading}
                          placeholder="〇〇支店"
                          hasError={!!invalid.branchName}
                        />
                        {fieldError("branchName")}
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
                        {fieldError("accountType")}
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
                        {fieldError("accountNumber")}
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
                      {fieldError("accountHolder")}
                    </div>
                  </div>

                  <div className={`check-field${invalid.agree ? " has-error" : ""}`}>
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
                      {/* r5 #29: /terms はタブ構成で、既定はユーザー規約に着地する。同意対象の
                          業者利用規約へ直接届くよう #biz アンカーへ配線する。 */}
                      <Link href="/terms#biz">業者利用規約</Link>に同意します
                    </label>
                    {fieldError("agree")}
                  </div>

                  {submitError ? <Notice tone="danger">{submitError}</Notice> : null}

                  <div className="submit-area">
                    <button type="submit" className="btn-submit" disabled={busy}>
                      <SendIcon />
                      {busy ? "送信中…" : "業者登録を申し込む"}
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
                    <strong>承認メールが届くまでお待ちください。届きましたら、記載の招待コードでアカウントを作成してください。</strong>
                  </p>
                  <p style={{ fontSize: 13, lineHeight: 1.9, marginBottom: 10 }}>
                    招待コードがお手元に届いている方は、こちらからアカウントを作成できます。
                  </p>
                  <Link href="/operator/signup" className="btn btn-ghost btn-lg btn-swipe" style={{ marginBottom: 10 }}>
                    招待コードでアカウントを作成
                    <Ic name="arrow" />
                  </Link>
                  <Link href="/" className="btn btn-ghost btn-lg btn-swipe">
                    トップページへ戻る
                  </Link>
                </div>
              )}
            </div>
          </div>
        </section>
      </main>

      {/* ============ モバイル固定バー（BARE ページなので共通 .dock は描かれない） ============
          R4 r4 #11/#17: ヒーローの CTA が見えている間は出さない（.is-on が付いたときだけ
          display:flex。CSS 側で閾値 859px にゲートしている）。 */}
      <a
        href="#register"
        className={`biz-dock${dockOn ? " is-on" : ""}`}
        aria-hidden={!dockOn}
        tabIndex={dockOn ? undefined : -1}
      >
        {/* r5 #16: 紙飛行機（送信）アイコンは、フォームへ移動するだけの導線を送信操作に見せる。
            ラベル・href は変えず、アイコンだけ右向き矢印にする。 */}
        <Ic name="arrow" />
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
                <li><a href="#flow">入札の流れ</a></li>
                <li><a href="#requirements">登録要件</a></li>
                <li><a href="#register">業者登録を申し込む</a></li>
                {/* r5 #18/#29: 業者が同意する文書への導線がページ内に無かった（同意チェックの
                    リンクだけ）。/terms の #biz アンカーへ1本置く。共通フッター
                    （components/kdz/chrome.tsx）側の1本はコア担当。 */}
                <li><Link href="/terms#biz">業者利用規約</Link></li>
              </ul>
            </div>
            <div>
              <h5>ユーザーの方へ</h5>
              <ul>
                {/* 2026-09-18 本採用: 新トップ(/lp移植)の対応セクションへ retarget
                    （#flow→#daily、#auction→#choose。#trust/#founder/#fee は同名のまま） */}
                <li><Link href="/#daily">使い方</Link></li>
                <li><Link href="/#choose">仕組み</Link></li>
                <li><Link href="/#trust">安心の取り組み</Link></li>
                <li><Link href="/faq">よくある質問</Link></li>
              </ul>
            </div>
            <div>
              <h5>カタヅケについて</h5>
              <ul>
                <li><Link href="/#founder">運営者メッセージ</Link></li>
                <li><Link href="/contact">お問い合わせ</Link></li>
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
