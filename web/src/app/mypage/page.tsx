"use client";

/**
 * マイページ（/mypage）。
 * デザイン正典: docs/design_handoff_katazuke/マイページ.html をピクセル忠実に再現。
 * このルートは SiteChrome の BARE_PREFIXES（/mypage）対象で共通クロムが付かないため、
 * ページ最上部で共通 AppHeader を描く（デザイン独自ヘッダー markup は再現しない）。
 *
 * クライアント化の理由（純表示では不可）:
 *  - タブ切替（すべて/進行中/成約済み）
 *  - useSession / listMyCases / listTransactions を用いた実データ取得
 *
 * バックエンド配線: listMyCases + listTransactions からフロント側で集計する
 * （専用の統計APIは無い）。データ源が無い項目（住所・利用開始月・フリガナ/電話・
 * 入札締切カウントダウン・通知トグル群・プロフィールタブ）は削除した（2026-07-03）。
 */

import "./mypage.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Ic } from "@/components/kdz/Icons";
import { caseItemsLabel, formatPurposeLabel } from "@/lib/case-labels";
import { StatusBadge, useToken } from "@/components/kdz/Ui";
import {
  LIST_MAX_LIMIT,
  formatYen,
  getMyProfile,
  listMyCases,
  listTransactions,
  photoSrc,
  toDisplayMessage,
  IDENTITY_STATUS_LABEL,
  type CaseOut,
  type CaseStatus,
  type TransactionListItem,
  type UserProfile,
} from "@/lib/katadzuke-api";

type TabKey = "all" | "active" | "done";

/**
 * タブ分類とサマリー集計で共有する唯一の判定ロジック。
 * 「進行中」= closed/cancelled を除く全ステータス（draft/open/bidding）。
 * 「成約済み」= closed（業者決定済み）または cancelled。
 * 「入札受付中」サマリーは進行中のうち、まだ業者が決まっていない
 * （open/bidding）かつ bid_count>0 のもののみをカウントする
 * （closed は成約済みタブに分類されるため、入札受付中サマリーからは除外）。
 */
const DONE_STATUSES: CaseStatus[] = ["closed", "cancelled"];
const isActiveCase = (c: CaseOut): boolean => !DONE_STATUSES.includes(c.status);
const isDoneCase = (c: CaseOut): boolean => DONE_STATUSES.includes(c.status);
const isBiddingCase = (c: CaseOut): boolean =>
  (c.status === "open" || c.status === "bidding") && c.bid_count > 0;

function statusChipInfo(c: CaseOut): { label: string; cls: string } {
  if (c.status === "cancelled") return { label: "キャンセル", cls: "done" };
  if (c.status === "closed") return { label: "業者決定済み", cls: "negotiating" };
  if (c.status === "bidding") return { label: "入札あり", cls: "live" };
  if (c.status === "open") return { label: "入札受付中", cls: "live" };
  return { label: "下書き", cls: "negotiating" };
}

