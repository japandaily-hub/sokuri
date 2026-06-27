"use client";

/**
 * 業者ダッシュボード（/operator）。
 * デザイン正典: docs/design_handoff_katazuke/業者ダッシュボード.html をピクセル忠実に再現。
 * /operator は SiteChrome の BARE_PREFIXES 対象で共通クロムが付かないため、
 * ページ自身が業者向けヘッダー（ロゴ + 業者ナビ + 業者名/通知/ログアウト）と
 * フッターを描く。
 *
 * クライアント化の理由（純表示では不可）:
 *  - タブ切替（案件一覧 / 入札中 / 交渉中 / 成約済み）
 *  - 入札フォーム入力 → 確認モーダル → 確定でカード更新（デモ）
 *  - 入札成功トースト
 *  - 絞り込みセレクトの状態保持
 *
 * バックエンド未配線: KPI / 案件 / 入札はすべてモック定数。入札確定は実処理せず
 * UI 挙動のみ（トースト「…で入札しました（デモ）」）。
 * 実機能の案件一覧/落札管理は既存 /operator/cases ・ /operator/transactions にある。
 */

import "./dashboard.css";

import Link from "next/link";
import { useState } from "react";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";

/* ============================================================
   モックデータ
   ============================================================ */

type LotStatus = "none" | "winning" | "outbid";

/** カテゴリ名 → スプライトアイコン（写真プレースホルダ用の近似） */
const CAT_ICON: Record<string, IcName> = {
  "家電・PC": "sun",
  "ブランド品": "bag",
  "時計": "clock",
  "カメラ": "camera",
  "家具": "sofa",
  "衣類・靴": "tag",
  "ゲーム": "box",
  "音楽": "spark",
  "スポーツ": "trend",
  "本・メディア": "crop",
};
const catIcon = (name: string): IcName => CAT_ICON[name] ?? "box";

type Lot = {
  id: string;
  area: string;
  items: string[];
  count: number;
  topBid: number;
  myBid: number | null;
  bidCount: number;
  expires: string;
  urgent: boolean;
  status: LotStatus;
};

const INITIAL_LOTS: Lot[] = [
  {
    id: "KTZ-2026-05102",
    area: "東京都世田谷区",
    items: ["家電・PC", "ブランド品", "時計", "カメラ"],
    count: 18,
    topBid: 85000,
    myBid: null,
    bidCount: 5,
    expires: "1日 22:10",
    urgent: false,
    status: "none",
  },
  {
    id: "KTZ-2026-05089",
    area: "神奈川県横浜市",
    items: ["家具", "家電・PC", "衣類・靴"],
    count: 11,
    topBid: 42000,
    myBid: 42000,
    bidCount: 3,
    expires: "2日 08:44",
    urgent: false,
    status: "winning",
  },
  {
    id: "KTZ-2026-05077",
    area: "東京都練馬区",
    items: ["ゲーム", "カメラ", "音楽"],
    count: 9,
    topBid: 38000,
    myBid: 32000,
    bidCount: 7,
    expires: "0日 04:12",
    urgent: true,
    status: "outbid",
  },
  {
    id: "KTZ-2026-05063",
    area: "千葉県船橋市",
    items: ["ブランド品", "時計", "スポーツ"],
    count: 14,
    topBid: 61000,
    myBid: null,
    bidCount: 4,
    expires: "2日 17:30",
    urgent: false,
    status: "none",
  },
  {
    id: "KTZ-2026-05051",
    area: "東京都渋谷区",
    items: ["家電・PC", "カメラ", "ブランド品", "本・メディア"],
    count: 22,
    topBid: 94000,
    myBid: null,
    bidCount: 8,
    expires: "1日 11:05",
    urgent: false,
    status: "none",
  },
];

type DoneItem = {
  id: string;
  area: string;
  items: string[];
  count: number;
  amount: number;
  date: string;
};

const DONE: DoneItem[] = [
  { id: "KTZ-2026-04821", area: "東京都足立区", items: ["家電・PC", "ブランド品", "カメラ"], count: 14, amount: 72000, date: "2026年6月25日" },
  { id: "KTZ-2026-04712", area: "東京都板橋区", items: ["家具", "家電・PC"], count: 8, amount: 45000, date: "2026年6月18日" },
  { id: "KTZ-2026-04680", area: "神奈川県川崎市", items: ["ブランド品", "時計"], count: 6, amount: 38000, date: "2026年6月10日" },
  { id: "KTZ-2026-04601", area: "東京都杉並区", items: ["家電・PC", "ゲーム", "本・メディア"], count: 20, amount: 52000, date: "2026年6月2日" },
];

