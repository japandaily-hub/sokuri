"use client";

/** よくある質問（FAQ）。デザインハンドオフ「よくある質問.html」由来。
 *  検索・カテゴリフィルタ・アコーディオン開閉を伴うためクライアントコンポーネント。
 *  ヘッダー/フッターは共通 SiteChrome が付与するため、ここでは <main id="main"> の中身のみを描画する。
 *  ビジュアル再構築 v2（BRIEF §2.4）: 画像はヒーロー帯 1 本だけ。Q&A の間に帯を入れない
 *  （打消し表示の近接を壊さないため）。サイドバーは既存の線アイコン .ic に一本化する。 */

import "./faq.css";
import { useMemo, useState, type CSSProperties } from "react";
import Link from "next/link";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { Reveal, RevealLines } from "@/components/kdz/interactions";
import { ILLUSTRATIONS, ILL_POSITIONS, ILL_THIN_ON_MOBILE, illSrc, type IllName } from "@/lib/illustrations";

/** 循環イラスト帯（ビジュアル刷新 Phase 3）。表示順・位置クラスはトップページの
 *  ILL_LOOP と同じ6点（katazuke-motion.css の .ill-item--<name> 円周配置に対応）。 */
const ILL_LOOP: IllName[] = ["box", "truck", "house-tree", "folding-hands", "books", "plant"];

type CatKey = "fee" | "privacy" | "item" | "flow" | "area";

type Category = {
  key: CatKey;
  label: string;
  icon: IcName;
  items: { q: string; a: React.ReactNode }[];
};

