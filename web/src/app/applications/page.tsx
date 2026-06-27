"use client";

import "./applications.css";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { AppHeader } from "@/components/kdz/AppHeader";

/* ============================================================
   申し込み状況ページ（カタヅケ）
   バックエンド未配線：一覧/カード/チャットはデモ用モックデータ。
   入札の締め切り・チャット送信・再出品等は UI 挙動のみ（実処理なし）。
   ============================================================ */

/** ステータスステップ（受付→入札受付中→交渉→引き取り完了） */
const STATUS_STEPS = [
  { state: "done" as const, dot: "check", label: "受付" },
  { state: "active" as const, dot: "2", label: "入札\n受付中" },
  { state: "todo" as const, dot: "3", label: "業者と\n交渉" },
  { state: "todo" as const, dot: "4", label: "引き取り\n完了" },
];

/** 出品まとめのサムネ（実画像未投入のためカテゴリラベルのみ＝PhImg相当のプレースホルダ表示） */
const LISTING_ITEMS: { src: string; label: string }[] = [
  { src: "/img/cat-kaden.png", label: "家電・PC類" },
  { src: "/img/cat-brand.png", label: "バッグ・財布" },
  { src: "/img/cat-watch.png", label: "腕時計" },
  { src: "/img/cat-camera.png", label: "カメラ" },
  { src: "/img/cat-fashion.png", label: "衣類・靴" },
];

/** 上位3社の入札（デモ）。amount は数値で保持し、表示時に整形する。 */
type Bid = {
  rank: 1 | 2 | 3;
  isNew?: boolean;
  initial: string;
  name: string;
  area: string;
  amount: number;
  highest?: boolean;
  note: string;
};

const BIDS: Bid[] = [
  {
    rank: 1,
    initial: "グ",
    name: "グリーンリサイクル東京",
    area: "東京都・神奈川県対応",
    amount: 68000,
    highest: true,
    note: "まとめ全体の買取総額。家電・ブランド品を中心に評価。引き取り日程は相談のうえ決定。",
  },
  {
    rank: 2,
    initial: "ア",
    name: "アクトリユース",
    area: "東京都・埼玉県対応",
    amount: 62000,
    note: "ブランド品・時計を高評価。梱包不要で玄関先での引き取り対応。",
  },
  {
    rank: 3,
    isNew: true,
    initial: "エ",
    name: "エコステーション千葉",
    area: "千葉県・東京都対応",
    amount: 58000,
    note: "家電・カメラ専門。値がつかない物もまとめて回収対応可能。",
  },
];

/** 活動タイムライン（デモ） */
type TlEntry = { color: "blue" | "green" | "gold"; icon: "trend" | "check"; title: string; body: string; time: string };
const TIMELINE: TlEntry[] = [
  { color: "blue", icon: "trend", title: "新入札", body: "グリーンリサイクル東京 ¥68,000", time: "3分前" },
  { color: "blue", icon: "trend", title: "入札更新", body: "アクトリユース ¥62,000", time: "28分前" },
  { color: "green", icon: "check", title: "業者へ公開", body: "入札受付を開始", time: "2時間前" },
  { color: "green", icon: "check", title: "出品完了", body: "14点を登録", time: "6月23日 10:42" },
];

/** チャット相手（デモ）。userMsgs は state 側で別管理。 */
type ChatMsg = { mine: boolean; text: string; time: string };
type Company = { initial: string; name: string; bid: string; msgs: ChatMsg[] };
const COMPANIES: Company[] = [
  {
    initial: "グ",
    name: "グリーンリサイクル東京",
    bid: "¥68,000",
    msgs: [
      { mine: false, text: "はじめまして。グリーンリサイクル東京です。ご出品いただいた内容を拝見し、¥68,000で入札させていただきました。", time: "10:42" },
      { mine: false, text: "特に家電・ブランド品の評価が高く、まとめてお引き取りできれば上記の金額でご対応可能です。ご検討よろしくお願いします。", time: "10:43" },
    ],
  },
  {
    initial: "ア",
    name: "アクトリユース",
    bid: "¥62,000",
    msgs: [{ mine: false, text: "アクトリユースと申します。ブランド品・時計を中心に高く評価しております。¥62,000でのお引き取りをご提案します。", time: "11:05" }],
  },
  {
    initial: "エ",
    name: "エコステーション千葉",
    bid: "¥58,000",
    msgs: [{ mine: false, text: "エコステーション千葉です。家電・カメラが得意分野です。値がつかないものもまとめて回収可能ですので、ぜひご検討ください。", time: "13:22" }],
  },
];

