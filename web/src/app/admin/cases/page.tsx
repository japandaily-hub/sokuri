"use client";

/**
 * 管理画面: 案件の横断閲覧（role=admin のみ）。
 * トラブル介入の起点として、admin自身が作成した案件だけでなく全案件を検索・閲覧できるようにする。
 * 既存 /admin（招待コード・業者承認）と同じ Tailwind/Card/StatusBadge 構成を踏襲する。
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Card, Notice, PageShell, StatusBadge, btnPrimary, btnSecondary, inputBase, useToken } from "@/components/kdz/Ui";
import { AdminPagination } from "../_components/AdminPagination";
import { CopyableId } from "../_components/CopyableId";
import { StatusFilterBar } from "../_components/StatusFilterBar";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  CASE_STATUS_LABEL,
  adminListCases,
  formatYen,
  toDisplayMessage,
  type AdminCaseListResponse,
  type CaseStatus,
} from "@/lib/katadzuke-api";
import { formatVisitSchedule } from "@/lib/categories";

type StatusFilterValue = CaseStatus | "all";

const STATUS_OPTIONS: { value: StatusFilterValue; label: string }[] = [
  { value: "all", label: "すべて" },
  ...(Object.keys(CASE_STATUS_LABEL) as CaseStatus[]).map((s) => ({
    value: s,
    label: CASE_STATUS_LABEL[s],
  })),
];

export default function AdminCasesPage() {
  const { token, loading } = useToken();
  const [data, setData] = useState<AdminCaseListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilterValue>("all");
  const [offset, setOffset] = useState(0);

  const reload = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    try {
      const res = await adminListCases(
        { q, status: statusFilter, limit: ADMIN_LIST_DEFAULT_LIMIT, offset },
        token,
      );
      setData(res);
      setError(null);
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    } finally {
      setBusy(false);
    }
  }, [token, q, statusFilter, offset]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function runSearch() {
    setOffset(0);
    setQ(qInput.trim());
  }

  function changeStatus(next: StatusFilterValue) {
    setOffset(0);
    setStatusFilter(next);
  }

  if (loading || (!data && !error)) {
    return (
      <div className="admin-page">
        <AppHeader showBell={false} />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AppHeader showBell={false} />
      <PageShell
        title="案件一覧"
        description="全ての依頼案件を横断的に検索・閲覧できます。トラブル介入時の起点です。"
        actions={
          <Link href="/admin" className={btnSecondary}>
            管理画面トップへ
          </Link>
        }
      >
        {error ? (
          <div className="mb-4">
            <Notice tone="error">{error}</Notice>
          </div>
        ) : null}

        <Card>
          <div className="flex flex-col gap-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") runSearch();
                }}
                className={inputBase}
                placeholder="案件ID（前方一致）・依頼者メール（部分一致）で検索"
              />
              <button type="button" onClick={runSearch} className={`${btnPrimary} shrink-0`}>
                検索
              </button>
            </div>
            <StatusFilterBar options={STATUS_OPTIONS} value={statusFilter} onChange={changeStatus} />
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-2 pr-4">ID</th>
                  <th className="pb-2 pr-4">状態</th>
                  <th className="pb-2 pr-4">依頼日時</th>
                  <th className="pb-2 pr-4">依頼者</th>
                  <th className="pb-2 pr-4">用途／所在地</th>
                  <th className="pb-2 pr-4">業者</th>
                  <th className="pb-2 pr-4 text-right">金額</th>
                  <th className="pb-2 pr-4">訪問予定</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((c) => (
                  <tr key={c.id}>
                    <td className="py-2 pr-4">
                      <CopyableId id={c.id} />
                    </td>
                    <td className="py-2 pr-4">
                      <StatusBadge value={c.status} label={CASE_STATUS_LABEL[c.status]} />
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {new Date(c.created_at).toLocaleString("ja-JP")}
                    </td>
                    <td className="py-2 pr-4 text-slate-700">{c.user_email ?? "—"}</td>
                    <td className="py-2 pr-4 text-slate-700">
                      {c.purpose} ・ {c.prefecture}{c.city}
                    </td>
                    <td className="py-2 pr-4 text-slate-700">{c.company_name ?? "—"}</td>
                    <td className="py-2 pr-4 text-right whitespace-nowrap">{formatYen(c.amount)}</td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {c.visit_date ? formatVisitSchedule(c.visit_date, null) : "—"}
                    </td>
                    <td className="py-2 text-right">
                      <Link href={`/cases/${c.id}`} className={btnSecondary}>
                        依頼者画面で開く
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && data.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">該当する案件はありません。</p>
            ) : null}
            {busy ? (
              <div className="flex items-center gap-2 py-3 text-sm text-slate-400">
                <Spinner className="h-4 w-4" /> 読み込み中…
              </div>
            ) : null}
          </div>

          {data ? (
            <AdminPagination
              total={data.total}
              limit={ADMIN_LIST_DEFAULT_LIMIT}
              offset={offset}
              itemCount={data.items.length}
              onPrev={() => setOffset(Math.max(0, offset - ADMIN_LIST_DEFAULT_LIMIT))}
              onNext={() => setOffset(offset + ADMIN_LIST_DEFAULT_LIMIT)}
            />
          ) : null}
        </Card>
      </PageShell>
    </div>
  );
}