/** カテゴリ別 FAQ データ（デザインの本文をそのまま移植） */
const CATEGORIES: Category[] = [
  {
    key: "fee",
    label: "費用・料金",
    icon: "yen",
    items: [
      {
        q: "利用にお金はかかりますか？",
        a: (
          <>
            出品・査定・お断りまで、<strong>ユーザーの費用は一切かかりません。</strong>
            成約後も同様です。費用は買取額の8%（税別・消費税を別途加算）のみ、業者側が負担します（※ サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします）。買取額や条件は事前に明示されますが、訪問時の現物確認により減額のご相談が届くことがあります。同意しない場合は取引を断れます。
          </>
        ),
      },
      {
        q: "成約後に追加費用は発生しますか？",
        a: "成約後も費用はかかりません。カタヅケはユーザーに対して恒久的に無料のプラットフォームを目指しています。運搬・引き取りにかかる費用は業者が負担します。",
      },
    ],
  },
  {
    key: "privacy",
    label: "個人情報・安心",
    icon: "lock",
    items: [
      {
        q: "しつこい営業電話は来ますか？",
        a: "連絡が来るのは、あなたが選んだ1社だけです。選ばなかった業者には自動でお断りが入るため、一括査定にありがちな営業電話の一斉架電は起こりません。",
      },
      {
        q: "個人情報はどう扱われますか？",
        a: (
          <>
            査定段階で業者に渡るのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容だけです。お名前や電話番号が業者に開示されることはなく、詳細住所と連絡用のメールアドレスも
            <strong>交渉が成立した1社にのみ開示されます。</strong>
            なお、古物営業法により、1万円以上の買取など法令で定める場合には、買取業者が住所・氏名・職業・年齢を確認するため、訪問時に業者から身分証のご提示を求められることがあります。詳しくは<Link href="/privacy">プライバシーポリシー</Link>をご確認ください。
          </>
        ),
      },
      {
        q: "訪問買取は安全ですか？",
        a: "参加するのは、古物商許可番号の登録を必須とし、運営が許可証を確認した登録事業者のみです。連絡先が渡るのは交渉成立後です。訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があります。クーリング・オフの可否は、品目（家具・家電等は対象外）や契約に至った経緯（ご自身の依頼で業者が訪問した場合は対象外となることがあります）によって異なりますので、業者から交付される書面をご確認ください。不安な点はチャットで事前に業者へ確認いただけます。",
      },
    ],
  },
  {
    key: "item",
    label: "品物・査定",
    icon: "zoom",
    items: [
      {
        q: "1点だけでも依頼できますか？",
        a: "はい、1点からでも依頼できます。ただし、まとめて出すほど業者の買取総額が伸びやすく、値がつかない物も一緒に引き取ってもらいやすくなります。家まるごとの片付けなら、まとめての依頼がおすすめです。",
      },
      {
        q: "値段がつかない物はどうなりますか？",
        a: "業者は1点ごとではなく、出品した商品すべてに対する買取総額で入札します。そのため、単体では値がつきにくい物も、他の商品と一緒に引き取ってもらえる場合があります。引き取りが難しい一部の物は、手放す導線をご案内します。",
      },
      {
        q: "査定額はそのまま確定しますか？",
        a: (
          <>
            業者の提示額は参考値です。最終的な買取額は、業者が現物を確認したうえで決まります。ただし、提示した買取金額を下回る変更は、
            <strong>査定現場で商品を確認し、理由を明示したうえでユーザーの了解を得た場合にのみ可能</strong>
            です。ユーザーの同意なく一方的に減額することはできません。
          </>
        ),
      },
    ],
  },
  {
    key: "flow",
    label: "流れ・操作",
    icon: "clock",
    items: [
      {
        q: "入札期間はどのくらいですか？",
        a: (
          <>
            <strong>入札期間の上限は設けていません。</strong>
            入札は随時届き、あなたが業者を選んだ時点で受付が終了します。十分な入札が集まったら、いつでも業者を選んで交渉に進めます。
          </>
        ),
      },
      {
        q: "入札がなかった場合はどうなりますか？",
        a: "入札がなかった場合は、市区町村の粗大ごみ案内（郵便番号入力で捨て方と費用目安がわかります）と、粗大ごみ回収業者への案内をご用意しています。なお、回収業者への依頼は別途費用が発生します。",
      },
      {
        q: "業者とのやり取りはどこで行いますか？",
        a: "入札が届いたときは、LINE連携済みの方はLINEへ、未連携の方はメールでお知らせします（どちらか一方に届きます）。業者とのチャットの新着通知は、LINE連携済みの方のみにお届けします。LINE未連携の場合は、カタヅケのマイページでチャットをご確認ください。業者とのやり取りはカタヅケのウェブページ内チャットで行います。連絡先を交換しなくてもスムーズにコミュニケーションできます。",
      },
    ],
  },
  {
    key: "area",
    label: "エリア・対応",
    icon: "pin",
    items: [
      {
        q: "対応エリアはどこですか？",
        a: (
          <>
            現在は<strong>東京都・千葉県・埼玉県・神奈川県</strong>
            に対応しています。エリアは順次拡大予定です。対象外エリアの場合は、
            <Link href="/contact">お問い合わせ</Link>よりご連絡ください。
          </>
        ),
      },
    ],
  },
];

/** カテゴリタブ（「すべて」を先頭に追加）。モバイルの横スクロールチップと
 *  デスクトップのサイドバーの両方がこの一覧を使う（導線を一本化する）。 */
const CAT_TABS: { key: "all" | CatKey; label: string; icon: IcName }[] = [
  { key: "all", label: "すべて", icon: "menu" },
  ...CATEGORIES.map((c) => ({ key: c.key, label: c.label, icon: c.icon })),
];

/** ラウンド6 指摘（11）: 初期表示は全節とも「全閉」に統一する。
 *  BRIEF §2.4 #3 は「個人情報・安心」の3問を既定で展開していたが、その結果
 *  「費用・料金」は全閉・「個人情報・安心」だけ3問展開という不統一な初期画面になり、
 *  どこを押せば答えが出るのかの基準が読者に伝わらなかった。
 *  代わりに (a) 各節見出しに「すべて開く」トグルを1つ置き、
 *  (b) 検索語があるときは該当項目を自動展開する（探している答えを1タップ手前で止めない）。 */

/** 検索用にカテゴリをまたいだ全 Q&A をフラット化。プレーンテキストは検索一致判定に使う。 */
type FlatItem = { q: string; a: React.ReactNode; catLabel: string; text: string };
const ALL_ITEMS: FlatItem[] = CATEGORIES.flatMap((c) =>
  c.items.map((it) => ({
    q: it.q,
    a: it.a,
    catLabel: c.label,
    text: `${it.q} ${reactNodeToText(it.a)}`,
  }))
);