const AUTO_REPLIES = [
  "ありがとうございます。確認して折り返しご連絡します。",
  "かしこまりました。ご都合のよい日時を教えてください。",
  "詳細を確認次第ご連絡いたします。",
];

/** 郵便番号 → 市区町村DB（先頭3桁キー。デモ用の代表的な値）。 */
type Muni = { name: string; pref: string; method: string; price: string; note: string; url: string };
const MUNI_DB: Record<string, Muni> = {
  "100": { name: "千代田区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,000円/点", note: "最大辺が30cm以上", url: "https://www.city.chiyoda.lg.jp" },
  "103": { name: "中央区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,200円/点", note: "最大辺が30cm以上", url: "https://www.city.chuo.lg.jp" },
  "105": { name: "港区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,000円/点", note: "最大辺が30cm以上", url: "https://www.city.minato.tokyo.jp" },
  "140": { name: "品川区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,200円/点", note: "最大辺が30cm以上", url: "https://www.city.shinagawa.tokyo.jp" },
  "150": { name: "渋谷区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,200円/点", note: "最大辺が30cm以上", url: "https://www.city.shibuya.tokyo.jp" },
  "154": { name: "世田谷区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,000円/点", note: "最大辺が30cm以上", url: "https://www.city.setagaya.lg.jp" },
  "160": { name: "新宿区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,000円/点", note: "最大辺が30cm以上", url: "https://www.city.shinjuku.lg.jp" },
  "166": { name: "杉並区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,000円/点", note: "最大辺が30cm以上", url: "https://www.city.suginami.tokyo.jp" },
  "176": { name: "練馬区", pref: "東京都", method: "インターネット・電話", price: "400円〜2,000円/点", note: "最大辺が30cm以上", url: "https://www.city.nerima.tokyo.jp" },
  "210": { name: "川崎市", pref: "神奈川県", method: "インターネット・電話・ハガキ", price: "300円〜2,100円/点", note: "最大辺が30cm以上", url: "https://www.city.kawasaki.jp/570/category/63-5-0-0-0.html" },
  "220": { name: "横浜市", pref: "神奈川県", method: "インターネット・電話", price: "200円〜1,400円/点", note: "最大辺が30cm以上", url: "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/gomi-recycle/" },
  "330": { name: "さいたま市", pref: "埼玉県", method: "インターネット・電話", price: "250円〜1,800円/点", note: "最大辺が50cm以上", url: "https://www.city.saitama.jp/001/011/009/" },
  "350": { name: "川越市", pref: "埼玉県", method: "インターネット・電話", price: "200円〜2,000円/点", note: "最大辺が50cm以上", url: "https://www.city.kawagoe.saitama.jp/kurashi/gomi/" },
  "260": { name: "千葉市", pref: "千葉県", method: "インターネット・電話", price: "250円〜1,600円/点", note: "最大辺が30cm以上", url: "https://www.city.chiba.jp/kankyo/haikibutsu/sodaigomi.html" },
  "273": { name: "船橋市", pref: "千葉県", method: "インターネット・電話", price: "200円〜1,600円/点", note: "最大辺が30cm以上", url: "https://www.city.funabashi.lg.jp/machi/gomi/" },
  "277": { name: "柏市", pref: "千葉県", method: "インターネット・電話", price: "250円〜2,000円/点", note: "最大辺が50cm以上", url: "https://www.city.kashiwa.lg.jp/kankyoubu/junkan/sodai.html" },
  "279": { name: "浦安市", pref: "千葉県", method: "インターネット・電話", price: "200円〜1,200円/点", note: "最大辺が30cm以上", url: "https://www.city.urayasu.lg.jp/shimin/kankyou/gomi/" },
};

