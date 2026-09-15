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

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Ic } from "@/components/kdz/Icons";
import { Notice } from "@/components/kdz/Notice";
import { caseItemsLabel, formatPurposeLabel } from "@/lib/case-labels";
import { formatVisitSchedule } from "@/lib/categories";
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
 * 「入札受付中」サマリーは status==="open" の案件数（r10-M5 是正: 従来は
 * (open|bidding) かつ bid_count>0 を母数にしており、同じ画面のステータス
 * チップ（status==="open" を無条件に「入札受付中」と表示）と定義がずれ、
 * 出品直後・入札0件の案件でチップとサマリーの表示が矛盾していた。
 * チップ側の定義に合わせ、bid_count を問わない status 基準に統一する）。
 */
const DONE_STATUSES: CaseStatus[] = ["closed", "cancelled"];
const isActiveCase = (c: CaseOut): boolean => !DONE_STATUSES.includes(c.status);
const isDoneCase = (c: CaseOut): boolean => DONE_STATUSES.includes(c.status);
const isBiddingCase = (c: CaseOut): boolean => c.status === "open";

/**
 * 出品カードの「更新あり」判定・並べ替え。
 *
 * CaseOut は created_at のみを返し、案件レベルの updated_at をAPIが
 * 公開していない（backend の Case モデル自体は TimestampMixin で
 * updated_at カラムを持つが、入札追加時は bid_count の再集計のみで
 * Case行自体を更新しないため、そのカラムを露出しても2件目以降の入札を
 * 正しく検知できない。schemas_katadzuke.CaseOut への追加は本タスクの
 * 対応範囲外のため行わず、フロント側のみで完結する方式にした）。
 * 代わりに、直近ブラウザで見た時点の状態（status・bid_count）を
 * localStorage に保存し、現在値との差分で「新着」を判定する。
 * 案件を開く（カードをクリックする）とその時点の状態でスナップショットを
 * 更新し、以後は差分が無くなるまでハイライトしない。
 */
/**
 * ストレージキーはセッションのメールアドレスでスコープする（セキュリティレビュー
 * 指摘対応: 共有端末で複数アカウントを切り替えた場合に、前のユーザーの案件状態
 * （ステータス・入札件数）が新しいログインユーザーの画面に残留・混在するのを防ぐ）。
 * 未ログイン時（理論上表示されないが念のため）は "anon" にフォールバックする。
 */
function caseSeenStorageKey(userKey: string): string {
  return `katazuke:mypage:case-seen-state:v1:${userKey}`;
}

interface CaseSeenSnapshot {
  status: CaseStatus;
  bidCount: number;
}

type CaseSeenMap = Record<string, CaseSeenSnapshot>;

function loadCaseSeenMap(userKey: string): CaseSeenMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(caseSeenStorageKey(userKey));
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as CaseSeenMap) : {};
  } catch {
    return {};
  }
}

function saveCaseSeenMap(map: CaseSeenMap, userKey: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(caseSeenStorageKey(userKey), JSON.stringify(map));
  } catch {
    // localStorage が使えない環境（プライベートモード等）でも表示自体は成立するため無視する。
  }
}

/** カードを開いた（見た）時点の状態を記録し、以後の「更新あり」判定から外す。 */
function markCaseSeen(c: CaseOut, userKey: string): void {
  const map = loadCaseSeenMap(userKey);
  map[c.id] = { status: c.status, bidCount: c.bid_count };
  saveCaseSeenMap(map, userKey);
}

/**
 * 「更新あり」= 前回見た状態からステータスが変わった、または入札件数が増えた案件。
 * まだ見た記録が無い案件（新規出品直後を含む）は誤って新着扱いしないよう false。
 */
function caseHasUpdate(c: CaseOut, seenMap: CaseSeenMap): boolean {
  const seen = seenMap[c.id];
  if (!seen) return false;
  return seen.status !== c.status || c.bid_count > seen.bidCount;
}

/** 更新ありの案件を先頭に集める（元の並び順は各グループ内で維持する安定並べ替え）。 */
function sortCasesByUpdate(list: CaseOut[], seenMap: CaseSeenMap): CaseOut[] {
  const updated: CaseOut[] = [];
  const rest: CaseOut[] = [];
  for (const c of list) {
    (caseHasUpdate(c, seenMap) ? updated : rest).push(c);
  }
  return [...updated, ...rest];
}

