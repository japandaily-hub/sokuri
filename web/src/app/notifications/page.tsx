"use client";

/**
 * 通知・お知らせ一覧。
 * デザイン: docs/design_handoff_katazuke/通知・お知らせ一覧.html を React 化。
 * - フィルタタブ（すべて/入札/メッセージ/システム）切替
 * - 未読カードは左ボーダー＋色付き円（タイトル先頭ドット）
 * - 「すべて既読にする」で未読→既読化（UIのみ・バックエンド未配線）
 *
 * バックエンド未配線: 通知データはデモ用モック定数。既読化/LINE設定は UI 挙動のみ。
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import "./notifications.css";

/* ── 通知アイコン（デザインHTMLの symbol を inline 化。共通スプライトと線形が異なるため自前で持つ） ── */
type NotifIconName = "bid" | "chat" | "clock" | "check" | "star" | "truck" | "info" | "bell";

function NotifIcon({ name }: { name: NotifIconName }) {
  switch (name) {
    case "bid":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2l2 7h7l-5.5 4 2 7L12 17l-5.5 3 2-7L3 9h7z" />
        </svg>
      );
    case "chat":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2H9l-4 4V7a2 2 0 012-2z" />
        </svg>
      );
    case "clock":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 3" />
        </svg>
      );
    case "check":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 12.5l4.5 4.5L19 7" />
        </svg>
      );
    case "star":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
      );
    case "truck":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="1" y="3" width="15" height="13" rx="1" />
          <path d="M16 8h4l3 4v4h-7V8z" />
          <circle cx="5.5" cy="18.5" r="2.5" />
          <circle cx="18.5" cy="18.5" r="2.5" />
        </svg>
      );
    case "info":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4M12 16h.01" />
        </svg>
      );
    case "bell":
    default:
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
        </svg>
      );
  }
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

/* ── 型・モックデータ ── */
type FilterKey = "all" | "bid" | "msg" | "sys";
type GroupKey = "today" | "yesterday" | "older";
type Tone = "blue" | "green" | "warn" | "gray";

type Notification = {
  id: string;
  type: Exclude<FilterKey, "all">;
  group: GroupKey;
  unread: false | "blue" | "green" | "warn"; // 未読時の左ボーダー/ドット色
  icon: NotifIconName;
  iconTone: Tone;
  title: string;
  text: string;
  time: string;
  badgeLabel: string;
  badgeTone: Tone;
  href: string;
};

const GROUP_LABEL: Record<GroupKey, string> = {
  today: "今日",
  yesterday: "昨日",
  older: "先週",
};
const GROUP_ORDER: GroupKey[] = ["today", "yesterday", "older"];

/* デモ用モック（明らかにデモ）。バックエンド未配線。 */
const NOTIFICATIONS: Notification[] = [
  {
    id: "n1",
    type: "bid",
    group: "today",
    unread: "blue",
    icon: "bid",
    iconTone: "blue",
    title: "最高額の入札が届きました！",
    text: "株式会社バリュー東京 から ¥54,000 の入札が届いています。期限まで残り1日です。早めにご確認ください。",
    time: "14分前",
    badgeLabel: "入札",
    badgeTone: "blue",
    href: "/result",
  },
  {
    id: "n2",
    type: "msg",
    group: "today",
    unread: "green",
    icon: "chat",
    iconTone: "green",
    title: "リサイクル侍 からメッセージ",
    text: "「ご連絡ありがとうございます！時計の詳細をもう少し教えていただけますか？モデル名や購入時期など…」",
    time: "2時間前",
    badgeLabel: "メッセージ",
    badgeTone: "green",
    href: "/chat/1",
  },
  {
    id: "n3",
    type: "bid",
    group: "today",
    unread: "warn",
    icon: "clock",
    iconTone: "warn",
    title: "入札期限まで残り24時間",
    text: "「家電・ブランド品まとめ 5点」の入札期限が明日の14:00に迫っています。3社から入札が届いています。",
    time: "5時間前",
    badgeLabel: "期限通知",
    badgeTone: "warn",
    href: "/result",
  },
  {
    id: "n4",
    type: "bid",
    group: "yesterday",
    unread: false,
    icon: "bid",
    iconTone: "blue",
    title: "ハウスクリア関東 から入札が届きました",
    text: "¥41,000 の入札が届いています。ご確認ください。",
    time: "昨日 18:20",
    badgeLabel: "入札",
    badgeTone: "gray",
    href: "/result",
  },
  {
    id: "n5",
    type: "sys",
    group: "yesterday",
    unread: false,
    icon: "check",
    iconTone: "green",
    title: "出品が審査を通過しました",
    text: "「家電・ブランド品まとめ 5点」が審査を通過し、業者への公開が開始されました。",
    time: "昨日 10:05",
    badgeLabel: "システム",
    badgeTone: "gray",
    href: "/applications",
  },
  {
    id: "n6",
    type: "sys",
    group: "older",
    unread: false,
    icon: "star",
    iconTone: "blue",
    title: "取引が完了しました。評価をお願いします",
    text: "グリーンリサイクル東京 との取引が完了しました。サービス品質の向上のため、ぜひ評価をお願いします。",
    time: "6月21日",
    badgeLabel: "取引完了",
    badgeTone: "gray",
    href: "/review",
  },
  {
    id: "n7",
    type: "sys",
    group: "older",
    unread: false,
    icon: "truck",
    iconTone: "green",
    title: "訪問日時が確定しました",
    text: "6月21日（土）13:00〜15:00 にグリーンリサイクル東京が訪問します。",
    time: "6月19日",
    badgeLabel: "日程確定",
    badgeTone: "gray",
    href: "/schedule",
  },
  {
    id: "n8",
    type: "sys",
    group: "older",
    unread: false,
    icon: "info",
    iconTone: "gray",
    title: "カタヅケへようこそ！",
    text: "アカウント登録が完了しました。さっそく不用品の出品を始めてみましょう。",
    time: "6月15日",
    badgeLabel: "システム",
    badgeTone: "gray",
    href: "/",
  },
];