const DISPOSAL_SVG = {
  truck: <svg viewBox="0 0 24 24"><path d="M3 6h11v9H3z" /><path d="M14 9h4l3 3v3h-7z" /><circle cx="7" cy="18" r="1.6" /><circle cx="17" cy="18" r="1.6" /></svg>,
  bag: <svg viewBox="0 0 24 24"><path d="M3 9h18M9 9V5a3 3 0 016 0v4" /><path d="M5 9l1 11h12l1-11" /></svg>,
  recycle: <svg viewBox="0 0 24 24"><path d="M3 12h4l3-9 4 18 3-9h4" /></svg>,
  shield: <svg viewBox="0 0 24 24"><path d="M12 3l7 3v6c0 4.7-3 7.9-7 9-4-1.1-7-4.3-7-9V6z" /><path d="M9 12l2 2 4-4" /></svg>,
};

const DISPOSAL_CARDS = [
  { icon: DISPOSAL_SVG.truck, title: "不用品回収業者", body: "自宅まで来て一括回収。重い物・大きい物もお任せできます。", chip: "目安：5,000円〜" },
  { icon: DISPOSAL_SVG.bag, title: "引越し・片付け業者", body: "引越しや遺品整理と合わせて依頼できます。まとめてお得に。", chip: "目安：20,000円〜" },
  { icon: DISPOSAL_SVG.recycle, title: "家電リサイクル", body: "冷蔵庫・洗濯機・エアコン・テレビは法律上リサイクル料が必要です。", chip: "リサイクル料：1,000〜5,000円" },
  { icon: DISPOSAL_SVG.shield, title: "自治体の戸別回収", body: "有料シールを貼れば玄関前まで回収。申し込みはネット・電話で。", chip: "目安：400〜2,000円/点" },
];

const pad = (n: number) => (n < 10 ? `0${n}` : String(n));

