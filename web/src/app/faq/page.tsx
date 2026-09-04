"use client";

/** よくある質問（FAQ）。デザインハンドオフ「よくある質問.html」をピクセル忠実に再実装。
 *  検索・カテゴリフィルタ・アコーディオン開閉を伴うためクライアントコンポーネント。
 *  ヘッダー/フッターは共通 SiteChrome が付与するため、ここでは <main id="main"> の中身のみを描画する。 */

import "./faq.css";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Ic, type IcName } from "@/components/kdz/Icons";

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
            成約後も同様です。費用は買取額の8%のみ、業者側が負担します（※ サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします）。買取額や条件は事前に明示されますが、訪問時の現物確認により減額のご相談が届くことがあります。同意しない場合は取引を断れます。
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
    icon: "shield",
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
        q: "訪問買取に不安があります",
        a: "参加するのは、古物商許可番号の登録を必須とし、運営が許可証を確認した登録事業者のみです。連絡先が渡るのは交渉成立後です。訪問による買取には特定商取引法（訪問購入）の規定が適用される場合があります。クーリング・オフの可否は、品目（家具・家電等は対象外）や契約に至った経緯（ご自身の依頼で業者が訪問した場合は対象外となることがあります）によって異なりますので、業者から交付される書面をご確認ください。不安な点はチャットで事前に業者へ確認いただけます。",
      },
    ],
  },
  {
    key: "item",
    label: "品物・査定",
    icon: "spark",
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

/** カテゴリタブ（「すべて」を先頭に追加） */
const CAT_TABS: { key: "all" | CatKey; label: string; icon: IcName }[] = [
  { key: "all", label: "すべて", icon: "box" },
  ...CATEGORIES.map((c) => ({ key: c.key, label: c.label, icon: c.icon })),
];

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

/** 1件のアコーディオン項目 */
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
      <div className="faq-a" style={{ maxHeight: open ? 600 : 0 }}>
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
  // 開閉状態は "<scope>-<index>" をキーに管理（同セクション内で1件のみ開く）
  const [openKey, setOpenKey] = useState<string | null>(null);

  const kw = query.trim();

  const hits = useMemo(() => {
    if (!kw) return null;
    return ALL_ITEMS.filter((it) => it.text.includes(kw));
  }, [kw]);

  function selectCat(cat: "all" | CatKey) {
    setActiveCat(cat);
    setQuery("");
    setOpenKey(null);
  }

  function toggle(key: string) {
    setOpenKey((prev) => (prev === key ? null : key));
  }

  const visibleCats =
    activeCat === "all" ? CATEGORIES : CATEGORIES.filter((c) => c.key === activeCat);

  // サイドリンクのハイライト対象（all のときは先頭=費用をアクティブ表示／デザイン準拠）
  const sideActive: CatKey = activeCat === "all" ? "fee" : activeCat;

  return (
    <main id="main" className="faq-page">
      {/* ヒーロー */}
      <section className="faq-hero">
        <div className="container">
          <span className="eyebrow">よくある質問</span>
          <h1>よくある質問</h1>
          <p>
            ご利用前の疑問にまとめてお答えします。解決しない場合は
            <Link href="/contact" style={{ color: "var(--blue)" }}>
              お問い合わせ
            </Link>
            ください。
          </p>
          <div className="faq-search-wrap">
            <input
              type="text"
              className="faq-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="キーワードで検索（例：費用、エリア）"
              autoComplete="off"
              aria-label="質問を検索"
            />
            {kw ? (
              <button
                className="faq-search-clear show"
                type="button"
                aria-label="クリア"
                onClick={() => setQuery("")}
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
          <p className="search-hint">
            {kw
              ? hits && hits.length > 0
                ? `${hits.length}件見つかりました`
                : "一致する質問が見つかりませんでした"
              : ""}
          </p>
        </div>
      </section>

      {/* カテゴリタブ */}
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

      <div className="section">
        <div className="container">
          <div className="faq-body">
            {/* サイドナビ */}
            <aside className="faq-side">
              <div className="faq-side-title">カテゴリ</div>
              {CATEGORIES.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  className={`faq-side-link${!kw && sideActive === c.key ? " active" : ""}`}
                  onClick={() => selectCat(c.key)}
                >
                  <Ic name={c.icon} />
                  {c.label}
                </button>
              ))}
              <div
                style={{
                  marginTop: 28,
                  paddingTop: 20,
                  borderTop: "1px solid var(--line-soft)",
                }}
              >
                <div className="faq-side-title">解決しない場合</div>
                <Link href="/contact" className="faq-side-link" style={{ color: "var(--blue)" }}>
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
                          open={openKey === key}
                          onToggle={() => toggle(key)}
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
                        <Link href="/contact" style={{ color: "var(--blue)" }}>
                          お問い合わせ
                        </Link>
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
                        <div className="faq-section-title">{c.label}</div>
                        <span className="faq-section-count">{c.items.length}問</span>
                      </div>
                      <div className="faq-list">
                        {c.items.map((it, i) => {
                          const key = `${c.key}-${i}`;
                          return (
                            <FaqItem
                              key={key}
                              q={it.q}
                              a={it.a}
                              open={openKey === key}
                              onToggle={() => toggle(key)}
                            />
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
                  <h3>解決しない場合はお問い合わせください</h3>
                  <p>フォームよりお気軽にご連絡ください。通常2営業日以内にご返信いたします。</p>
                  <Link
                    href="/contact"
                    className="btn btn-primary"
                    style={{ marginTop: 12, display: "inline-flex" }}
                  >
                    お問い合わせフォームへ
                    <Ic name="arrow" />
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
