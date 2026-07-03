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
 *  - 入札フォーム入力 → 確認モーダル → 確定で API 呼び出し
 *  - 入札成功トースト
 *  - 絞り込みセレクトの状態保持
 *
 * バックエンド配線: 案件一覧は listOpenCases()、成約済み/交渉中は listTransactions()
 * （既存 /operator/cases ・ /operator/transactions と同じ実装済み関数を再利用）。
 * KPI サマリーは上記2つのレスポンスからフロント側で集計する（専用APIは無い）。
 * 「交渉中」= transactions のうち status が pending（訪問日調整中）または
 * visiting（訪問予定）のもの。チャット本文の一覧表示は未実装のため、
 * neg タブでは done タブと同じカード実装を流用して該当取引を一覧表示する
 * （2026-07-03 実カウント化）。
 */

import "./dashboard.css";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { Spinner } from "@/components/Icon";
import { useToken } from "@/components/kdz/Ui";
import {
  KdzApiError,
  TXN_STATUS_LABEL,
  createBid,
  formatYen,
  listOpenCases,
  listTransactions,
  photoSrc,
  toDisplayMessage,
  type CaseMasked,
  type TransactionListItem,
} from "@/lib/katadzuke-api";

/* ============================================================
   表示ユーティリティ
   ============================================================ */

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

const yen = (n: number) => n.toLocaleString("ja-JP");

type LotStatus = "none" | "winning" | "outbid";

/** CaseMasked をカード表示用の形にフロント側でマッピングしたもの。 */
type Lot = {
  id: string;
  area: string;
  purpose: string;
  count: number;
  topBid: number | null;
  myBid: number | null;
  bidCount: number;
  status: LotStatus;
  photoUrl: string | null;
};

function toLot(c: CaseMasked): Lot {
  const myBidAmount = c.my_bid?.amount ?? null;
  const topBid = c.top_bid_amount ?? myBidAmount;
  let status: LotStatus = "none";
  if (myBidAmount != null) {
    status = topBid != null && myBidAmount < topBid ? "outbid" : "winning";
  }
  return {
    id: c.id,
    area: `${c.prefecture} ${c.city}`,
    purpose: c.purpose,
    count: c.photos.length,
    topBid,
    myBid: myBidAmount,
    bidCount: c.bid_count,
    status,
    photoUrl: c.photos[0]?.url ?? null,
  };
}

type TabKey = "lots" | "bids" | "neg" | "done";

/* ============================================================
   案件カード
   ============================================================ */