export default function ApplicationsPage() {
  /* ---- カウントダウン（残り約2日14時間） ---- */
  const [remaining, setRemaining] = useState((2 * 24 + 14) * 3600 + 23 * 60 + 45);
  const [stopped, setStopped] = useState(false);
  useEffect(() => {
    if (stopped) return;
    const id = window.setInterval(() => {
      setRemaining((s) => (s <= 0 ? 0 : s - 1));
    }, 1000);
    return () => window.clearInterval(id);
  }, [stopped]);

  const countdownLabel = (() => {
    if (stopped) return "終了";
    if (remaining <= 0) return "終了";
    const d = Math.floor(remaining / 86400);
    const h = Math.floor((remaining % 86400) / 3600);
    const m = Math.floor((remaining % 3600) / 60);
    if (d > 0) return `${d}日 ${pad(h)}:${pad(m)}`;
    if (h > 0) return `${pad(h)}:${pad(m)}`;
    return `${pad(m)}:${pad(remaining % 60)}`;
  })();

  /* ---- 早期終了モーダル + バナー ---- */
  const [modalOpen, setModalOpen] = useState(false);
  const [stoppedTime, setStoppedTime] = useState<string | null>(null);
  const [extraTimeline, setExtraTimeline] = useState<TlEntry[]>([]);

  function confirmStop() {
    setStopped(true);
    setModalOpen(false);
    const now = new Date();
    setStoppedTime(`${now.getHours()}:${pad(now.getMinutes())}`);
    setExtraTimeline((prev) => [{ color: "gold", icon: "check", title: "入札を早期終了", body: "7件の入札で確定", time: "たった今" }, ...prev]);
  }

  /* ---- デモ切替（入札なし状態） ---- */
  const [nobidMode, setNobidMode] = useState(false);

  /* ---- 郵便番号検索 ---- */
  const [zip, setZip] = useState("");
  const [zipResult, setZipResult] = useState<Muni | null>(null);
  const [zipNotFound, setZipNotFound] = useState(false);

  function onZipChange(v: string) {
    let digits = v.replace(/[^0-9]/g, "");
    if (digits.length > 3) digits = `${digits.substring(0, 3)}-${digits.substring(3, 7)}`;
    setZip(digits);
  }
  function lookupZip() {
    const raw = zip.replace(/[^0-9]/g, "");
    if (raw.length < 3) return;
    const muni = MUNI_DB[raw.substring(0, 3)];
    if (muni) {
      setZipResult(muni);
      setZipNotFound(false);
    } else {
      setZipResult(null);
      setZipNotFound(true);
    }
  }
  const disposalSearchHref = (() => {
    const raw = zip.replace(/[^0-9]/g, "");
    const q = raw ? `郵便番号${raw}` : "近く";
    return `https://www.google.com/search?q=${encodeURIComponent(`不用品回収業者 ${q}`)}`;
  })();

  /* ---- チャットパネル ---- */
  const [chatOpen, setChatOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const [userMsgs, setUserMsgs] = useState<ChatMsg[][]>([[], [], []]);
  const [coReplies, setCoReplies] = useState<ChatMsg[][]>([[], [], []]);
  const [draft, setDraft] = useState("");
  const messagesRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const co = COMPANIES[activeIdx];
  // 表示順: 業者初期メッセージ → 各ユーザー送信とそれに対応する業者の自動返信を交互に。
  const renderedMsgs: ChatMsg[] = [...co.msgs, ...userMsgs[activeIdx].flatMap((u, i) => {
    const r = coReplies[activeIdx][i];
    return r ? [u, r] : [u];
  })];

  useEffect(() => {
    if (chatOpen && messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [chatOpen, activeIdx, renderedMsgs.length]);

  function openChat(idx: number) {
    setActiveIdx(idx);
    setChatOpen(true);
    window.setTimeout(() => textareaRef.current?.focus(), 50);
  }

  function sendMsg() {
    const text = draft.trim();
    if (!text) return;
    const now = new Date();
    const t = `${now.getHours()}:${pad(now.getMinutes())}`;
    const idx = activeIdx;
    setUserMsgs((prev) => prev.map((arr, i) => (i === idx ? [...arr, { mine: true, text, time: t }] : arr)));
    setDraft("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    window.setTimeout(() => {
      const n = new Date();
      const reply = AUTO_REPLIES[Math.floor(Math.random() * AUTO_REPLIES.length)];
      setCoReplies((prev) => prev.map((arr, i) => (i === idx ? [...arr, { mine: false, text: reply, time: `${n.getHours()}:${pad(n.getMinutes())}` }] : arr)));
    }, 1800);
  }

  const fullTimeline = [...extraTimeline, ...TIMELINE];

  return (
    <div className="applications-page">
      <AppHeader unread />

      <main>
        <div className="page-wrap">
          {/* ステータスバー */}
          <div className="status-bar">
            <div className="status-steps">
              {STATUS_STEPS.map((s, i) => (
                <div key={i} className={`status-step${s.state === "done" ? " done" : s.state === "active" ? " active" : ""}`}>
                  <div className="s-dot">
                    {s.dot === "check" ? (
                      <svg viewBox="0 0 24 24" style={{ width: 14, height: 14, fill: "none", stroke: "#fff", strokeWidth: 3, strokeLinecap: "round", strokeLinejoin: "round" }}>
                        <path d="M5 12.5l4.5 4.5L19 7" />
                      </svg>
                    ) : (
                      s.dot
                    )}
                  </div>
                  <div className="s-label">
                    {s.label.split("\n").map((line, li) => (
                      <span key={li}>
                        {line}
                        {li < s.label.split("\n").length - 1 ? <br /> : null}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="status-meta">
              <span className="s-id">申し込みID：KTZ-2026-04821</span>
              <span className="s-date">出品日：2026年6月23日</span>
            </div>
          </div>

          {/* 入札サマリー */}
          <div className={`bid-summary${nobidMode ? " dimmed" : ""}`} id="bids">
            <div className="bid-summary-inner">
              <div className="bid-count-area">
                <div className="bid-live-label">
                  <span className="live-dot" />
                  LIVE入札
                </div>
                <div className="bid-count-num">
                  7<span>件</span>
                </div>
                <div className="bid-count-sub">業者が入札中。残り時間内に増える可能性があります。</div>
              </div>
              <div className="bid-highest">
                <div className="bid-highest-label">現在の最高入札</div>
                <div className="bid-highest-amount">
                  68,000<span>円</span>
                </div>
                <div className="bid-highest-note">まとめ全体の買取総額</div>
              </div>
              <div className="bid-timer">
                <div className="bid-timer-label">入札締め切り</div>
                <div className="bid-timer-val">{countdownLabel}</div>
                <div className="bid-timer-sub">{stopped ? "早期終了されました" : "3日間の入札期間"}</div>
                {!stopped ? (
                  <button type="button" className="bid-stop-btn" onClick={() => setModalOpen(true)}>
                    <svg viewBox="0 0 24 24">
                      <rect x="6" y="6" width="12" height="12" rx="2" />
                    </svg>
                    今すぐ入札を締め切る
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          {/* 早期終了バナー */}
          {stoppedTime ? (
            <div className="stopped-banner">
              <div className="stopped-ic">
                <svg viewBox="0 0 24 24">
                  <path d="M5 12.5l4.5 4.5L19 7" />
                </svg>
              </div>
              <span>
                <strong>入札を締め切りました</strong>　上位3社と交渉に進めます
              </span>
              <span className="stopped-time">{stoppedTime}</span>
            </div>
          ) : null}

          {/* 新着通知 */}
          {!nobidMode ? (
            <div className="notif-bar">
              <div className="notif-ic">
                <svg viewBox="0 0 24 24">
                  <path d="M4 17l5-5 3 3 7-7" />
                  <path d="M16 8h4v4" />
                </svg>
              </div>
              <span>
                <strong>新しい入札が届きました</strong>　グリーンリサイクル東京が ¥68,000 を提示
              </span>
              <span className="notif-time">3分前</span>
            </div>
          ) : null}

          {/* メインコンテンツ */}
          <div className={`main-cols${nobidMode ? " dimmed" : ""}`}>
            {/* 左：出品内容 + 入札 */}
            <div>
              {/* 出品まとめ */}
              <div className="listing-card" id="items" style={{ marginBottom: 20 }}>
                <div className="card-head">
                  <h3>出品まとめ</h3>
                  <span className="item-count">14点</span>
                </div>
                <div className="items-grid">
                  {LISTING_ITEMS.map((it) => (
                    <ItemThumb key={it.label} src={it.src} label={it.label} />
                  ))}
                  <div className="item-thumb more">
                    <span>+9</span>
                    <small>点を見る</small>
                  </div>
                </div>
                <div className="listing-footer">
                  <span className="l-date">出品日時：2026年6月23日 10:42</span>
                  <Link href="/create" className="btn-sm ghost" style={{ fontSize: 12 }}>
                    内容を編集
                  </Link>
                </div>
              </div>

              {/* 入札一覧 */}
              <div className="bids-card">
                <div className="card-head">
                  <h3>届いた入札</h3>
                  <span className="item-count">7件</span>
                </div>
                <div className="bids-list">
                  {BIDS.map((b) => (
                    <div key={b.rank} className={`bid-item${b.rank === 1 ? " top1" : ""}${b.isNew ? " new-bid" : ""}`}>
                      <div className={`bid-rank rank${b.rank}${b.isNew ? " new" : ""}`}>
                        {b.rank === 1 ? <Ic name="crown" /> : null}
                        {b.isNew ? "NEW " : ""}
                        {b.rank}位
                      </div>
                      <div className="bid-item-top">
                        <div className="bid-co-icon">{b.initial}</div>
                        <div>
                          <div className="bid-co-name">{b.name}</div>
                          <div className="bid-co-area">
                            {b.area}
                            <Link href="/vendors/1" className="profile-link">
                              プロフィール
                            </Link>
                          </div>
                        </div>
                      </div>
                      <div className="bid-amount-row">
                        <div className="bid-amount">
                          {b.amount.toLocaleString()}
                          <span>円</span>
                        </div>
                        {b.highest ? <span className="bid-badge">最高値</span> : null}
                      </div>
                      <div className="bid-note">{b.note}</div>
                      <div className="bid-action">
                        <button type="button" className="btn-sm primary" onClick={() => openChat(b.rank - 1)}>
                          <Ic name="chat" />
                          交渉する
                        </button>
                        <Link href="/result" className="btn-sm ghost">
                          詳細を見る
                        </Link>
                      </div>
                    </div>
                  ))}

                  {/* 4位以下（非表示） */}
                  <div className="bid-hidden">
                    <div className="bid-hidden-ic">
                      <svg viewBox="0 0 24 24">
                        <rect x="5" y="10" width="14" height="10" rx="2" />
                        <path d="M8 10V8a4 4 0 018 0v2" />
                      </svg>
                    </div>
                    <div className="bid-hidden-body">
                      <strong>他4件の入札は非表示</strong>
                      <p>上位3社以外の入札者の詳細は表示されません。連絡もありません。交渉は上位3社とだけ行えます。</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* 右：サイドバー */}
            <div className="sidebar">
              {/* 申し込み情報 */}
              <div className="side-card">
                <div className="side-card-head">
                  <h4>申し込み情報</h4>
                </div>
                <div className="side-card-body flush">
                  <div className="info-row">
                    <span className="lbl">状態</span>
                    <span className="val blue">入札受付中</span>
                  </div>
                  <div className="info-row">
                    <span className="lbl">入札数</span>
                    <span className="val">7件</span>
                  </div>
                  <div className="info-row">
                    <span className="lbl">最高額</span>
                    <span className="val">¥68,000</span>
                  </div>
                  <div className="info-row">
                    <span className="lbl">出品点数</span>
                    <span className="val">14点</span>
                  </div>
                  <div className="info-row">
                    <span className="lbl">対応エリア</span>
                    <span className="val">東京都</span>
                  </div>
                  <div className="info-row">
                    <span className="lbl">ユーザー費用</span>
                    <span className="val green">無料</span>
                  </div>
                </div>
              </div>

              {/* タイムライン */}
              <div className="side-card">
                <div className="side-card-head">
                  <h4>活動タイムライン</h4>
                </div>
                <div className="side-card-body">
                  <ul className="timeline">
                    {fullTimeline.map((t, i) => (
                      <li className="tl-item" key={i}>
                        <div className={`tl-dot ${t.color}`}>
                          {t.icon === "trend" ? (
                            <svg viewBox="0 0 24 24">
                              <path d="M4 17l5-5 3 3 7-7" />
                              <path d="M16 8h4v4" />
                            </svg>
                          ) : (
                            <svg viewBox="0 0 24 24">
                              <path d="M5 12.5l4.5 4.5L19 7" />
                            </svg>
                          )}
                        </div>
                        <div className="tl-body">
                          <p>
                            <strong>{t.title}</strong>　{t.body}
                          </p>
                          <time>{t.time}</time>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* 入札なし：粗大ごみ案内（デモ切替で表示） */}
      {nobidMode ? (
        <div className="page-wrap nobid-section">
          <div className="nobid-card">
            <div className="nobid-head">
              <div className="nobid-ic">
                <svg viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="8" />
                  <path d="M12 8v4.5l3 2" />
                </svg>
              </div>
              <div>
                <h3>入札期間が終了しました</h3>
                <p>今回は業者からの入札がありませんでした。お住まいの地域の粗大ごみ制度をご案内します。</p>
              </div>
            </div>

            <div className="zip-lookup">
              <label className="zip-label" htmlFor="zip-input">
                郵便番号を入力してください
              </label>
              <div className="zip-input-row">
                <span className="zip-prefix">〒</span>
                <input
                  type="text"
                  id="zip-input"
                  className="zip-input"
                  placeholder="123-4567"
                  maxLength={8}
                  inputMode="numeric"
                  value={zip}
                  onChange={(e) => onZipChange(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") lookupZip();
                  }}
                />
                <button type="button" className="btn-sm primary" onClick={lookupZip}>
                  調べる
                </button>
              </div>
              <p className="zip-hint">ハイフンあり・なしどちらでも入力できます</p>
            </div>

            {zipResult ? (
              <div className="zip-result">
                <div className="zip-muni">
                  {zipResult.pref} {zipResult.name}
                </div>
                <div className="zip-info-grid">
                  <div className="zip-info-item">
                    <div className="zip-info-label">申し込み方法</div>
                    <div className="zip-info-val">{zipResult.method}</div>
                  </div>
                  <div className="zip-info-item">
                    <div className="zip-info-label">費用の目安</div>
                    <div className="zip-info-val green">{zipResult.price}</div>
                  </div>
                  <div className="zip-info-item">
                    <div className="zip-info-label">粗大ごみの基準</div>
                    <div className="zip-info-val">{zipResult.note}</div>
                  </div>
                  <div className="zip-info-item">
                    <div className="zip-info-label">手順</div>
                    <div className="zip-info-val">
                      <ol className="zip-steps">
                        <li>粗大ごみ受付に申し込む</li>
                        <li>指定の有料シール（処理手数料）を購入</li>
                        <li>収集日に玄関前へ出す</li>
                      </ol>
                    </div>
                  </div>
                </div>
                <a href={zipResult.url} target="_blank" rel="noopener noreferrer" className="zip-official-link">
                  <svg viewBox="0 0 24 24">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                  公式サイトで詳細を確認する
                </a>
              </div>
            ) : null}

            {zipNotFound ? (
              <div className="zip-notfound">
                <p>
                  お住まいの地域の情報が見つかりませんでした。
                  <br />
                  市区町村の公式ウェブサイトで「粗大ごみ 申し込み」と検索してください。
                </p>
              </div>
            ) : null}

            {/* 粗大ごみ回収業者 */}
            <div className="or-divider-plain">または、回収業者に依頼する</div>

            <div className="disposal-section">
              <div className="disposal-label">粗大ごみ回収業者</div>
              <div className="paid-note">
                <svg viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4.5M12 16h.01" />
                </svg>
                回収には別途費用がかかります
              </div>
              <div className="disposal-cards">
                {DISPOSAL_CARDS.map((d) => (
                  <div className="disposal-card" key={d.title}>
                    <div className="disposal-card-head">
                      <div className="disposal-card-ic">{d.icon}</div>
                      <h5>{d.title}</h5>
                    </div>
                    <p>{d.body}</p>
                    <span className="price-chip">{d.chip}</span>
                  </div>
                ))}
              </div>
              <a href={disposalSearchHref} target="_blank" rel="noopener noreferrer" className="disposal-search-btn">
                <svg viewBox="0 0 24 24">
                  <circle cx="11" cy="11" r="7" />
                  <path d="M21 21l-4.35-4.35" />
                </svg>
                近くの回収業者を検索する
              </a>
            </div>

            <div className="nobid-retry">
              <p>商品を追加・整理して再出品すると、入札が集まりやすくなります。</p>
              <Link href="/create" className="btn-sm primary">
                再出品する
              </Link>
            </div>
          </div>
        </div>
      ) : null}

      {/* デモ切替 */}
      <div className="demo-toggle-wrap">
        <button type="button" className="demo-toggle" onClick={() => setNobidMode((v) => !v)}>
          {nobidMode ? "通常状態に戻す" : "入札なし状態を見る"}
        </button>
      </div>

      {/* 早期終了モーダル */}
      <div className={`modal-overlay${modalOpen ? " open" : ""}`} onClick={(e) => e.target === e.currentTarget && setModalOpen(false)}>
        <div className="modal" role="dialog" aria-modal="true" aria-label="入札を締め切る確認">
          <div className="modal-ic">
            <svg style={{ width: 26, height: 26, fill: "none", stroke: "#b9892f", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" }} viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          </div>
          <h3>入札を今すぐ締め切りますか？</h3>
          <p className="modal-body">
            現在届いている入札で確定します。<strong>この操作は取り消せません。</strong>
            <br />
            締め切り後は上位3社と交渉に進めます。
          </p>
          <div className="modal-bids-preview">
            <div className="modal-bid-row">
              <span className="rank-chip g">1位</span>
              <span className="co">グリーンリサイクル東京</span>
              <span className="amt">¥68,000</span>
            </div>
            <div className="modal-bid-row">
              <span className="rank-chip s">2位</span>
              <span className="co">アクトリユース</span>
              <span className="amt">¥62,000</span>
            </div>
            <div className="modal-bid-row">
              <span className="rank-chip b">3位</span>
              <span className="co">エコステーション千葉</span>
              <span className="amt">¥58,000</span>
            </div>
          </div>
          <p className="modal-warn">⚠ 締め切り後に追加入札は受け付けられません。残り期間を待てば、さらに高い入札が届く可能性があります。</p>
          <div className="modal-actions">
            <button type="button" className="btn-cancel" onClick={() => setModalOpen(false)}>
              キャンセル
            </button>
            <button type="button" className="btn-confirm-stop" onClick={confirmStop}>
              締め切る
            </button>
          </div>
        </div>
      </div>

      {/* チャットパネル */}
      <div className={`chat-overlay${chatOpen ? " open" : ""}`}>
        <div className="chat-backdrop" onClick={() => setChatOpen(false)} />
        <div className="chat-panel" role="dialog" aria-modal="true" aria-label="業者とのチャット">
          {/* タブ（業者切替） */}
          <div className="chat-tabs">
            {COMPANIES.map((c, i) => (
              <button key={c.name} type="button" className={`chat-tab${i === activeIdx ? " active" : ""}`} onClick={() => setActiveIdx(i)}>
                {c.name}
              </button>
            ))}
          </div>

          {/* ヘッダー */}
          <div className="chat-head">
            <div className="chat-co-ic">{co.initial}</div>
            <div className="chat-co-info">
              <div className="chat-co-name">{co.name}</div>
              <div className="chat-co-bid">
                入札額：<strong>{co.bid}</strong>
              </div>
            </div>
            <span className="chat-status">
              <span className="chat-status-dot" />
              オンライン
            </span>
            <button type="button" className="chat-close" aria-label="閉じる" onClick={() => setChatOpen(false)}>
              <svg viewBox="0 0 24 24">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          {/* メッセージ一覧 */}
          <div className="chat-messages" ref={messagesRef}>
            <div className="chat-date-sep">今日</div>
            {renderedMsgs.map((m, i) => (
              <div key={i} className={`msg${m.mine ? " mine" : ""}`}>
                <div className="msg-av">{m.mine ? "山" : co.initial}</div>
                <div className="msg-body">
                  <div className="msg-bubble">{m.text}</div>
                  <div className="msg-time">
                    {m.time}
                    {m.mine ? <span className="msg-read"> 既読</span> : null}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* 入力エリア */}
          <div className="chat-input-area">
            <div className="chat-input-row">
              <textarea
                ref={textareaRef}
                className="chat-textarea"
                placeholder="メッセージを入力…"
                rows={1}
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMsg();
                  }
                }}
              />
              <button type="button" className="chat-send" aria-label="送信" disabled={!draft.trim()} onClick={sendMsg}>
                <svg viewBox="0 0 24 24">
                  <path d="M22 2L11 13" />
                  <path d="M22 2L15 22l-4-9-9-4 20-7z" />
                </svg>
              </button>
            </div>
            <p className="chat-hint">LINEで通知 → このチャットで返信</p>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 出品サムネ（実画像未投入時はアイコン+ラベルのプレースホルダにフォールバック）。 */
function ItemThumb({ src, label }: { src: string; label: string }) {
  const [err, setErr] = useState(false);
  return (
    <div className="item-thumb">
      {err ? (
        <div className="imgph">
          <Ic name="camera" />
          <small>{label}</small>
        </div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={label} loading="lazy" onError={() => setErr(true)} />
      )}
      <div className="item-label">{label}</div>
    </div>
  );
}