const TABS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "すべて" },
  { key: "bid", label: "入札" },
  { key: "msg", label: "メッセージ" },
  { key: "sys", label: "システム" },
];

export default function NotificationsPage() {
  const [filter, setFilter] = useState<FilterKey>("all");
  // 既読化された通知ID集合（「すべて既読」押下で全未読を投入）。バックエンド未配線。
  const [readIds, setReadIds] = useState<Set<string>>(new Set());

  // 表示中の通知（フィルタ適用後）
  const visible = useMemo(
    () => NOTIFICATIONS.filter((n) => filter === "all" || n.type === filter),
    [filter],
  );

  // タブごとの未読バッジ数（既読化されたものは除外）
  const unreadCount = useMemo(() => {
    const count = (pred: (n: Notification) => boolean) =>
      NOTIFICATIONS.filter((n) => pred(n) && n.unread !== false && !readIds.has(n.id)).length;
    return {
      all: count(() => true),
      bid: count((n) => n.type === "bid"),
      msg: count((n) => n.type === "msg"),
      sys: count((n) => n.type === "sys"),
    } satisfies Record<FilterKey, number>;
  }, [readIds]);

  const allRead = unreadCount.all === 0;

  function markAllRead() {
    if (allRead) return;
    setReadIds(new Set(NOTIFICATIONS.map((n) => n.id)));
  }

  return (
    <div className="notif-page">
      <AppHeader unread={!allRead} />

      <main id="main">
        <div className="notif-wrap">
          {/* LINE通知バナー（設定UIは未配線・装飾のみ） */}
          <div className="notif-settings-banner">
            <NotifIcon name="bell" />
            <div className="notif-settings-text">
              <strong>LINE通知が届いていません。</strong>
              <br />
              入札・メッセージをLINEで即座に受け取れます。
            </div>
            <button type="button" className="btn-notif-setting">
              設定する
            </button>
          </div>

          {/* ツールバー（タイトル + すべて既読） */}
          <div className="notif-toolbar">
            <h1 className="notif-toolbar-title">通知・お知らせ</h1>
            <button
              type="button"
              className="btn-read-all"
              onClick={markAllRead}
              disabled={allRead}
            >
              すべて既読にする
            </button>
          </div>

          {/* フィルタタブ */}
          <div className="notif-tabs">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                className={`notif-tab${filter === tab.key ? " active" : ""}`}
                onClick={() => setFilter(tab.key)}
                aria-pressed={filter === tab.key}
              >
                {tab.label}
                {unreadCount[tab.key] > 0 ? (
                  <span className="tab-badge">{unreadCount[tab.key]}</span>
                ) : null}
              </button>
            ))}
          </div>

          {/* 通知一覧（グループごと） */}
          <div id="notif-list">
            {GROUP_ORDER.map((group) => {
              const items = visible.filter((n) => n.group === group);
              if (items.length === 0) return null;
              return (
                <div key={group} className="notif-group">
                  <div className="notif-group-label">{GROUP_LABEL[group]}</div>
                  {items.map((n) => {
                    const isRead = n.unread === false || readIds.has(n.id);
                    const unreadClass = isRead
                      ? "read"
                      : n.unread === "green"
                        ? "unread-green"
                        : n.unread === "warn"
                          ? "unread-warn"
                          : "unread";
                    return (
                      <Link key={n.id} href={n.href} className={`notif-card ${unreadClass}`}>
                        <div className="notif-card-inner">
                          <div className={`notif-icon ${n.iconTone}`}>
                            <NotifIcon name={n.icon} />
                          </div>
                          <div className="notif-body">
                            <div className="notif-title">{n.title}</div>
                            <div className="notif-text">{n.text}</div>
                            <div className="notif-meta">
                              <span className="notif-time">{n.time}</span>
                              <span className={`notif-badge ${n.badgeTone}`}>{n.badgeLabel}</span>
                            </div>
                          </div>
                          <div className="notif-arrow">
                            <ArrowIcon />
                          </div>
                        </div>
                      </Link>
                    );
                  })}
                </div>
              );
            })}

            {/* 空状態 */}
            {visible.length === 0 ? (
              <div className="notif-empty">
                <div className="notif-empty-ic">
                  <NotifIcon name="bell" />
                </div>
                <h3>通知はありません</h3>
                <p>
                  このカテゴリの通知はまだありません。
                  <br />
                  入札や取引が始まるとここに表示されます。
                </p>
              </div>
            ) : null}
          </div>
        </div>
      </main>
    </div>
  );
}