const yen = (n: number) => n.toLocaleString("ja-JP");

type TabKey = "lots" | "bids" | "neg" | "done";

/* ============================================================
   案件カード
   ============================================================ */

function LotCard({ lot, onBid }: { lot: Lot; onBid: (lotId: string, value: number) => void }) {
  const [draft, setDraft] = useState("");

  const statusTag =
    lot.status === "winning" ? (
      <span className="lot-tag green">入札首位</span>
    ) : lot.status === "outbid" ? (
      <span className="lot-tag red">入札順位外</span>
    ) : null;

  const submitLabel = lot.myBid ? "入札額を更新する" : "入札する";
  const submitClass = lot.myBid ? "bid-submit update" : "bid-submit";
  const placeholder = lot.myBid ? yen(lot.myBid) : "金額を入力";

  // 写真は3枚分のプレースホルダ + 「+N点」タイル
  const previewItems = lot.items.slice(0, 3);
  while (previewItems.length < 3) previewItems.push(previewItems[previewItems.length - 1] ?? "その他");

  return (
    <div className={`lot-card${lot.status === "winning" ? " winning" : lot.status === "outbid" ? " outbid" : ""}`}>
      <div className="lot-card-inner">
        {/* 写真グリッド（実アセット未投入 → カテゴリアイコンのプレースホルダ） */}
        <div className="lot-photos">
          {previewItems.map((cat, i) => (
            <div className="lot-photo" key={i}>
              <div className="imgph">
                <Ic name={catIcon(cat)} />
                <small>{cat}</small>
              </div>
            </div>
          ))}
          <div className="lot-photo lot-photo-more">
            <span>+{lot.count - 3}</span>
            <small>点</small>
          </div>
        </div>

        {/* 案件情報 */}
        <div className="lot-info">
          <div className="lot-info-top">
            <span className="lot-id">{lot.id}</span>
            {statusTag}
          </div>
          <div className="lot-items-row">
            {lot.items.map((it) => (
              <span className="lot-item-chip" key={it}>
                {it}
              </span>
            ))}
          </div>
          <div className="lot-meta">
            <span className="lot-meta-item">
              <Ic name="pin" />
              {lot.area}
            </span>
            <span className="lot-meta-item">
              <Ic name="box" />
              {lot.count}点まとめ
            </span>
            <span className="lot-meta-item">
              <strong>{lot.bidCount}</strong>社が入札中
            </span>
          </div>
          <div className={`lot-timer ${lot.urgent ? "urgent" : "normal"}`}>
            <span className="live-dot" />
            残り {lot.expires}
          </div>
        </div>

        {/* 入札エリア */}
        <div className="lot-bid-area">
          <div>
            <div className="current-top">現在の最高入札</div>
            <div className="current-amount">
              {yen(lot.topBid)}
              <span>円</span>
            </div>
          </div>
          {lot.myBid ? (
            <div className="my-bid-row">
              自社入札 <strong>¥{yen(lot.myBid)}</strong>
            </div>
          ) : null}
          <div className="bid-form">
            <div className="bid-input-wrap">
              <span className="bid-yen">¥</span>
              <input
                className="bid-input"
                type="number"
                placeholder={placeholder}
                min={1000}
                step={1000}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                aria-label={`${lot.id} の入札金額`}
              />
              <span className="bid-en">円</span>
            </div>
            <button
              type="button"
              className={submitClass}
              onClick={() => {
                const val = parseInt(draft, 10);
                if (!val || val < 1000) {
                  onBid(lot.id, NaN);
                  return;
                }
                onBid(lot.id, val);
              }}
            >
              {submitLabel}
            </button>
            <p className="bid-hint">成約時のみ買取額の8%が手数料</p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   ページ本体
   ============================================================ */

export default function OperatorDashboardPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("lots");
  const [lots, setLots] = useState<Lot[]>(INITIAL_LOTS);

  // 入札確認モーダル
  const [modalLotId, setModalLotId] = useState<string | null>(null);
  const [modalAmount, setModalAmount] = useState<number>(0);

  // トースト
  const [toast, setToast] = useState<string | null>(null);

  function showToast(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 3000);
  }

  function requestBid(lotId: string, value: number) {
    if (Number.isNaN(value)) {
      showToast("入札金額を入力してください（1,000円以上）");
      return;
    }
    setModalLotId(lotId);
    setModalAmount(value);
  }

  function confirmBid() {
    const lotId = modalLotId;
    const val = modalAmount;
    setModalLotId(null);
    if (!lotId || !val) return;
    // カード更新（デモ。バックエンド未配線）
    setLots((prev) =>
      prev.map((lot) => {
        if (lot.id !== lotId) return lot;
        const nextTop = val > lot.topBid ? val : lot.topBid;
        const status: LotStatus = val >= lot.topBid ? "winning" : "outbid";
        return { ...lot, myBid: val, topBid: nextTop, status };
      })
    );
    showToast(`¥${yen(val)} で入札しました（デモ）`);
  }

  const biddingLots = lots.filter((l) => l.myBid);

  const TABS: { key: TabKey; icon: IcName; label: string; badge: number; gray?: boolean }[] = [
    { key: "lots", icon: "menu", label: "案件一覧", badge: 24 },
    { key: "bids", icon: "trend", label: "入札中", badge: biddingLots.length },
    { key: "neg", icon: "chat", label: "交渉中", badge: 1 },
    { key: "done", icon: "check", label: "成約済み", badge: DONE.length, gray: true },
  ];

  const NAV: { href: string; label: string; icon: IcName; active?: boolean }[] = [
    { href: "/operator", label: "ダッシュボード", icon: "menu", active: true },
    { href: "/operator/cases", label: "案件一覧", icon: "box" },
    { href: "/operator/transactions", label: "取引", icon: "trend" },
    { href: "/operator/profile", label: "プロフィール", icon: "people" },
  ];

  return (
    <div className="op-dash">
      {/* ---------- ヘッダー（業者独自） ---------- */}
      <header className="biz-header">
        <Link href="/" className="biz-header-logo" aria-label="カタヅケ トップへ">
          <KdzLogo size={20} />
        </Link>
        <span className="biz-header-sep" aria-hidden="true" />
        <span className="biz-header-title">業者ダッシュボード</span>

        <nav className="biz-nav" aria-label="業者メニュー">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={`biz-nav-link${n.active ? " active" : ""}`}>
              <Ic name={n.icon} />
              {n.label}
            </Link>
          ))}
        </nav>

        <div className="biz-header-right">
          <Link href="/notifications" className="notif-btn" aria-label="通知・お知らせ">
            <Ic name="chat" />
            <span className="notif-dot" />
          </Link>
          <span className="biz-header-co">
            <span className="co-dot">グ</span>
            <span className="biz-header-co-name">グリーンリサイクル東京</span>
          </span>
          <Link href="/operator/login" className="biz-logout">
            ログアウト
          </Link>
        </div>
      </header>

      <div className="dash-wrap">
        {/* ---------- サマリー帯（KPI） ---------- */}
        <div className="summary-bar">
          <div className="sum-card highlight">
            <div className="sum-label">入札中の案件</div>
            <div className="sum-val">
              3<span>件</span>
            </div>
            <div className="sum-sub">うち首位 2件</div>
          </div>
          <div className="sum-card">
            <div className="sum-label">交渉中</div>
            <div className="sum-val">
              1<span>件</span>
            </div>
            <div className="sum-sub">未読メッセージ 2件</div>
          </div>
          <div className="sum-card">
            <div className="sum-label">今月の成約</div>
            <div className="sum-val">
              4<span>件</span>
            </div>
            <div className="sum-sub">買取総額 ¥312,000</div>
          </div>
          <div className="sum-card">
            <div className="sum-label">新着案件</div>
            <div className="sum-val">
              8<span>件</span>
            </div>
            <div className="sum-sub">今日追加</div>
          </div>
        </div>

        {/* ---------- タブ ---------- */}
        <div className="dash-tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={activeTab === t.key}
              className={`dash-tab${activeTab === t.key ? " active" : ""}`}
              onClick={() => setActiveTab(t.key)}
            >
              <Ic name={t.icon} />
              {t.label}
              <span className={`tab-badge${t.gray ? " gray" : ""}`}>{t.badge}</span>
            </button>
          ))}
        </div>

        {/* ---------- 案件一覧タブ ---------- */}
        <div className={`tab-content${activeTab === "lots" ? " active" : ""}`}>
          <div className="filter-row">
            <span className="filter-label">絞り込み</span>
            <select className="filter-select" aria-label="エリアで絞り込み" defaultValue="全エリア">
              <option>全エリア</option>
              <option>東京都</option>
              <option>神奈川県</option>
              <option>千葉県</option>
              <option>埼玉県</option>
            </select>
            <select className="filter-select" aria-label="カテゴリで絞り込み" defaultValue="全カテゴリ">
              <option>全カテゴリ</option>
              <option>家電・PC</option>
              <option>ブランド品</option>
              <option>カメラ</option>
              <option>家具</option>
              <option>衣類・靴</option>
            </select>
            <select className="filter-select" aria-label="並び替え" defaultValue="新着順">
              <option>新着順</option>
              <option>締め切り近い順</option>
              <option>入札額高い順</option>
              <option>点数多い順</option>
            </select>
            <span className="filter-count">24件</span>
          </div>

          <div className="lot-grid">
            {lots.map((lot) => (
              <LotCard key={lot.id} lot={lot} onBid={requestBid} />
            ))}
          </div>
        </div>

        {/* ---------- 入札中タブ ---------- */}
        <div className={`tab-content${activeTab === "bids" ? " active" : ""}`}>
          {biddingLots.length ? (
            <div className="lot-grid">
              {biddingLots.map((lot) => (
                <LotCard key={lot.id} lot={lot} onBid={requestBid} />
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <Ic name="trend" />
              <p>
                現在入札中の案件はありません。
                <br />
                「案件一覧」から入札してみましょう。
              </p>
            </div>
          )}
        </div>

        {/* ---------- 交渉中タブ ---------- */}
        <div className={`tab-content${activeTab === "neg" ? " active" : ""}`}>
          <Link href="/operator/chat/1" className="negotiation-card">
            <div className="neg-user-ic">山</div>
            <div className="neg-info">
              <div className="neg-lot">KTZ-2026-04821　家電・ブランド品など14点</div>
              <div className="neg-preview">引き取り日程はいつ頃が可能ですか？</div>
            </div>
            <div className="neg-right">
              <div className="neg-amount">¥72,000</div>
              <div className="neg-time">15:42</div>
              <span className="unread-chip">未読 2</span>
            </div>
          </Link>
        </div>

        {/* ---------- 成約済みタブ ---------- */}
        <div className={`tab-content${activeTab === "done" ? " active" : ""}`}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {DONE.map((d) => (
              <div className="negotiation-card" key={d.id} style={{ cursor: "default" }}>
                <div className="neg-user-ic done" aria-hidden="true">
                  <Ic name="check" />
                </div>
                <div className="neg-info">
                  <div className="neg-lot">
                    {d.id}　{d.items.join("・")}など{d.count}点
                  </div>
                  <div className="neg-preview">
                    {d.area}　成約日：{d.date}
                  </div>
                </div>
                <div className="neg-right">
                  <div className="neg-amount">¥{yen(d.amount)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ---------- フッター ---------- */}
      <footer className="biz-footer">
        <span>© 2026 カタヅケ</span>
        <Link href="/legal">プライバシーポリシー</Link>
        <Link href="/legal">利用規約・業者利用規約</Link>
        <Link href="/contact">お問い合わせ</Link>
        <Link href="/">トップページ</Link>
      </footer>

      {/* ---------- 入札確認モーダル ---------- */}
      <div
        className={`modal-overlay${modalLotId ? " open" : ""}`}
        onClick={(e) => {
          if (e.target === e.currentTarget) setModalLotId(null);
        }}
      >
        <div className="modal" role="dialog" aria-modal="true" aria-label="入札の確認">
          <h3>入札を確定しますか？</h3>
          <p className="modal-body">以下の金額でこのまとめに入札します。上位3社に入れば交渉に進めます。</p>
          <div className="modal-amount">
            ¥{modalAmount ? yen(modalAmount) : "—"}
            <span>円</span>
          </div>
          <p className="modal-warn">
            <Ic name="shield" />
            提示した金額を大きく下回る減額は、査定現場での顧客合意が必要です。
          </p>
          <div className="modal-actions">
            <button type="button" className="btn-cancel" onClick={() => setModalLotId(null)}>
              キャンセル
            </button>
            <button type="button" className="btn-confirm" onClick={confirmBid}>
              入札する
            </button>
          </div>
        </div>
      </div>

      {/* ---------- トースト ---------- */}
      <div className={`toast${toast ? " show" : ""}`} role="status" aria-live="polite">
        <Ic name="check" />
        <span>{toast ?? ""}</span>
      </div>
    </div>
  );
}
