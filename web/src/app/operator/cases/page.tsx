"use client";

/**
 * 業者: 入札可能な案件一覧（/operator/cases）。
 *
 * デザインレビュー B-1 対応: 旧 Tailwind/slate 実装（PageShell/Card/StatusBadge）を廃し、
 * ダッシュボード（dashboard.css）と同じ視覚言語（正典トークン・部品）に統一。
 * .lot-card/.status-chip/.empty-state 等は operator-shared.css に定義済み。
 * 併せて OperatorHeader を追加し、ヘッダー欠落でナビ不能だった問題を解消（B-1）。
 * 住所は業者決定後にのみ開示（本文の挙動は変更していない）。
 */

import "../operator-shared.css";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { OperatorHeader } from "@/components/kdz/OperatorHeader";
import { ApprovalPendingNotice } from "@/components/kdz/ApprovalPendingNotice";
import { Ic } from "@/components/kdz/Icons";
import { useToken } from "@/components/kdz/Ui";
import {
  CASE_STATUS_LABEL,
  LIST_DEFAULT_LIMIT,
  dedupeById,
  formatYen,
  getOperatorProfile,
  listOpenCases,
  photoSrc,
  toDisplayMessage,
  type CaseMasked,
} from "@/lib/katadzuke-api";
import { caseItemsLabel, formatPurposeLabel } from "@/lib/case-labels";

/** ステータス+自社入札状況 → チップ表示のマッピング。 */
function statusChipInfo(c: CaseMasked): { label: string; cls: string } {
  if (c.my_bid) {
    if (c.my_bid.status === "selected") return { label: "落札", cls: "bidding" };
    if (c.my_bid.status === "rejected") return { label: "非選定", cls: "done" };
    if (c.my_bid.status === "withdrawn") return { label: "取り下げ済み", cls: "done" };
    return { label: "入札済み", cls: "negotiating" };
  }
  if (c.status === "open" || c.status === "bidding") return { label: CASE_STATUS_LABEL[c.status], cls: "live" };
  return { label: CASE_STATUS_LABEL[c.status], cls: "done" };
}

function LotCard({ c }: { c: CaseMasked }) {
  const { label, cls } = statusChipInfo(c);
  // 商品アルバムがあれば「各商品の1枚目」を4枠に、無ければ従来通りフラット写真の先頭4枚にフォールバック。
  const thumbPhotos =
    c.items && c.items.length > 0
      ? c.items
          .slice()
          .sort((a, b) => a.sort_order - b.sort_order)
          .map((item) => item.photos[0])
          .filter((p): p is NonNullable<typeof p> => p != null)
          .slice(0, 4)
      : c.photos.slice(0, 4);
  return (
    <Link href={`/operator/cases/${c.id}`} className={`lot-card ${cls}`.trim()}>
      <div className="lot-card-inner">
        <div className="lot-thumb" aria-hidden="true">
          {thumbPhotos.length > 0 ? (
            thumbPhotos.map((p) => (
              <div className="lot-thumb-img" key={p.id}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={photoSrc(p.url)} alt="" />
              </div>
            ))
          ) : (
            <>
              <div className="lot-thumb-img" />
              <div className="lot-thumb-img" />
              <div className="lot-thumb-img" />
              <div className="lot-thumb-img" />
            </>
          )}
        </div>
        <div className="lot-info">
          <div className="lot-info-top">
            <span className="lot-id lot-items" title={`案件ID ${c.id.slice(0, 8)}`}>{caseItemsLabel(c) ?? `#${c.id.slice(0, 8)}`}</span>
            <span className={`status-chip ${cls}`}>{label}</span>
          </div>
          <div className="lot-title">{formatPurposeLabel(c.purpose)}</div>
          <div className="lot-meta">
            <span className="lot-meta-item">
              <Ic name="pin" />
              {c.prefecture} {c.city}
            </span>
            <span className="lot-meta-item">
              <Ic name="clock" />
              {new Date(c.created_at).toLocaleDateString("ja-JP")}
            </span>
            {c.item_count != null && c.item_count > 0 ? (
              <span className="lot-meta-item">
                <Ic name="box" />
                商品 {c.item_count} 点
              </span>
            ) : null}
          </div>
          {c.my_bid && c.my_bid.status !== "withdrawn" ? (
            <div className="lot-bid-count">自社入札 {formatYen(c.my_bid.amount)}</div>
          ) : c.bid_count > 0 ? (
            <div className="lot-bid-count" style={{ color: "var(--body-soft)" }}>
              入札 {c.bid_count} 件（他社）
            </div>
          ) : null}
        </div>
        <div className="lot-action" aria-hidden="true">
          <Ic name="arrow" />
        </div>
      </div>
    </Link>
  );
}