/** 出品カード（実データ版）。unreadCount は成約後の取引に紐づく未読チャット件数（無ければ undefined）。 */
function LotCard({ c, unreadCount }: { c: CaseOut; unreadCount?: number }) {
  const { label, cls } = statusChipInfo(c);
  const isDone = c.status === "closed" || c.status === "cancelled";
  return (
    <Link href={`/cases/${c.id}`} className={`lot-card ${cls}`} style={{ textDecoration: "none" }}>
      <div className="lot-card-inner">
        <div className="lot-thumb" aria-hidden="true">
          {c.photos.length > 0 ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={photoSrc(c.photos[0].url)}
              alt=""
              style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "inherit" }}
            />
          ) : (
            <>
              <div className="lot-thumb-img" />
              <div className="lot-thumb-img" />
              <div className="lot-thumb-img" />
            </>
          )}
        </div>

        <div className="lot-info">
          <div className="lot-info-top">
            <span className="lot-id lot-items" title={`案件ID ${c.id.slice(0, 8)}`}>{caseItemsLabel(c) ?? c.id.slice(0, 8).toUpperCase()}</span>
            {unreadCount ? <span className="status-chip unread">未読{unreadCount}</span> : null}
            <span className={`status-chip ${cls}`}>{label}</span>
          </div>
          <div className="lot-cats">
            <span className="lot-cat-chip">{formatPurposeLabel(c.purpose)}</span>
          </div>
          <div className="lot-meta">
            <span className="lot-meta-item">
              <Ic name="box" />
              {c.photos.length}枚の写真
            </span>
            <span className="lot-meta-item">
              <Ic name="clock" />
              {new Date(c.created_at).toLocaleDateString("ja-JP")}出品
            </span>
          </div>
        </div>

        <div className="lot-action">
          <div className="bid-info">
            <div className="bid-label">入札</div>
            <div className="bid-amount">
              {c.bid_count}
              <span>件</span>
            </div>
            <div className="bid-count">
              {c.bid_count > 0 ? "入札あり" : "入札待ち"}
            </div>
          </div>
          <div className="lot-btns">
            {c.status === "cancelled" ? (
              <span
                className="btn-lot"
                style={{ background: "var(--line-soft)", color: "var(--body-soft)" }}
              >
                <Ic name="x" />
                キャンセル
              </span>
            ) : isDone ? (
              <span className="btn-lot green">
                <Ic name="check" />
                業者決定済み
              </span>
            ) : (
              <span className="btn-lot primary">詳細を見る</span>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}

/** 空状態 */
function EmptyState({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="empty-state">
      <Ic name="box" />
      <h3>{title}</h3>
      {sub ? <p>{sub}</p> : null}
      <Link href="/create" className="btn btn-primary btn-lg">
        出品をはじめる
        <Ic name="arrow" />
      </Link>
    </div>
  );
}

export default function MyPage() {
  const { data: sessionData } = useSession();
  const { token, loading } = useToken();
  const [tab, setTab] = useState<TabKey>("all");

  const [cases, setCases] = useState<CaseOut[] | null>(null);
  const [transactions, setTransactions] = useState<TransactionListItem[] | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setCases(await listMyCases(token));
    } catch (e) {
      setError(toDisplayMessage(e, "案件の取得に失敗しました"));
    }
    try {
      // このページは取引の一覧表示ではなくサマリー集計（成約件数・総買取額・未読数）に
      // 使うため、backend の既定100件切り詰め（r6 H-1）をそのまま使うと成約が101件を
      // 超えたユーザーで集計が過小になる。上限200件ずつ、取得件数が limit 未満になる
      // まで（＝終端まで）ページングして全件を集計対象にする（安全上限20ページ=4000件）。
      const all: TransactionListItem[] = [];
      for (let page = 0; page < 20; page += 1) {
        const res = await listTransactions(token, { limit: LIST_MAX_LIMIT, offset: page * LIST_MAX_LIMIT });
        all.push(...res);
        if (res.length < LIST_MAX_LIMIT) break;
      }
      setTransactions(all);
    } catch (e) {
      setError((prev) => prev ?? toDisplayMessage(e, "取引の取得に失敗しました"));
    }
    try {
      setProfile(await getMyProfile(token));
    } catch (e) {
      setError((prev) => prev ?? toDisplayMessage(e, "プロフィールの取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const userName = sessionData?.user?.name ?? "ゲスト";
  const userInitial = userName.slice(0, 1);

  const completedTxns = useMemo(
    () => (transactions ?? []).filter((t) => t.status === "completed"),
    [transactions],
  );
  const totalAmount = useMemo(
    () => completedTxns.reduce((sum, t) => sum + (t.final_amount ?? t.initial_amount), 0),
    [completedTxns],
  );

  const biddingCount = useMemo(
    () => (cases ?? []).filter(isBiddingCase).length,
    [cases],
  );
  const negotiatingCount = useMemo(
    () => (transactions ?? []).filter((t) => t.status === "pending" || t.status === "visiting").length,
    [transactions],
  );

  const activeLots = useMemo(() => (cases ?? []).filter(isActiveCase), [cases]);
  const doneLots = useMemo(() => (cases ?? []).filter(isDoneCase), [cases]);
  /** 案件ID → 紐づく取引の未読チャット件数（r6-flow M-3 対応）。 */
  const unreadByCaseId = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of transactions ?? []) {
      if (t.unread_count > 0) map.set(t.case_id, t.unread_count);
    }
    return map;
  }, [transactions]);

  const tabs: { key: TabKey; label: string; count: number; gray?: boolean }[] = [
    { key: "all", label: "すべて", count: (cases ?? []).length },
    { key: "active", label: "進行中", count: activeLots.length },
    { key: "done", label: "成約・終了", count: doneLots.length, gray: true },
  ];

  const isLoading = loading || (!cases && !error);
  const sessionExpired = !loading && !token;

  if (sessionExpired) {
    return (
      <div className="mypage-page">
        <AppHeader />
        <main id="main" className="my-wrap">
          <div
            role="alert"
            style={{
              padding: "12px 16px",
              borderRadius: "var(--radius-s)",
              background: "rgba(215,0,53,.06)",
              color: "var(--danger)",
              fontSize: 13,
              border: "1px solid rgba(215,0,53,.35)",
            }}
          >
            セッションが切れました。再ログインしてください。
            <Link href="/login" style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline" }}>
              ログインへ
            </Link>
          </div>
        </main>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="mypage-page">
        <AppHeader />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  return (
    <div className="mypage-page">
      <AppHeader />

      <main id="main" className="my-wrap">
        {error ? (
          <div
            role="alert"
            style={{
              marginBottom: 20,
              padding: "12px 16px",
              borderRadius: "var(--radius-s)",
              background: "rgba(215,0,53,.06)",
              color: "var(--danger)",
              fontSize: 13,
              border: "1px solid rgba(215,0,53,.35)",
            }}
          >
            {error}
          </div>
        ) : null}

        {/* ユーザーカード */}
        <div className="user-card">
          <div className="user-card-avatar">{userInitial}</div>
          <div className="user-card-info">
            <div className="user-card-name">{userName}</div>
          </div>
          <div className="user-card-stats">
            <div className="stat-item">
              <div className="stat-num">
                {(cases ?? []).length}
                <span>件</span>
              </div>
              <div className="stat-lbl">出品回数</div>
            </div>
            <div className="stat-item">
              <div className="stat-num">
                {completedTxns.length}
                <span>件</span>
              </div>
              <div className="stat-lbl">成約済み</div>
            </div>
            <div className="stat-item">
              <div className="stat-num">{formatYen(totalAmount)}</div>
              <div className="stat-lbl">総買取額</div>
            </div>
          </div>
        </div>

        {/* サマリー帯 */}
        <div className="my-summary">
          <Link href="/cases" className="sum-card active-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">入札受付中</div>
            <div className="sum-val">
              {biddingCount}
              <span>件</span>
            </div>
            <div className="sum-sub">入札が届いています</div>
          </Link>
          <Link href="/cases" className="sum-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">交渉中</div>
            <div className="sum-val">
              {negotiatingCount}
              <span>件</span>
            </div>
            <div className="sum-sub">訪問日調整中を含む</div>
          </Link>
          <Link href="/cases" className="sum-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">成約済み</div>
            <div className="sum-val">
              {completedTxns.length}
              <span>件</span>
            </div>
            <div className="sum-sub">総買取額 {formatYen(totalAmount)}</div>
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

        {/* LINE通知誘導（通知トグル群の代替・1行） */}
        <div className="user-card" style={{ marginBottom: 20, padding: "14px 20px" }}>
          <div className="user-card-info" style={{ fontSize: 13, color: "var(--body-soft)" }}>
            入札の通知は、LINE連携済みの方はLINEで、未連携の方はメールでお知らせします。チャットの新着通知はLINE連携済みの方のみに届きます。
            <Link href="/notifications" style={{ marginLeft: 6, fontWeight: 600 }}>
              通知設定を見る（本人確認のためパスワード入力があります）→
            </Link>
          </div>
        </div>
        <div className="user-card" style={{ marginBottom: 20, padding: "14px 20px" }}>
          <div className="user-card-info" style={{ fontSize: 13, color: "var(--body-soft)" }}>
            登録業者の評価と口コミは、成約したユーザーの投稿をそのまま公開しています。
            <Link href="/vendors" style={{ marginLeft: 6, fontWeight: 600 }}>
              登録業者一覧・口コミを見る →
            </Link>
          </div>
        </div>

        {/* 会員情報の入力状況（本人確認/振込口座/LINE連携） */}
        {profile ? (
          <div className="member-status-card">
            <div className="member-status-title">会員情報の入力状況</div>
            <Link href="/mypage/identity" className="member-status-row">
              <span className="member-status-label">本人確認</span>
              <StatusBadge
                value={profile.identity_status === "approved" ? "approved" : profile.identity_status}
                label={IDENTITY_STATUS_LABEL[profile.identity_status]}
              />
            </Link>
            <Link href="/mypage/bank-account" className="member-status-row">
              <span className="member-status-label">振込口座</span>
              <StatusBadge
                value={profile.has_bank_account ? "approved" : "unverified"}
                label={profile.has_bank_account ? "登録済み" : "未登録"}
              />
            </Link>
            <Link href="/notifications" className="member-status-row">
              <span className="member-status-label">LINE連携</span>
              <StatusBadge
                value={profile.line_linked ? "approved" : "unverified"}
                label={profile.line_linked ? "連携済み" : "未連携"}
              />
            </Link>
          </div>
        ) : null}

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
              {t.label}
              <span className={`tab-count${t.gray ? " gray" : ""}`}>{t.count}</span>
            </button>
          ))}
        </div>

        {/* すべて */}
        {tab === "all" ? (
          <div className="lot-list">
            {(cases ?? []).length ? (
              (cases ?? []).map((c) => <LotCard key={c.id} c={c} unreadCount={unreadByCaseId.get(c.id)} />)
            ) : (
              <EmptyState title="まだ出品がありません" sub="最初の出品をしてみましょう。" />
            )}
          </div>
        ) : null}

        {/* 進行中 */}
        {tab === "active" ? (
          <div className="lot-list">
            {activeLots.length ? (
              activeLots.map((c) => <LotCard key={c.id} c={c} unreadCount={unreadByCaseId.get(c.id)} />)
            ) : (
              <EmptyState title="進行中の出品はありません" sub="新しく出品してみましょう。" />
            )}
          </div>
        ) : null}

        {/* 成約済み */}
        {tab === "done" ? (
          <div className="lot-list">
            {doneLots.length ? (
              doneLots.map((c) => <LotCard key={c.id} c={c} unreadCount={unreadByCaseId.get(c.id)} />)
            ) : (
              <EmptyState title="成約済みの出品はありません" />
            )}
          </div>
        ) : null}
      </main>
    </div>
  );
}
