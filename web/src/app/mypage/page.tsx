"use client";

/**
 * マイページ（/mypage）。
 * デザイン正典: docs/design_handoff_katazuke/マイページ.html をピクセル忠実に再現。
 * このルートは SiteChrome の BARE_PREFIXES（/mypage）対象で共通クロムが付かないため、
 * ページ最上部で共通 AppHeader を描く（デザイン独自ヘッダー markup は再現しない）。
 *
 * クライアント化の理由（純表示では不可）:
 *  - タブ切替（すべて/進行中/成約済み/プロフィール）
 *  - 通知設定トグルの ON/OFF 連動
 *  - 入札受付中ロットのライブカウントダウン
 *
 * バックエンド未配線: 出品一覧・サマリー値・プロフィール値はすべてモックデータ。
 * 保存/編集等の実処理は行わず UI 挙動のみで表現する。
 */

import "./mypage.css";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Ic } from "@/components/kdz/Icons";

/* ====== 型 ====== */
type LotStatus = "negotiating" | "bidding" | "done";

type LotButton = { label: string; href: string };

type Lot = {
  id: string;
  status: LotStatus;
  statusLabel: string;
  cats: string[];
  count: number;
  date: string;
  topBid: number;
  bidCount: number;
  /** 入札受付中のみ：締切までの初期秒数（ライブカウントダウン用） */
  initialSecs: number | null;
  btnPrimary: LotButton | null;
  btnSecondary: LotButton | null;
  doneDate?: string;
};

/* ====== モックデータ（明らかにデモ。バックエンド未配線） ====== */
const LOTS: Lot[] = [
  {
    id: "KTZ-2026-04821",
    status: "negotiating",
    statusLabel: "交渉中",
    cats: ["家電・PC", "ブランド品", "カメラ"],
    count: 14,
    date: "2026年6月23日",
    topBid: 72000,
    bidCount: 7,
    initialSecs: null,
    btnPrimary: { label: "チャットを見る", href: "/chat/1" },
    btnSecondary: { label: "状況を確認", href: "/applications" },
  },
  {
    id: "KTZ-2026-05201",
    status: "bidding",
    statusLabel: "入札受付中",
    cats: ["家具", "衣類・靴", "本・メディア"],
    count: 9,
    date: "2026年6月25日",
    topBid: 31000,
    bidCount: 3,
    initialSecs: 1 * 86400 + 14 * 3600 + 22 * 60,
    btnPrimary: { label: "入札を確認", href: "/applications" },
    btnSecondary: null,
  },
  {
    id: "KTZ-2026-04312",
    status: "done",
    statusLabel: "成約済み",
    cats: ["家電・PC", "ゲーム"],
    count: 8,
    date: "2026年5月10日",
    topBid: 48000,
    bidCount: 5,
    initialSecs: null,
    btnPrimary: null,
    btnSecondary: null,
    doneDate: "2026年5月18日",
  },
  {
    id: "KTZ-2026-03980",
    status: "done",
    statusLabel: "成約済み",
    cats: ["ブランド品", "時計"],
    count: 5,
    date: "2026年4月2日",
    topBid: 72000,
    bidCount: 9,
    initialSecs: null,
    btnPrimary: null,
    btnSecondary: null,
    doneDate: "2026年4月8日",
  },
];

type TabKey = "all" | "active" | "done" | "profile";

const NOTIF_ITEMS = [
  { label: "入札が届いたとき", sub: "LINE通知", defaultOn: true },
  { label: "新着メッセージ", sub: "LINE通知", defaultOn: true },
  { label: "入札期間終了", sub: "LINE通知", defaultOn: true },
  { label: "サービスからのお知らせ", sub: "LINE通知", defaultOn: false },
] as const;

const PROFILE_ROWS = [
  { lbl: "お名前", val: "山田 花子" },
  { lbl: "フリガナ", val: "ヤマダ ハナコ" },
  { lbl: "電話番号", val: "090-****-1234" },
  { lbl: "住所", val: "東京都世田谷区 ****" },
  { lbl: "登録日", val: "2026年3月15日" },
];

/* ====== ヘルパー ====== */
function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function statusChipClass(s: LotStatus): string {
  return { bidding: "live", negotiating: "negotiating", done: "done" }[s];
}

function formatRemaining(secs: number): string {
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return d > 0 ? `${d}日 ${pad(h)}:${pad(m)}` : `${pad(h)}:${pad(m)}`;
}