/** React ノード（answer）から検索照合用のプレーンテキストを抽出する簡易ヘルパー。 */
function reactNodeToText(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(reactNodeToText).join("");
  if (typeof node === "object" && "props" in (node as { props?: unknown })) {
    const props = (node as { props?: { children?: React.ReactNode } }).props;
    return reactNodeToText(props?.children);
  }
  return "";
}

/** 検索一致テキストにハイライト（<mark>）を付与して返す。 */
function highlight(text: string, kw: string): React.ReactNode {
  if (!kw) return text;
  const idx = text.indexOf(kw);
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark>{text.slice(idx, idx + kw.length)}</mark>
      {text.slice(idx + kw.length)}
    </>
  );
}

/** 1件のアコーディオン項目。開閉は grid-template-rows（0fr→1fr）で伸ばすため、
 *  max-height の固定値で長文が途中で切れることがない。 */
function FaqItem({
  q,
  a,
  open,
  onToggle,
  catLabel,
}: {
  q: React.ReactNode;
  a: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  catLabel?: string;
}) {
  return (
    <div className={`faq-item${open ? " open" : ""}`}>
      <button className="faq-q" type="button" aria-expanded={open} onClick={onToggle}>
        <span className="qmark">Q</span>
        <span className="faq-q-text">{q}</span>
        <Ic name="chev" className="faq-chev" />
      </button>
      <div className="faq-a">
        <div className="faq-a-inner">
          {catLabel ? <em className="faq-a-cat">{catLabel}</em> : null}
          {a}
        </div>
      </div>
    </div>
  );
}

