"use client";

/**
 * 業者: 落札案件の一覧（落札管理の入口）（/operator/transactions）。
 *
 * デザインレビュー B-1 対応: 旧 Tailwind/slate 実装（PageShell/Card/StatusBadge）を廃し、
 * katazuke トークンへ統一。OperatorHeader を追加しナビ不能だった問題も解消。
 */

import "../operator-shared.css";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { OperatorHeader } from "@/components/kdz/OperatorHeader";
import { Ic } from "@/components/kdz/Icons";
import { useToken } from "@/components/kdz/Ui";
import {
  TXN_STATUS_LABEL,
  formatYen,
  listTransactions,
  toDisplayMessage,
  type TransactionListItem,
} from "@/lib/katadzuke-api";

/** 取引ステータス → チップ表示のマッピング（operator-shared.css の .status-chip を流用）。 */
function txnChipClass(status: TransactionListItem["status"]): string {
  if (status === "completed") return "bidding";
  if (status === "cancelled") return "done";
  return "negotiating"; // pending / visiting
}

export default function OperatorTransactionsPage() {
  const { token, loading } = useToken();
  const [items, setItems] = useState<TransactionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    listTransactions(token)
      .then(setItems)
      .catch((e) => setError(toDisplayMessage(e, "取得に失敗しました")));
  }, [token]);

  const attentionCount = items?.filter((t) => t.has_pending_reduction).length ?? 0;

  return (
    <div className="cases-page">
      <OperatorHeader active="transactions" hasAttention={attentionCount > 0} />
      <main id="main">
        <div className="op-wrap">
          <div className="op-head">
            <div>
              <h1>落札管理</h1>
              <p>落札した案件の進行状況です。</p>
            </div>
            <Link href="/operator/cases" className="btn btn-ghost">
              案件一覧へ
              <Ic name="arrow" className="arw" />
            </Link>
          </div>

          {error ? <div className="op-alert error">{error}</div> : null}

          {loading || (!items && !error) ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
              <Spinner className="h-6 w-6 text-brand-600" />
            </div>
          ) : items && items.length === 0 ? (
            <div className="empty-state">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 7h16M4 12h16M4 17h10" />
              </svg>
              <h3>落札した案件はまだありません</h3>
              <p>案件一覧から入札すると、落札後にここへ表示されます。</p>
            </div>
          ) : (
            <div className="txn-list">
              {items?.map((t) => (
                <Link href={`/operator/transactions/${t.id}`} className="txn-row" key={t.id}>
                  <div className="txn-row-info">
                    <div className="txn-row-title">{t.purpose}</div>
                    <div className="txn-row-meta">
                      {t.prefecture} {t.city} ・ 落札額 {formatYen(t.initial_amount)}
                      {t.final_amount != null && t.final_amount !== t.initial_amount
                        ? ` → 確定 ${formatYen(t.final_amount)}`
                        : ""}
                      ・ {new Date(t.created_at).toLocaleDateString("ja-JP")}
                    </div>
                  </div>
                  <div className="txn-row-right">
                    {t.has_pending_reduction ? <span className="status-chip warn">減額申請中</span> : null}
                    <span className={`status-chip ${txnChipClass(t.status)}`}>{TXN_STATUS_LABEL[t.status]}</span>
                    <Ic name="arrow" style={{ color: "var(--body-soft)", width: 16, height: 16 }} />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
