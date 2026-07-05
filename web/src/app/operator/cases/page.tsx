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

import { useEffect, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { OperatorHeader } from "@/components/kdz/OperatorHeader";
import { Ic } from "@/components/kdz/Icons";
import { useToken } from "@/components/kdz/Ui";
import {
  CASE_STATUS_LABEL,
  KdzApiError,
  formatYen,
  listOpenCases,
  photoSrc,
  toDisplayMessage,
  type CaseMasked,
} from "@/lib/katadzuke-api";

/** ステータス+自社入札状況 → チップ表示のマッピング。 */
function statusChipInfo(c: CaseMasked): { label: string; cls: string } {
  if (c.my_bid) {
    if (c.my_bid.status === "selected") return { label: "落札", cls: "bidding" };
    if (c.my_bid.status === "rejected") return { label: "非選定", cls: "done" };
    return { label: "入札済み", cls: "negotiating" };
  }
  if (c.status === "open" || c.status === "bidding") return { label: CASE_STATUS_LABEL[c.status], cls: "live" };
  return { label: CASE_STATUS_LABEL[c.status], cls: "done" };
}

function LotCard({ c }: { c: CaseMasked }) {
  const { label, cls } = statusChipInfo(c);
  return (
    <Link href={`/operator/cases/${c.id}`} className={`lot-card ${cls}`.trim()}>
      <div className="lot-card-inner">
        <div className="lot-thumb" aria-hidden="true">
          {c.photos.length > 0 ? (
            c.photos.slice(0, 4).map((p) => (
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
            <span className="lot-id">#{c.id.slice(0, 8)}</span>
            <span className={`status-chip ${cls}`}>{label}</span>
          </div>
          <div className="lot-title">{c.purpose}</div>
          <div className="lot-meta">
            <span className="lot-meta-item">
              <Ic name="pin" />
              {c.prefecture} {c.city}
            </span>
            <span className="lot-meta-item">
              <Ic name="clock" />
              {new Date(c.created_at).toLocaleDateString("ja-JP")}
            </span>
          </div>
          {c.my_bid ? (
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
  const [pendingApproval, setPendingApproval] = useState(false);

  useEffect(() => {
    if (!token) return;
    listOpenCases(token)
      .then(setCases)
      .catch((e) => {
        if (e instanceof KdzApiError && e.status === 403) {
          setPendingApproval(true);
        } else {
          setError(toDisplayMessage(e, "取得に失敗しました"));
        }
      });
  }, [token]);

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
              落札管理へ
              <Ic name="arrow" className="arw" />
            </Link>
          </div>

          {pendingApproval ? (
            <div className="op-alert warn">
              アカウントは運営の承認待ちです。承認が完了すると案件を閲覧できます（通常1営業日以内）。
            </div>
          ) : null}
          {error ? <div className="op-alert error">{error}</div> : null}

          {loading || (!cases && !error && !pendingApproval) ? (
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
              {cases?.map((c) => (
                <LotCard c={c} key={c.id} />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
