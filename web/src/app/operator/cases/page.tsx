"use client";

/** 業者: 入札可能な案件一覧（住所は市区町村まで）。 */

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
  CASE_STATUS_LABEL,
  KdzApiError,
  formatYen,
  listOpenCases,
  photoSrc,
  toDisplayMessage,
  type CaseMasked,
} from "@/lib/katadzuke-api";

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

  if (loading || (!cases && !error && !pendingApproval)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  return (
    <PageShell
      title="案件一覧"
      description="入札を受け付けている片付け案件です。住所は業者決定後に開示されます。"
      actions={
        <a href="/operator/transactions" className={btnSecondary}>
          落札管理へ
        </a>
      }
    >
      {pendingApproval ? (
        <Notice tone="warn">
          アカウントは運営の承認待ちです。承認が完了すると案件を閲覧できます（通常1営業日以内）。
        </Notice>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}
      {cases && cases.length === 0 ? (
        <Card className="text-center text-sm text-slate-500">
          現在、入札可能な案件はありません。
        </Card>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {cases?.map((c) => (
          <a key={c.id} href={`/operator/cases/${c.id}`} className="group">
            <Card className="h-full transition-shadow group-hover:shadow-md">
              <div className="flex items-start justify-between gap-3">
                <div className="flex gap-3">
                  {c.photos[0] ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={photoSrc(c.photos[0].url)}
                      alt=""
                      className="h-16 w-16 shrink-0 rounded-xl border border-slate-200 object-cover"
                    />
                  ) : (
                    <div className="h-16 w-16 shrink-0 rounded-xl bg-slate-100" />
                  )}
                  <div>
                    <p className="font-bold text-slate-900">{c.purpose}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {c.prefecture} {c.city} / {c.housing_type ?? "—"} /{" "}
                      {c.floor_plan ?? "—"}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      入札 {c.bid_count} 件 ・{" "}
                      {new Date(c.created_at).toLocaleDateString("ja-JP")}
                    </p>
                  </div>
                </div>
                <StatusBadge value={c.status} label={CASE_STATUS_LABEL[c.status]} />
              </div>
              {c.ai_summary ? (
                <p className="mt-3 line-clamp-2 text-sm leading-relaxed text-slate-600">
                  {c.ai_summary}
                </p>
              ) : null}
              {c.my_bid ? (
                <p className="mt-3 text-sm font-semibold text-brand-700">
                  自社入札済み: {formatYen(c.my_bid.amount)}
                </p>
              ) : null}
            </Card>
          </a>
        ))}
      </div>
    </PageShell>
  );
}