export default function OperatorCasesPage() {
  const { token, loading } = useToken();
  const [cases, setCases] = useState<CaseMasked[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vendorStatus, setVendorStatus] = useState<string | null>(null);
  const [hasLicense, setHasLicense] = useState<boolean | null>(null);
  // ページング（r6 H-1）: backend が既定100件で切り詰めるため、取得件数が limit と
  // 一致する間は「さらに読み込む」余地があると判断する（総件数は応答に含まれない）。
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    if (!token) return;
    listOpenCases(token, { limit: LIST_DEFAULT_LIMIT, offset: 0 })
      .then((res) => {
        setCases(res);
        setHasMore(res.length === LIST_DEFAULT_LIMIT);
      })
      .catch((e) => setError(toDisplayMessage(e, "取得に失敗しました")));
  }, [token]);

  async function loadMore() {
    if (!token || loadingMore) return;
    setLoadingMore(true);
    try {
      const res = await listOpenCases(token, { limit: LIST_DEFAULT_LIMIT, offset: cases?.length ?? 0 });
      setCases((prev) => dedupeById([...(prev ?? []), ...res]));
      setHasMore(res.length === LIST_DEFAULT_LIMIT);
    } catch (e) {
      setError(toDisplayMessage(e, "追加の読み込みに失敗しました"));
    } finally {
      setLoadingMore(false);
    }
  }

  // 承認状態（vendor_status）を取得して審査中バナーの表示を判定する。
  // listOpenCases は審査待ちの業者にも200を返すため、403検知では判定できない。
  useEffect(() => {
    if (!token) return;
    getOperatorProfile(token)
      .then((p) => {
        setVendorStatus(p.vendor_status);
        setHasLicense(p.license_image_uploaded_at != null);
      })
      .catch(() => setVendorStatus("unknown"));
  }, [token]);

  const statusLoading = vendorStatus === null;
  const awaitingApproval = !statusLoading && vendorStatus !== "active" && vendorStatus !== "unknown";

  // 絞り込み（クライアント側）: 都道府県 / 未入札のみ。件数が増えた時に目的の案件へ辿り着きやすくする。
  const [prefFilter, setPrefFilter] = useState<string>("all");
  const [onlyUnbid, setOnlyUnbid] = useState(false);
  const prefectures = useMemo(
    () => Array.from(new Set((cases ?? []).map((c) => c.prefecture))).sort(new Intl.Collator("ja").compare),
    [cases],
  );
  const visibleCases = useMemo(
    () =>
      (cases ?? []).filter(
        (c) =>
          (prefFilter === "all" || c.prefecture === prefFilter) &&
          (!onlyUnbid || !c.my_bid || c.my_bid.status === "withdrawn"),
      ),
    [cases, prefFilter, onlyUnbid],
  );

  return (
    <div className="cases-page">
      <OperatorHeader active="cases" />
      <main id="main">
        <div className="op-wrap">
          <div className="op-head">
            <div>
              <h1>案件一覧</h1>
              <p>入札を受け付けている片付け案件です。住所は業者決定後に開示されます。</p>
            </div>
            <Link href="/operator/transactions" className="btn btn-ghost">
              取引一覧へ
              <Ic name="arrow" />
            </Link>
          </div>

          {awaitingApproval ? (
            <ApprovalPendingNotice hasLicenseImage={hasLicense} />
          ) : null}
          {error ? <div className="op-alert error">{error}</div> : null}

          {cases && cases.length > 0 ? (
            <div className="lot-filters" role="group" aria-label="案件の絞り込み">
              <label className="lot-filter">
                <span>エリア</span>
                <select value={prefFilter} onChange={(e) => setPrefFilter(e.target.value)}>
                  <option value="all">すべて（{cases.length}件）</option>
                  {prefectures.map((p) => (
                    <option key={p} value={p}>
                      {p}（{cases.filter((c) => c.prefecture === p).length}件）
                    </option>
                  ))}
                </select>
              </label>
              <label className="lot-filter lot-filter-check">
                <input type="checkbox" checked={onlyUnbid} onChange={(e) => setOnlyUnbid(e.target.checked)} />
                <span>未入札の案件のみ</span>
              </label>
              <span className="lot-filter-count">{visibleCases.length}件を表示</span>
            </div>
          ) : null}
          {hasMore ? (
            <p className="lot-filter-empty" style={{ marginTop: -4, marginBottom: 12 }}>
              ※ エリア・未入札の絞り込みは、現在読み込み済みの{cases?.length ?? 0}件が対象です。
            </p>
          ) : null}

          {loading || (!cases && !error) ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
              <Spinner className="h-6 w-6 text-brand-600" />
            </div>
          ) : cases && cases.length === 0 ? (
            <div className="empty-state">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 7h16M4 12h16M4 17h10" />
              </svg>
              <h3>現在、入札可能な案件はありません</h3>
              <p>新しい案件が出品されると、ここに表示されます。</p>
            </div>
          ) : (
            <div className="lot-list">
              {visibleCases.map((c) => (
                <LotCard c={c} key={c.id} />
              ))}
              {visibleCases.length === 0 ? (
                <p className="lot-filter-empty">条件に合う案件はありません。絞り込みを変更してください。</p>
              ) : null}
            </div>
          )}

          {hasMore ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "16px 0" }}>
              <button type="button" className="btn btn-ghost" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "読み込み中…" : "さらに読み込む"}
              </button>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