/* ====== 出品カード ====== */
function LotCard({ lot, liveSecs }: { lot: Lot; liveSecs: number | null }) {
  const isDone = lot.status === "done";
  return (
    <div className={`lot-card ${lot.status}`}>
      <div className="lot-card-inner">
        {/* サムネイル：実アセット未投入のため淡色プレースホルダの4分割枠で表現 */}
        <div className="lot-thumb" aria-hidden="true">
          <div className="lot-thumb-img" />
          <div className="lot-thumb-img" />
          <div className="lot-thumb-img" />
        </div>

        <div className="lot-info">
          <div className="lot-info-top">
            <span className="lot-id">{lot.id}</span>
            <span className={`status-chip ${statusChipClass(lot.status)}`}>{lot.statusLabel}</span>
          </div>
          <div className="lot-cats">
            {lot.cats.map((c) => (
              <span key={c} className="lot-cat-chip">
                {c}
              </span>
            ))}
          </div>
          <div className="lot-meta">
            <span className="lot-meta-item">
              <Ic name="box" />
              {lot.count}点まとめ
            </span>
            <span className="lot-meta-item">
              <Ic name="clock" />
              {lot.date}出品
            </span>
          </div>
          {lot.initialSecs !== null && liveSecs !== null ? (
            <div className="lot-timer live">
              <span className="live-dot" />残り {formatRemaining(liveSecs)}
            </div>
          ) : lot.doneDate ? (
            <div className="lot-timer ended">成約日：{lot.doneDate}</div>
          ) : null}
        </div>

        <div className="lot-action">
          <div className="bid-info">
            <div className="bid-label">{isDone ? "成約額" : "最高入札"}</div>
            <div className="bid-amount">
              ¥{lot.topBid.toLocaleString()}
              <span>円</span>
            </div>
            <div className="bid-count">{lot.bidCount}件の入札</div>
          </div>
          <div className="lot-btns">
            {lot.btnPrimary ? (
              <Link href={lot.btnPrimary.href} className="btn-lot primary">
                {lot.btnPrimary.label}
              </Link>
            ) : null}
            {lot.btnSecondary ? (
              <Link href={lot.btnSecondary.href} className="btn-lot ghost">
                {lot.btnSecondary.label}
              </Link>
            ) : null}
            {!lot.btnPrimary && !lot.btnSecondary ? (
              <span className="btn-lot green">
                <Ic name="check" />
                完了
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ====== 空状態 ====== */
function EmptyState({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="empty-state">
      <Ic name="box" />
      <h3>{title}</h3>
      {sub ? <p>{sub}</p> : null}
      <Link href="/create" className="btn btn-primary btn-lg">
        出品をはじめる
        <Ic name="arrow" className="arw" />
      </Link>
    </div>
  );
}

/* ====== 通知トグル行 ====== */
function NotifRow({ label, sub, defaultOn }: { label: string; sub: string; defaultOn: boolean }) {
  const [on, setOn] = useState(defaultOn);
  return (
    <div className="notif-row">
      <div>
        <div className="notif-label">{label}</div>
        <div className="notif-sub">{sub}</div>
      </div>
      <button
        type="button"
        className={`toggle ${on ? "on" : "off"}`}
        aria-pressed={on}
        aria-label={`${label}の通知`}
        onClick={() => setOn((v) => !v)}
      />
    </div>
  );
}

export default function MyPage() {
  const [tab, setTab] = useState<TabKey>("all");

  // 入札受付中ロットのライブカウントダウン（マウント後に開始）。
  const biddingLot = LOTS.find((l) => l.initialSecs !== null);
  const [liveSecs, setLiveSecs] = useState<number | null>(biddingLot?.initialSecs ?? null);

  useEffect(() => {
    if (liveSecs === null) return;
    const id = window.setInterval(() => {
      setLiveSecs((s) => (s === null || s <= 0 ? s : s - 1));
    }, 1000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeLots = LOTS.filter((l) => l.status !== "done");
  const doneLots = LOTS.filter((l) => l.status === "done");

  const tabs: { key: TabKey; label: string; count?: number; gray?: boolean; icon?: boolean }[] = [
    { key: "all", label: "すべて", count: LOTS.length },
    { key: "active", label: "進行中", count: activeLots.length },
    { key: "done", label: "成約済み", count: doneLots.length, gray: true },
    { key: "profile", label: "プロフィール", icon: true },
  ];

  return (
    <div className="mypage-page">
      <AppHeader unread />

      <main id="main" className="my-wrap">
        {/* ユーザーカード */}
        <div className="user-card">
          <div className="user-card-avatar">山</div>
          <div className="user-card-info">
            <div className="user-card-name">山田 花子</div>
            <div className="user-card-meta">
              <span>
                <Ic name="pin" />東京都世田谷区
              </span>
              <span>
                <Ic name="clock" />2026年3月から利用
              </span>
            </div>
          </div>
          <div className="user-card-stats">
            <div className="stat-item">
              <div className="stat-num">
                3<span>件</span>
              </div>
              <div className="stat-lbl">出品回数</div>
            </div>
            <div className="stat-item">
              <div className="stat-num">
                2<span>件</span>
              </div>
              <div className="stat-lbl">成約済み</div>
            </div>
            <div className="stat-item">
              <div className="stat-num">
                ¥120<span>K</span>
              </div>
              <div className="stat-lbl">総買取額</div>
            </div>
          </div>
        </div>

        {/* サマリー帯 */}
        <div className="my-summary">
          <Link href="/applications" className="sum-card active-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">入札受付中</div>
            <div className="sum-val">
              1<span>件</span>
            </div>
            <div className="sum-sub">入札7件届いています</div>
          </Link>
          <Link href="/applications" className="sum-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">交渉中</div>
            <div className="sum-val">
              1<span>件</span>
            </div>
            <div className="sum-sub">未読メッセージ 2件</div>
          </Link>
          <Link href="/applications" className="sum-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">成約済み</div>
            <div className="sum-val">
              2<span>件</span>
            </div>
            <div className="sum-sub">総買取額 ¥120,000</div>
          </Link>
          <div className="sum-card">
            <div className="sum-label">次の出品</div>
            <div className="sum-val" style={{ fontSize: 16, paddingTop: 4 }}>
              →
            </div>
            <div className="sum-sub">
              <Link href="/create">出品する</Link>
            </div>
          </div>
        </div>

        {/* タブ */}
        <div className="my-tabs" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={`my-tab${tab === t.key ? " active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.icon ? <Ic name="people" /> : null}
              {t.label}
              {typeof t.count === "number" ? (
                <span className={`tab-count${t.gray ? " gray" : ""}`}>{t.count}</span>
              ) : null}
            </button>
          ))}
        </div>

        {/* すべて */}
        {tab === "all" ? (
          <div className="lot-list">
            {LOTS.map((lot) => (
              <LotCard key={lot.id} lot={lot} liveSecs={liveSecs} />
            ))}
          </div>
        ) : null}

        {/* 進行中 */}
        {tab === "active" ? (
          <div className="lot-list">
            {activeLots.length ? (
              activeLots.map((lot) => <LotCard key={lot.id} lot={lot} liveSecs={liveSecs} />)
            ) : (
              <EmptyState title="進行中の出品はありません" sub="新しく出品してみましょう。" />
            )}
          </div>
        ) : null}

        {/* 成約済み */}
        {tab === "done" ? (
          <div className="lot-list">
            {doneLots.length ? (
              doneLots.map((lot) => <LotCard key={lot.id} lot={lot} liveSecs={liveSecs} />)
            ) : (
              <EmptyState title="成約済みの出品はありません" />
            )}
          </div>
        ) : null}

        {/* プロフィール */}
        {tab === "profile" ? (
          <div className="profile-card">
            <div className="profile-section">
              <div className="profile-section-title">
                基本情報
                <Link href="/mypage/profile" className="edit-link">
                  編集
                </Link>
              </div>
              {PROFILE_ROWS.map((r) => (
                <div key={r.lbl} className="profile-row">
                  <span className="profile-lbl">{r.lbl}</span>
                  <span className="profile-val">{r.val}</span>
                </div>
              ))}
            </div>

            <div className="profile-section">
              <div className="profile-section-title">通知設定</div>
              {NOTIF_ITEMS.map((n) => (
                <NotifRow key={n.label} label={n.label} sub={n.sub} defaultOn={n.defaultOn} />
              ))}
            </div>

            <div className="profile-section">
              <div className="profile-section-title">関連リンク</div>
              <div className="profile-links">
                <Link href="/legal">特定商取引法に基づく表記</Link>
                <Link href="/privacy">プライバシーポリシー</Link>
                <Link href="/terms">利用規約</Link>
                <Link href="/contact">お問い合わせ</Link>
                <Link href="/mypage/withdraw" className="danger">
                  退会手続き
                </Link>
              </div>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
