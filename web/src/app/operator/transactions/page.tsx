"use client";

/** 業者: 落札案件の一覧（落札管理の入口）。 */

import { useEffect, useState } from "react";
import { Spinner } from "@/components/Icon";
import {
  Card,
  Notice,
  PageShell,
  StatusBadge,
  btnSecondary,
  useToken,
} from "@/components/kdz/Ui";
import {
  TXN_STATUS_LABEL,
  formatYen,
  listTransactions,
  toDisplayMessage,
  type TransactionListItem,
} from "@/lib/katadzuke-api";

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

  if (loading || (!items && !error)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  return (
    <PageShell
      title="落札管理"
      description="落札した案件の進行状況です。"
      actions={
        <a href="/operator/cases" className={btnSecondary}>
          案件一覧へ
        </a>
      }
    >
      {error ? <Notice tone="error">{error}</Notice> : null}
      {items && items.length === 0 ? (
        <Card className="text-center text-sm text-slate-500">落札した案件はまだありません。</Card>
      ) : null}
      <div className="space-y-3">
        {items?.map((t) => (
          <a key={t.id} href={`/operator/transactions/${t.id}`} className="group block">
            <Card className="flex flex-wrap items-center justify-between gap-3 transition-shadow group-hover:shadow-md">
              <div>
                <p className="font-bold text-slate-900">
                  {t.purpose}{" "}
                  <span className="text-sm font-medium text-slate-500">
                    {t.prefecture} {t.city}
                  </span>
                </p>
                <p className="mt-0.5 text-sm text-slate-500">
                  落札額 {formatYen(t.initial_amount)}
                  {t.final_amount != null && t.final_amount !== t.initial_amount
                    ? ` → 確定 ${formatYen(t.final_amount)}`
                    : ""}
                  ・ {new Date(t.created_at).toLocaleDateString("ja-JP")}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {t.has_pending_reduction ? (
                  <StatusBadge value="pending" label="減額申請中" />
                ) : null}
                <StatusBadge value={t.status} label={TXN_STATUS_LABEL[t.status]} />
              </div>
            </Card>
          </a>
        ))}
      </div>
    </PageShell>
  );
}
