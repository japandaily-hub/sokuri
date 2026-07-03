"use client";

/**
 * 通知・お知らせ一覧。
 * デザイン: docs/design_handoff_katazuke/通知・お知らせ一覧.html を React 化。
 * 通知専用APIが無いため、案件/取引の実データからフロント側でサマリを導出する
 * 「案B」構成に置換した（2026-07-03）。架空 NOTIFICATIONS 定数・フィルタタブは廃止。
 *
 * サマリ3行:
 *  - 入札が届いている案件 N件（listMyCases: bid_count>0 && status!==closed/cancelled → /cases）
 *  - 進行中の取引 N件（listTransactions: pending|visiting → /cases/{case_id}）
 *  - 評価待ちの取引 N件（listTransactions: completed → /review?transaction_id={id}）
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { useToken } from "@/components/kdz/Ui";
import {
  listMyCases,
  listTransactions,
  toDisplayMessage,
  type CaseOut,
  type TransactionListItem,
} from "@/lib/katadzuke-api";
import "./notifications.css";

/* ── アイコン（デザインHTMLの symbol を inline 化） ── */
type NotifIconName = "bid" | "chat" | "star" | "bell";

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
    case "star":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
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

type SummaryRow = {
  key: string;
  icon: NotifIconName;
  iconTone: "blue" | "green" | "warn";
  title: string;
  text: string;
  badgeLabel: string;
  href: string;
};

export default function NotificationsPage() {
  const { token, loading } = useToken();
  const [cases, setCases] = useState<CaseOut[] | null>(null);
  const [transactions, setTransactions] = useState<TransactionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setCases(await listMyCases(token));
    } catch (e) {
      setError(toDisplayMessage(e, "案件の取得に失敗しました"));
    }
    try {
      setTransactions(await listTransactions(token));
    } catch (e) {
      setError((prev) => prev ?? toDisplayMessage(e, "取引の取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const biddingCases = useMemo(
    () =>
      (cases ?? []).filter(
        (c) => c.bid_count > 0 && c.status !== "closed" && c.status !== "cancelled",
      ),
    [cases],
  );
  const negotiatingTxns = useMemo(
    () => (transactions ?? []).filter((t) => t.status === "pending" || t.status === "visiting"),
    [transactions],
  );
  const reviewWaitingTxns = useMemo(
    () => (transactions ?? []).filter((t) => t.status === "completed" && !t.has_review),
    [transactions],
  );

  const rows: SummaryRow[] = [];
  if (biddingCases.length > 0) {
    rows.push({
      key: "bidding",
      icon: "bid",
      iconTone: "blue",
      title: "入札が届いている案件",
      text: `${biddingCases.length}件の案件に業者からの入札が届いています。内容をご確認ください。`,
      badgeLabel: "入札",
      href: "/cases",
    });
  }
  if (negotiatingTxns.length > 0) {
    rows.push({
      key: "negotiating",
      icon: "chat",
      iconTone: "green",
      title: "進行中の取引",
      text: `${negotiatingTxns.length}件の取引が訪問日調整・訪問予定として進行中です。`,
      badgeLabel: "進行中",
      href: negotiatingTxns.length === 1 ? `/cases/${negotiatingTxns[0].case_id}` : "/cases",
    });
  }
  if (reviewWaitingTxns.length > 0) {
    rows.push({
      key: "review",
      icon: "star",
      iconTone: "warn",
      title: "評価待ちの取引",
      text: `${reviewWaitingTxns.length}件の取引が完了しています。業者の評価にご協力ください。`,
      badgeLabel: "評価待ち",
      href:
        reviewWaitingTxns.length === 1
          ? `/review?transaction_id=${reviewWaitingTxns[0].id}`
          : "/mypage",
    });
  }

  const isLoading = loading || (!cases && !transactions && !error);
  const sessionExpired = !loading && !token;

  return (
    <div className="notif-page">
      <AppHeader unread={rows.length > 0} />

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

          <div className="notif-toolbar">
            <h1 className="notif-toolbar-title">通知・お知らせ</h1>
          </div>

          {sessionExpired ? (
            <div
              role="alert"
              style={{
                marginBottom: 20,
                padding: "12px 16px",
                borderRadius: "var(--radius-s)",
                background: "#fff5f5",
                color: "#dc2626",
                fontSize: 13,
                border: "1px solid #fca5a5",
              }}
            >
              セッションが切れました。再ログインしてください。
              <Link href="/login" style={{ marginLeft: 8, fontWeight: 700, textDecoration: "underline" }}>
                ログインへ
              </Link>
            </div>
          ) : null}

          {error ? (
            <div
              role="alert"
              style={{
                marginBottom: 20,
                padding: "12px 16px",
                borderRadius: "var(--radius-s)",
                background: "#fff5f5",
                color: "#dc2626",
                fontSize: 13,
                border: "1px solid #fca5a5",
              }}
            >
              {error}
            </div>
          ) : null}

          {sessionExpired ? null : isLoading ? (
            <div className="flex min-h-[30vh] items-center justify-center">
              <Spinner className="h-6 w-6 text-brand-600" />
            </div>
          ) : (
            <div id="notif-list">
              {rows.length > 0 ? (
                <div className="notif-group">
                  {rows.map((row) => (
                    <Link key={row.key} href={row.href} className="notif-card unread">
                      <div className="notif-card-inner">
                        <div className={`notif-icon ${row.iconTone}`}>
                          <NotifIcon name={row.icon} />
                        </div>
                        <div className="notif-body">
                          <div className="notif-title">{row.title}</div>
                          <div className="notif-text">{row.text}</div>
                          <div className="notif-meta">
                            <span className={`notif-badge ${row.iconTone}`}>{row.badgeLabel}</span>
                          </div>
                        </div>
                        <div className="notif-arrow">
                          <ArrowIcon />
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="notif-empty">
                  <div className="notif-empty-ic">
                    <NotifIcon name="bell" />
                  </div>
                  <h3>新しいお知らせはありません</h3>
                  <p>
                    入札や取引が始まるとここに表示されます。
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