export default function FaqPage() {
  const [activeCat, setActiveCat] = useState<"all" | CatKey>("all");
  const [query, setQuery] = useState("");
  // 開閉状態は "<scope>-<index>" をキーに管理（複数同時に開ける。既定は全閉）
  const [openKeys, setOpenKeys] = useState<Set<string>>(() => new Set<string>());
  // 検索結果は既定で展開する。ここには「利用者が明示的に閉じた項目」だけを入れ、
  // 検索語が変わったら捨てる（openKeys とは意味が逆なので別の state にしている）
  const [closedHits, setClosedHits] = useState<Set<string>>(() => new Set<string>());

  const kw = query.trim();

  const hits = useMemo(() => {
    if (!kw) return null;
    return ALL_ITEMS.filter((it) => it.text.includes(kw));
  }, [kw]);

  function selectCat(cat: "all" | CatKey) {
    setActiveCat(cat);
    setQuery("");
    setClosedHits(new Set());
    // QA M6 是正: ここで既定3問へ戻すと、利用者が閉じた回答がカテゴリを切り替えるたびに
    // 開き直る。既定は初回マウント（useState の初期値）だけに適用し、切替では開閉を触らない。
  }

  function toggle(key: string) {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  /** 検索結果の開閉（既定=開。閉じたものだけを覚える）。 */
  function toggleHit(key: string) {
    setClosedHits((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  /** 節の一括開閉。1問でも閉じていれば全部開く、全部開いていれば全部閉じる。 */
  function toggleSection(cat: Category) {
    const keys = cat.items.map((_, i) => `${cat.key}-${i}`);
    setOpenKeys((prev) => {
      const next = new Set(prev);
      const allOpen = keys.every((k) => next.has(k));
      for (const k of keys) {
        if (allOpen) next.delete(k);
        else next.add(k);
      }
      return next;
    });
  }

  const visibleCats =
    activeCat === "all" ? CATEGORIES : CATEGORIES.filter((c) => c.key === activeCat);

  return (
    <main id="main" className="faq-page">
      {/* ヒーロー写真帯（.site-frame の内側いっぱいに届く）。
          --headline のため帯に置くのは h1（見出し）だけ。本文・注記・検索窓は帯の下に置く。
          R4 ラウンド5 指摘（1/3）: --slim（PC 240px / SP 160px）では PC で人物の頭頂が帯の
          上端で切れ、SP では帯が薄すぎて人物が判別できなかった。--mid（PC 400px / SP 220px）に
          上げると可視域が画像高の 30.5% → 50.8%（SP は 100%）に広がり、頭上の余白が確保できる。
          帯の縦位置（--band-pos）は core 所有（R4_BRIEF D.1）なのでここには書かない。 */}
      <section className="hero-band hero-band--mid hero-band--face hero-band--headline faq-hero">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/img/v2/faq-band.webp"
          width={1920}
          height={1088}
          alt=""
          loading="eager"
          fetchPriority="high"
          decoding="async"
        />
        <div className="hero-band__veil" aria-hidden="true" />
        <div className="container hero-band__copy">
          <h1>よくある質問</h1>
        </div>
      </section>

      {/* 帯の直下の白面（リード文）。
          ラウンド6 指摘（9）: リード文が検索窓の下にあり「道具が説明より先に出る」読み順に
          なっていた。DOM 順で説明 → 検索窓に直す（CSS の order で見た目だけ入れ替えると
          DOM 順・タブ順と食い違うので使わない）。
          ラウンド6 指摘（5）: モバイルで検索窓が帯の下端に接し、帯とフォームが1つの塊に
          見えていた。帯を受ける余白はこの面の上パディングが持ち、ヘアラインは置かない。 */}
      <div className="faq-lead">
        <div className="container">
          <p>
            ご利用前の疑問にまとめてお答えします。解決しない場合は
            <Link href="/contact">お問い合わせ</Link>
            ください。
          </p>
        </div>
      </div>

      {/* 検索窓は帯の外・リード文の下に置く（R4 ラウンド5 指摘 3/7/15/17）。
          帯の中に置くと白地 1px 枠の箱が人物の顔の直下に接し、顔を分断して「雑な合成」に見えた。
          件数（aria-live）は検索窓の直下＝操作した場所に置く。 */}
      <div className="faq-searchbar">
        <div className="container">
          <div className="faq-search-wrap">
            <input
              type="text"
              className="faq-search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                // 検索語が変わったら「閉じた項目」の記憶を捨てる（新しい検索は全件展開から始める）
                setClosedHits(new Set());
              }}
              placeholder="キーワードで検索（例：費用、エリア）"
              autoComplete="off"
              aria-label="質問を検索"
            />
            {kw ? (
              <button
                className="faq-search-clear show"
                type="button"
                aria-label="クリア"
                onClick={() => {
                  setQuery("");
                  setClosedHits(new Set());
                }}
              >
                ×
              </button>
            ) : (
              <svg className="faq-search-icon" viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <path d="M21 21l-4.35-4.35" />
              </svg>
            )}
          </div>
          <p className="search-hint" aria-live="polite">
            {kw
              ? hits && hits.length > 0
                ? `${hits.length}件見つかりました`
                : "一致する質問が見つかりませんでした"
              : ""}
          </p>
        </div>
      </div>

      {/* カテゴリタブ（859px 以下のみ。デスクトップはサイドバーに一本化） */}
      <div className="faq-cats">
        <div className="container">
          <div className="faq-cats-inner">
            {CAT_TABS.map((t) => (
              <button
                key={t.key}
                className={`cat-chip${activeCat === t.key && !kw ? " active" : ""}`}
                type="button"
                onClick={() => selectCat(t.key)}
              >
                <Ic name={t.icon} />
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ============ 循環イラスト帯 ============
          ビジュアル刷新 Phase 3（architect指示）: 検索・カテゴリタブを読み終えた直後、
          本文の Q&A に入る前の一息の位置に置く（トップページと同じ .ill-loop を再利用。
          クラス定義は katazuke-motion.css へ移設済みで新規追加はしていない）。装飾のみのため
          section 全体を aria-hidden にする。 */}
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
                  data-ill-thin={ILL_THIN_ON_MOBILE.includes(name) ? "" : undefined}
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

      <div className="section">
        <div className="container">
          <div className="faq-body">
            {/* サイドナビ（行頭は既存の線アイコン .ic。3D アイコンは使わない） */}
            <aside className="faq-side">
              <div className="faq-side-title">カテゴリ</div>
              {CAT_TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  className={`faq-side-link${!kw && activeCat === t.key ? " active" : ""}`}
                  onClick={() => selectCat(t.key)}
                >
                  <Ic name={t.icon} />
                  {t.label}
                </button>
              ))}
              {/* ラウンド6 指摘（25）: 検索から /faq に落ちた業者が、手数料・審査の答え
                  （/business の「業者向けよくある質問」）に届かなかった。カテゴリ列の末尾に
                  1 本だけ置く。859px 以下はサイドバーが消えるので、末尾の
                  .faq-biz-line が同じ導線を担う（導線の本数は常に1本）。 */}
              <Link href="/business#faq" className="faq-side-link faq-side-link--biz">
                <Ic name="bag" />
                業者向けFAQを見る
              </Link>

              <div className="faq-side-foot">
                <div className="faq-side-title">解決しない場合</div>
                <Link href="/contact" className="faq-side-link faq-side-link--link">
                  <Ic name="chat" />
                  お問い合わせ
                </Link>
              </div>
            </aside>

            {/* メインコンテンツ */}
            <div className="faq-main">
              {kw ? (
                /* 検索結果 */
                <div>
                  {hits && hits.length > 0 ? (
                    hits.map((it, i) => {
                      const key = `search-${i}`;
                      return (
                        <FaqItem
                          key={key}
                          q={highlight(it.q, kw)}
                          a={it.a}
                          catLabel={it.catLabel}
                          /* 検索中は該当項目を自動展開する（ラウンド6 指摘 11） */
                          open={!closedHits.has(key)}
                          onToggle={() => toggleHit(key)}
                        />
                      );
                    })
                  ) : (
                    <div className="faq-empty">
                      <svg viewBox="0 0 24 24" className="ic" aria-hidden="true">
                        <circle cx="11" cy="11" r="7" />
                        <path d="M21 21l-4.35-4.35" />
                      </svg>
                      <p>
                        「{kw}」に一致する質問が見つかりませんでした。
                        <br />
                        <Link href="/contact">お問い合わせ</Link>
                        からご質問ください。
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                /* カテゴリ別 */
                <div>
                  {visibleCats.map((c) => (
                    <div className="faq-section" key={c.key}>
                      <div className="faq-section-header">
                        <div className="faq-section-icon">
                          <Ic name={c.icon} />
                        </div>
                        <RevealLines
                          as="h2"
                          mark="under"
                          className="faq-section-title"
                          lines={[c.label]}
                        />
                        <span className="faq-section-count">{c.items.length}問</span>
                        {/* 初期表示を全閉に統一した代わりの一括開閉（ラウンド6 指摘 11）。
                            状態はラベルの文字が持つので aria-expanded は付けない
                            （1つのボタンが複数の領域を制御するため状態の指す先が曖昧になる）。 */}
                        <button
                          type="button"
                          className="faq-section-all"
                          onClick={() => toggleSection(c)}
                        >
                          {c.items.every((_, i) => openKeys.has(`${c.key}-${i}`))
                            ? "すべて閉じる"
                            : "すべて開く"}
                        </button>
                      </div>
                      <div className="faq-list">
                        {c.items.map((it, i) => {
                          const key = `${c.key}-${i}`;
                          return (
                            <Reveal key={key} stagger={i}>
                              <FaqItem
                                q={it.q}
                                a={it.a}
                                open={openKeys.has(key)}
                                onToggle={() => toggle(key)}
                              />
                            </Reveal>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* お問い合わせ誘導 */}
              <div className="faq-contact">
                <Ic name="chat" />
                <div className="faq-contact-info">
                  <RevealLines as="h2" mark="under" lines={["解決しない場合はお問い合わせください"]} />
                  <p>フォームよりお気軽にご連絡ください。通常3営業日以内にご返信いたします。</p>
                  <Link href="/contact" className="btn btn-primary faq-contact-btn">
                    お問い合わせフォームへ
                    <Ic name="arrow" />
                  </Link>
                  {/* サイドバーが消える 859px 以下だけ表示（ラウンド6 指摘 25） */}
                  <p className="faq-biz-line">
                    業者の方は<Link href="/business#faq">業者向けよくある質問</Link>をご覧ください。
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