function statusChipInfo(c: CaseOut): { label: string; cls: string } {
  if (c.status === "cancelled") return { label: "キャンセル", cls: "done" };
  if (c.status === "closed") return { label: "業者決定済み", cls: "negotiating" };
  if (c.status === "bidding") return { label: "入札あり", cls: "live" };
  if (c.status === "open") return { label: "入札受付中", cls: "live" };
  return { label: "下書き", cls: "negotiating" };
}

/**
 * 出品カード（実データ版）。
 * unreadCount: 成約後の取引に紐づく未読チャット件数（無ければ undefined）。
 * visitInfo: 訪問日時（"9月10日（水） 10:00-12:00" 等）。訪問予定のある取引
 *   （status===pending/visiting）が紐づく場合のみ渡される（r10 対応）。
 */
function LotCard({
  c,
  unreadCount,
  visitInfo,
  hasUpdate,
  userKey,
}: {
  c: CaseOut;
  unreadCount?: number;
  visitInfo?: string;
  /** 前回見た時点から状態が変化した案件か（新着入札・ステータス変化）。r-mypage-update 対応。 */
  hasUpdate?: boolean;
  /** 「更新あり」状態の保存先をユーザーごとに分離するためのキー(セッションのメールアドレス)。 */
  userKey: string;
}) {
  const { label, cls } = statusChipInfo(c);
  const isDone = c.status === "closed" || c.status === "cancelled";
  return (
    <Link
      href={`/cases/${c.id}`}
      className={`lot-card ${cls}${hasUpdate ? " has-update" : ""}`}
      style={{ textDecoration: "none" }}
      onClick={() => markCaseSeen(c, userKey)}
    >
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
            {hasUpdate ? (
              <span className="lot-update-indicator" title="前回確認時から動きがありました">
                <span className="lot-update-dot" aria-hidden="true" />
                <span className="sr-only">更新あり</span>
              </span>
            ) : null}
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
            {visitInfo ? (
              <span className="lot-meta-item">
                <Ic name="clock" />
                訪問日 {visitInfo}
              </span>
            ) : null}
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

function MyPageContent() {
  const { data: sessionData } = useSession();
  const { token, loading } = useToken();
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<TabKey>("all");

  // r10-M4 是正: サマリー3枚（入札受付中/交渉中/成約済み）が全て絞り込みなしの /cases へ
  // 飛び、押した数字の中身に辿り着けなかったため、同一ページ内のタブへ `?tab=` で絞り込む。
  useEffect(() => {
    const t = searchParams.get("tab");
    if (t === "all" || t === "active" || t === "done") setTab(t);
  }, [searchParams]);

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

  /**
   * 「更新あり」ハイライト用のスナップショット（r-mypage-update 対応）。
   * 案件一覧が取得できたら、まだ記録の無い案件（新規出品直後を含む）にだけ
   * 現在値でベースラインを追加する。既に記録がある案件の値は上書きしない
   * （＝差分が残ったままハイライトを維持し、カードを開いた時点で
   * markCaseSeen により更新される）。
   */
  const userKey = sessionData?.user?.email ?? "anon";
  const [caseSeenMap, setCaseSeenMap] = useState<CaseSeenMap>({});
  useEffect(() => {
    if (!cases) return;
    const map = loadCaseSeenMap(userKey);
    let changed = false;
    for (const c of cases) {
      if (!map[c.id]) {
        map[c.id] = { status: c.status, bidCount: c.bid_count };
        changed = true;
      }
    }
    if (changed) saveCaseSeenMap(map, userKey);
    setCaseSeenMap(map);
  }, [cases, userKey]);

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

  /** 各タブの表示順（更新ありを先頭に集約。r-mypage-update 対応）。 */
  const sortedAllCases = useMemo(
    () => sortCasesByUpdate(cases ?? [], caseSeenMap),
    [cases, caseSeenMap],
  );
  const sortedActiveLots = useMemo(
    () => sortCasesByUpdate(activeLots, caseSeenMap),
    [activeLots, caseSeenMap],
  );
  const sortedDoneLots = useMemo(
    () => sortCasesByUpdate(doneLots, caseSeenMap),
    [doneLots, caseSeenMap],
  );
  /** 案件ID → 紐づく取引の未読チャット件数（r6-flow M-3 対応）。 */
  const unreadByCaseId = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of transactions ?? []) {
      if (t.unread_count > 0) map.set(t.case_id, t.unread_count);
    }
    return map;
  }, [transactions]);
  /**
   * 案件ID → 訪問日時の表示文字列（r10 対応）。
   * 訪問予定が意味を持つのは日程調整中〜訪問前（status===pending/visiting）の取引のみ。
   * 完了・キャンセル済みの案件では出品カードに訪問日を出す必要がないため対象外にする。
   */
  const visitInfoByCaseId = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of transactions ?? []) {
      if (t.status !== "pending" && t.status !== "visiting") continue;
      map.set(t.case_id, t.visit_date ? formatVisitSchedule(t.visit_date, t.visit_time_slot) : "未確定");
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
          <Notice tone="danger">
            セッションが切れました。再ログインしてください。
            <Link href="/login" style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline" }}>
              ログインへ
            </Link>
          </Notice>
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
        {error ? <Notice tone="danger">{error}</Notice> : null}

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
          <Link href="/mypage?tab=active" className="sum-card active-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">入札受付中</div>
            <div className="sum-val">
              {biddingCount}
              <span>件</span>
            </div>
            <div className="sum-sub">業者からの入札を受付中です</div>
          </Link>
          <Link href="/mypage?tab=done" className="sum-card" style={{ textDecoration: "none" }}>
            <div className="sum-label">訪問調整中</div>
            <div className="sum-val">
              {negotiatingCount}
              <span>件</span>
            </div>
            <div className="sum-sub">訪問日調整中を含む</div>
          </Link>
          <Link href="/mypage?tab=done" className="sum-card" style={{ textDecoration: "none" }}>
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
              通知設定を見る →
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
            {sortedAllCases.length ? (
              sortedAllCases.map((c) => (
                <LotCard
                  key={c.id}
                  c={c}
                  unreadCount={unreadByCaseId.get(c.id)}
                  visitInfo={visitInfoByCaseId.get(c.id)}
                  hasUpdate={caseHasUpdate(c, caseSeenMap)}
                  userKey={userKey}
                />
              ))
            ) : (
              <EmptyState title="まだ出品がありません" sub="最初の出品をしてみましょう。" />
            )}
          </div>
        ) : null}

        {/* 進行中 */}
        {tab === "active" ? (
          <div className="lot-list">
            {sortedActiveLots.length ? (
              sortedActiveLots.map((c) => (
                <LotCard
                  key={c.id}
                  c={c}
                  unreadCount={unreadByCaseId.get(c.id)}
                  visitInfo={visitInfoByCaseId.get(c.id)}
                  hasUpdate={caseHasUpdate(c, caseSeenMap)}
                  userKey={userKey}
                />
              ))
            ) : (
              <EmptyState title="進行中の出品はありません" sub="新しく出品してみましょう。" />
            )}
          </div>
        ) : null}

        {/* 成約済み */}
        {tab === "done" ? (
          <div className="lot-list">
            {sortedDoneLots.length ? (
              sortedDoneLots.map((c) => (
                <LotCard
                  key={c.id}
                  c={c}
                  unreadCount={unreadByCaseId.get(c.id)}
                  visitInfo={visitInfoByCaseId.get(c.id)}
                  hasUpdate={caseHasUpdate(c, caseSeenMap)}
                  userKey={userKey}
                />
              ))
            ) : (
              <EmptyState title="成約済みの出品はありません" />
            )}
          </div>
        ) : null}
      </main>
    </div>
  );
}

/** useSearchParams（?tab=）を使うため Suspense 境界で包む（本番ビルドの静的プリレンダー要件。他ページと同型）。 */
export default function MyPage() {
  return (
    <Suspense fallback={null}>
      <MyPageContent />
    </Suspense>
  );
}