function LotCard({
  lot,
  busy,
  onBid,
}: {
  lot: Lot;
  busy: boolean;
  onBid: (lotId: string, value: number) => void;
}) {
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

  return (
    <div
      className={`lot-card${lot.status === "winning" ? " winning" : lot.status === "outbid" ? " outbid" : ""}`}
    >
      <div className="lot-card-inner">
        {/* 写真グリッド（実アセット未投入 or 1枚のみの場合はカテゴリアイコンでフォールバック） */}
        <div className="lot-photos">
          {lot.photoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={photoSrc(lot.photoUrl)}
              alt=""
              className="lot-photo"
              style={{ gridRow: "1 / 3", objectFit: "cover", width: "100%", height: "100%" }}
            />
          ) : (
            <div className="lot-photo" style={{ gridRow: "1 / 3" }}>
              <div className="imgph">
                <Ic name={catIcon(lot.purpose)} />
                <small>{lot.purpose}</small>
              </div>
            </div>
          )}
          <div className="lot-photo lot-photo-more">
            <span>{lot.count}</span>
            <small>枚</small>
          </div>
        </div>

        {/* 案件情報 */}
        <div className="lot-info">
          <div className="lot-info-top">
            <span className="lot-id">{lot.id.slice(0, 8)}</span>
            {statusTag}
          </div>
          <div className="lot-items-row">
            <span className="lot-item-chip">{lot.purpose}</span>
          </div>
          <div className="lot-meta">
            <span className="lot-meta-item">
              <Ic name="pin" />
              {lot.area}
            </span>
            <span className="lot-meta-item">
              <strong>{lot.bidCount}</strong>社が入札中
            </span>
          </div>
        </div>

        {/* 入札エリア */}
        <div className="lot-bid-area">
          <div>
            <div className="current-top">現在の最高入札</div>
            <div className="current-amount">
              {lot.topBid != null ? yen(lot.topBid) : "—"}
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
              disabled={busy}
              onClick={() => {
                const val = parseInt(draft, 10);
                if (!val || val < 1000) {
                  onBid(lot.id, NaN);
                  return;
                }
                onBid(lot.id, val);
              }}
            >
              {busy ? "送信中…" : submitLabel}
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
  const { token, loading } = useToken();
  const { data: session } = useSession();
  const companyName = session?.user?.name ?? "";
  const [activeTab, setActiveTab] = useState<TabKey>("lots");

  const [cases, setCases] = useState<CaseMasked[] | null>(null);
  const [transactions, setTransactions] = useState<TransactionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingApproval, setPendingApproval] = useState(false);

  // 入札確認モーダル
  const [modalLotId, setModalLotId] = useState<string | null>(null);
  const [modalAmount, setModalAmount] = useState<number>(0);
  const [bidBusy, setBidBusy] = useState(false);

  // トースト
  const [toast, setToast] = useState<string | null>(null);

  function showToast(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 3000);
  }

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      const c = await listOpenCases(token);
      setCases(c);
      setPendingApproval(false);
    } catch (e) {
      if (e instanceof KdzApiError && e.status === 403) {
        setPendingApproval(true);
        setCases([]);
      } else {
        setError(toDisplayMessage(e, "案件の取得に失敗しました"));
      }
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

  const lots = useMemo(() => (cases ?? []).map(toLot), [cases]);
  const biddingLots = lots.filter((l) => l.myBid != null);
  const winningLots = biddingLots.filter((l) => l.status === "winning");
  const doneTxns = useMemo(
    () => (transactions ?? []).filter((t) => t.status === "completed"),
    [transactions],
  );
  /** 「交渉中」= 訪問日調整中（pending）または訪問予定（visiting）の取引。 */
  const negotiatingTxns = useMemo(
    () => (transactions ?? []).filter((t) => t.status === "pending" || t.status === "visiting"),
    [transactions],
  );

  const now = new Date();
  /** 今月の成約件数 = visiting + completed（キャンセルは除外）。金額は completed のみ合計。 */
  const thisMonthActive = useMemo(
    () =>
      (transactions ?? []).filter((t) => {
        if (t.status !== "visiting" && t.status !== "completed") return false;
        const d = new Date(t.created_at);
        return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transactions],
  );
  const thisMonthDoneCount = useMemo(
    () => thisMonthActive.filter((t) => t.status === "completed").length,
    [thisMonthActive],
  );
  const thisMonthAmount = useMemo(
    () =>
      thisMonthActive
        .filter((t) => t.status === "completed")
        .reduce((sum, t) => sum + (t.final_amount ?? t.initial_amount), 0),
    [thisMonthActive],
  );

  function requestBid(lotId: string, value: number) {
    if (Number.isNaN(value)) {
      showToast("入札金額を入力してください（1,000円以上）");
      return;
    }
    setModalLotId(lotId);
    setModalAmount(value);
  }

  async function confirmBid() {
    const lotId = modalLotId;
    const val = modalAmount;
    setModalLotId(null);
    if (!lotId || !val || !token) return;
    setBidBusy(true);
    try {
      await createBid(lotId, { amount: val }, token);
      await reload();
      showToast(`¥${yen(val)} で入札しました`);
    } catch (e) {
      showToast(toDisplayMessage(e, "入札に失敗しました"));
    } finally {
      setBidBusy(false);
    }
  }

  const TABS: { key: TabKey; icon: IcName; label: string; badge: number; gray?: boolean }[] = [
    { key: "lots", icon: "menu", label: "案件一覧", badge: lots.length },
    { key: "bids", icon: "trend", label: "入札中", badge: biddingLots.length },
    { key: "neg", icon: "chat", label: "交渉中", badge: negotiatingTxns.length },
    { key: "done", icon: "check", label: "成約済み", badge: doneTxns.length, gray: true },
  ];

  const NAV: { href: string; label: string; icon: IcName; active?: boolean }[] = [
    { href: "/operator", label: "ダッシュボード", icon: "menu", active: true },
    { href: "/operator/cases", label: "案件一覧", icon: "box" },
    { href: "/operator/transactions", label: "取引", icon: "trend" },
    { href: "/operator/profile", label: "プロフィール", icon: "people" },
  ];

  const isLoading = loading || (!cases && !error && !pendingApproval);

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
          {companyName ? (
            <span className="biz-header-co">
              <span className="co-dot">{companyName.slice(0, 1)}</span>
              <span className="biz-header-co-name">{companyName}</span>
            </span>
          ) : null}
          <Link href="/operator/login" className="biz-logout">
            ログアウト
          </Link>
        </div>
      </header>

      {isLoading ? (
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      ) : (
        <div className="dash-wrap">
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
          {pendingApproval ? (
            <div
              role="status"
              style={{
                marginBottom: 20,
                padding: "12px 16px",
                borderRadius: "var(--radius-s)",
                background: "var(--pale)",
                color: "var(--body)",
                fontSize: 13,
              }}
            >
              アカウントは運営の承認待ちです。承認が完了すると案件を閲覧できます（通常1営業日以内）。
            </div>
          ) : null}

          {/* ---------- サマリー帯（KPI） ---------- */}
          <div className="summary-bar">
            <div className="sum-card highlight">
              <div className="sum-label">入札中の案件</div>
              <div className="sum-val">
                {biddingLots.length}
                <span>件</span>
              </div>
              <div className="sum-sub">うち首位 {winningLots.length}件</div>
            </div>
            <div className="sum-card">
              <div className="sum-label">交渉中</div>
              <div className="sum-val">
                {negotiatingTxns.length}
                <span>件</span>
              </div>
              <div className="sum-sub">訪問日調整中・訪問予定</div>
            </div>
            <div className="sum-card">
              <div className="sum-label">今月の成約</div>
              <div className="sum-val">
                {thisMonthActive.length}
                <span>件</span>
              </div>
              <div className="sum-sub">
                買取総額 ¥{yen(thisMonthAmount)}（うち完了{thisMonthDoneCount}件）
              </div>
            </div>
            <div className="sum-card">
              <div className="sum-label">案件一覧</div>
              <div className="sum-val">
                {lots.length}
                <span>件</span>
              </div>
              <div className="sum-sub">現在入札可能</div>
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
              <span className="filter-count">{lots.length}件</span>
            </div>

            {lots.length === 0 ? (
              <div className="empty-state">
                <Ic name="box" />
                <p>現在、入札可能な案件はありません。</p>
              </div>
            ) : (
              <div className="lot-grid">
                {lots.map((lot) => (
                  <LotCard key={lot.id} lot={lot} busy={bidBusy} onBid={requestBid} />
                ))}
              </div>
            )}
          </div>

          {/* ---------- 入札中タブ ---------- */}
          <div className={`tab-content${activeTab === "bids" ? " active" : ""}`}>
            {biddingLots.length ? (
              <div className="lot-grid">
                {biddingLots.map((lot) => (
                  <LotCard key={lot.id} lot={lot} busy={bidBusy} onBid={requestBid} />
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
            {negotiatingTxns.length === 0 ? (
              <div className="empty-state">
                <Ic name="chat" />
                <p>
                  現在交渉中の取引はありません。
                  <br />
                  落札状況は「取引」ページからご確認いただけます。
                </p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {negotiatingTxns.map((t) => (
                  <Link
                    href={`/operator/transactions/${t.id}`}
                    className="negotiation-card"
                    key={t.id}
                  >
                    <div className="neg-user-ic" aria-hidden="true">
                      <Ic name="chat" />
                    </div>
                    <div className="neg-info">
                      <div className="neg-lot">{t.purpose}</div>
                      <div className="neg-preview">
                        {t.prefecture} {t.city}　{TXN_STATUS_LABEL[t.status]}
                      </div>
                    </div>
                    <div className="neg-right">
                      <div className="neg-amount">
                        {formatYen(t.final_amount ?? t.initial_amount)}
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* ---------- 成約済みタブ ---------- */}
          <div className={`tab-content${activeTab === "done" ? " active" : ""}`}>
            {doneTxns.length === 0 ? (
              <div className="empty-state">
                <Ic name="check" />
                <p>成約済みの案件はまだありません。</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {doneTxns.map((t) => (
                  <Link
                    href={`/operator/transactions/${t.id}`}
                    className="negotiation-card"
                    key={t.id}
                  >
                    <div className="neg-user-ic done" aria-hidden="true">
                      <Ic name="check" />
                    </div>
                    <div className="neg-info">
                      <div className="neg-lot">{t.purpose}</div>
                      <div className="neg-preview">
                        {t.prefecture} {t.city}　成約日：
                        {new Date(t.created_at).toLocaleDateString("ja-JP")}
                      </div>
                    </div>
                    <div className="neg-right">
                      <div className="neg-amount">
                        {formatYen(t.final_amount ?? t.initial_amount)}
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

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
            <button type="button" className="btn-confirm" disabled={bidBusy} onClick={confirmBid}>
              {bidBusy ? "送信中…" : "入札する"}
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
