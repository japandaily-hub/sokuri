"use client";

/**
 * 管理画面: 成約（取引）の横断閲覧（role=admin のみ）。
 * トラブル介入の起点として、admin自身が当事者ではない成約も検索・閲覧できるようにする。
 * 既存 /admin（招待コード・業者承認）と同じ Tailwind/Card/StatusBadge 構成を踏襲する。
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Card, Notice, PageShell, StatusBadge, btnPrimary, btnSecondary, inputBase, useToken } from "@/components/kdz/Ui";
import { AdminPagination } from "../_components/AdminPagination";
import { ConfirmModal } from "../_components/ConfirmModal";
import { CopyableId } from "../_components/CopyableId";
import { StatusFilterBar } from "../_components/StatusFilterBar";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  CANCELLED_BY_LABEL,
  TXN_STATUS_LABEL,
  adminCancelTransaction,
  adminListTransactions,
  formatYen,
  toDisplayMessage,
  type AdminTransactionListItem,
  type AdminTransactionListResponse,
  type TransactionStatus,
} from "@/lib/katadzuke-api";
import { formatVisitSchedule } from "@/lib/categories";

type StatusFilterValue = TransactionStatus | "all";

const STATUS_OPTIONS: { value: StatusFilterValue; label: string }[] = [
  { value: "all", label: "すべて" },
  ...(Object.keys(TXN_STATUS_LABEL) as TransactionStatus[]).map((s) => ({
    value: s,
    label: TXN_STATUS_LABEL[s],
  })),
];

/** cancelled_by は backend 契約上 string（将来値追加への耐性）のため、未知値は素通しする。 */
function cancelledByLabel(value: string | null): string {
  if (value == null) return "—";
  return (CANCELLED_BY_LABEL as Record<string, string>)[value] ?? value;
}

export default function AdminTransactionsPage() {
  const { token, loading } = useToken();
  const [data, setData] = useState<AdminTransactionListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilterValue>("all");
  const [offset, setOffset] = useState(0);

  // r8-fix-frontend2 M5 是正: 依頼者停止等で当事者が動かせなくなった取引を
  // 運営が強制終了できる手段が無かったため、一覧に強制終了ボタン（理由必須）を追加する。
  const [cancelTarget, setCancelTarget] = useState<AdminTransactionListItem | null>(null);
  const [cancelModalError, setCancelModalError] = useState<string | null>(null);
  const [cancelBusy, setCancelBusy] = useState(false);

  function closeCancelModal() {
    setCancelTarget(null);
    setCancelModalError(null);
  }

  async function confirmForceCancel(reason: string | null) {
    if (!cancelTarget || !token) return;
    const trimmed = (reason ?? "").trim();
    if (!trimmed) {
      setCancelModalError("理由を入力してください。");
      return;
    }
    setCancelBusy(true);
    setCancelModalError(null);
    try {
      await adminCancelTransaction(cancelTarget.id, trimmed, token);
      closeCancelModal();
      await reload();
    } catch (e) {
      // r5-fix-frontend M-2 と同型: 失敗時はモーダルを閉じず、error prop に表示する。
      setCancelModalError(toDisplayMessage(e, "強制終了に失敗しました"));
    } finally {
      setCancelBusy(false);
    }
  }

  const reload = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    try {
      const res = await adminListTransactions(
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
        title="取引一覧"
        description="全ての成約（取引）を横断的に検索・閲覧できます。トラブル介入時の起点です。"
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
                placeholder="取引ID・案件ID（完全一致）／依頼者メール・業者名（部分一致）で検索"
              />
              <button type="button" onClick={runSearch} className={`${btnPrimary} shrink-0`}>
                検索
              </button>
            </div>
            <StatusFilterBar options={STATUS_OPTIONS} value={statusFilter} onChange={changeStatus} />
          </div>

          <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="取引一覧">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-2 pr-4">ID</th>
                  <th className="pb-2 pr-4">状態</th>
                  <th className="pb-2 pr-4">成約日時</th>
                  <th className="pb-2 pr-4">依頼者</th>
                  <th className="pb-2 pr-4">業者</th>
                  <th className="pb-2 pr-4 text-right">金額</th>
                  <th className="pb-2 pr-4">訪問予定</th>
                  <th className="pb-2 pr-4">キャンセル元</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((t) => (
                  <tr key={t.id}>
                    <td className="py-2 pr-4">
                      <CopyableId id={t.id} />
                    </td>
                    <td className="py-2 pr-4">
                      <StatusBadge value={t.status} label={TXN_STATUS_LABEL[t.status]} />
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {new Date(t.created_at).toLocaleString("ja-JP")}
                    </td>
                    <td className="py-2 pr-4 text-slate-700">{t.user_email ?? "—"}</td>
                    <td className="py-2 pr-4 text-slate-700">{t.company_name ?? "—"}</td>
                    <td className="py-2 pr-4 text-right whitespace-nowrap">{formatYen(t.amount)}</td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {t.visit_date ? formatVisitSchedule(t.visit_date, null) : "—"}
                    </td>
                    <td className="py-2 pr-4 text-slate-500">{cancelledByLabel(t.cancelled_by)}</td>
                    <td className="py-2 text-right whitespace-nowrap">
                      <Link href={`/chat/${t.id}`} className={btnSecondary}>
                        依頼者画面で開く
                      </Link>
                      {t.status !== "cancelled" && t.status !== "completed" ? (
                        <button
                          type="button"
                          className={`${btnSecondary} ml-2`}
                          style={{ borderColor: "#dc2626", color: "#dc2626" }}
                          onClick={() => {
                            setCancelModalError(null);
                            setCancelTarget(t);
                          }}
                        >
                          強制終了
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && data.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">該当する取引はありません。</p>
            ) : null}
            {busy ? (
              <div className="flex items-center gap-2 py-3 text-sm text-slate-600">
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

      {cancelTarget ? (
        <ConfirmModal
          title="この取引を強制終了しますか？"
          message="依頼者・業者どちらも応答不能等で進行不能な取引を、運営の判断で終了します。入力した理由は依頼者・業者の双方に表示されます。この操作は元に戻せません。"
          confirmLabel="強制終了する"
          danger
          withReason
          reasonLabel="終了理由（必須・当事者双方に表示されます）"
          reasonRequired
          error={cancelModalError}
          busy={cancelBusy}
          onCancel={closeCancelModal}
          onConfirm={(reason) => void confirmForceCancel(reason)}
        />
      ) : null}
    </div>
  );
}
