"use client";

/**
 * 管理画面: 業者事前申込（/business 経由）の審査（role=admin のみ）。
 * 一覧 → 行から詳細モーダルを開いて内容を確認 → 承認（招待コード発行）または却下（理由必須）。
 * 口座情報は下4桁マスクのみ一覧・詳細で表示し、必要な時だけボタンで全桁を復号取得する
 * （backend 側でアクセスがログ記録される。r4監査 H1/ADD-H1 対応）。
 * 既存 /admin（招待コード・業者承認）・/admin/identity-documents と同じ Tailwind/Card/StatusBadge/
 * ConfirmModal 構成を踏襲する。
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import {
  Card,
  Notice,
  PageShell,
  StatusBadge,
  btnDanger,
  btnPrimary,
  btnSecondary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import { AdminPagination } from "../_components/AdminPagination";
import { ConfirmModal } from "../_components/ConfirmModal";
import { CopyableId } from "../_components/CopyableId";
import { StatusFilterBar } from "../_components/StatusFilterBar";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  adminApproveOperatorApplication,
  adminListOperatorApplications,
  adminRejectOperatorApplication,
  adminRevealOperatorApplicationBankAccount,
  toDisplayMessage,
  type OperatorApplicationBankAccountRevealOut,
  type OperatorApplicationListResponse,
  type OperatorApplicationOut,
  type OperatorApplicationStatus,
} from "@/lib/katadzuke-api";

type StatusFilterValue = OperatorApplicationStatus | "all";

const STATUS_LABEL: Record<OperatorApplicationStatus, string> = {
  received: "審査待ち",
  approved: "承認済み",
  rejected: "却下",
};

const STATUS_BADGE_VALUE: Record<OperatorApplicationStatus, string> = {
  received: "pending",
  approved: "approved",
  rejected: "rejected",
};

const STATUS_OPTIONS: { value: StatusFilterValue; label: string }[] = [
  { value: "all", label: "すべて" },
  { value: "received", label: STATUS_LABEL.received },
  { value: "approved", label: STATUS_LABEL.approved },
  { value: "rejected", label: STATUS_LABEL.rejected },
];

/** L1 是正: backend が想定外の値を返した場合でも空白にせず「不明」を出す。 */
function accountTypeLabel(accountType: string): string {
  if (accountType === "ordinary") return "普通";
  if (accountType === "checking") return "当座";
  return "不明";
}

export default function AdminOperatorApplicationsPage() {
  const { token, loading } = useToken();
  // r4-fix-frontend2 M4: 検索・状態フィルタ・ページングを backend 側に委譲する
  // （旧: 先頭 ADMIN_LIST_DEFAULT_LIMIT 件のみをフロントで絞り込み・件数表示していた）。
  const [data, setData] = useState<OperatorApplicationListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [statusFilter, setStatusFilter] = useState<StatusFilterValue>("all");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);

  const [selected, setSelected] = useState<OperatorApplicationOut | null>(null);
  const [bankReveal, setBankReveal] = useState<OperatorApplicationBankAccountRevealOut | null>(
    null,
  );
  const [bankRevealLoading, setBankRevealLoading] = useState(false);
  const [bankRevealError, setBankRevealError] = useState<string | null>(null);

  const [rejectTarget, setRejectTarget] = useState<OperatorApplicationOut | null>(null);
  const [approveTarget, setApproveTarget] = useState<OperatorApplicationOut | null>(null);
  const [approveResult, setApproveResult] = useState<{ inviteCode: string } | null>(null);
  // r5-fix-frontend M-2: 失敗時にモーダルを閉じず、ConfirmModal の error prop へ表示する
  // （画面下部の行を操作した場合、ページ上部 Notice は画面外に出て見落とされやすいため）。
  const [approveModalError, setApproveModalError] = useState<string | null>(null);
  const [rejectModalError, setRejectModalError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    try {
      const res = await adminListOperatorApplications(
        { status: statusFilter, q, limit: ADMIN_LIST_DEFAULT_LIMIT, offset },
        token,
      );
      setData(res);
      setError(null);
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    } finally {
      setBusy(false);
    }
  }, [token, statusFilter, q, offset]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function changeStatus(next: StatusFilterValue) {
    setOffset(0);
    setStatusFilter(next);
  }

  function runSearch() {
    setOffset(0);
    setQ(qInput.trim());
  }

  function openDetail(app: OperatorApplicationOut) {
    setSelected(app);
    setBankReveal(null);
    setBankRevealError(null);
  }

  function closeDetail() {
    setSelected(null);
    setBankReveal(null);
    setBankRevealError(null);
  }

  async function revealBankAccount() {
    if (!selected || !token || bankRevealLoading) return;
    setBankRevealLoading(true);
    setBankRevealError(null);
    try {
      const result = await adminRevealOperatorApplicationBankAccount(selected.id, token);
      setBankReveal(result);
    } catch (e) {
      setBankRevealError(toDisplayMessage(e, "口座情報の取得に失敗しました"));
    } finally {
      setBankRevealLoading(false);
    }
  }

  async function confirmApprove() {
    if (!approveTarget || !token || busy) return;
    setBusy(true);
    setApproveModalError(null);
    try {
      const res = await adminApproveOperatorApplication(approveTarget.id, token);
      setApproveTarget(null);
      setApproveResult({ inviteCode: res.invite_code });
      closeDetail();
      await reload();
    } catch (e) {
      // r5-fix-frontend M-2 是正: 失敗時はモーダルを閉じず、ConfirmModal の error prop に
      // 表示する（409「既に審査済み」等の detail は backend が日本語で返すため
      // toDisplayMessage でそのまま表示される）。
      setApproveModalError(toDisplayMessage(e, "承認に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmReject(reason: string | null) {
    if (!rejectTarget || !token || busy) return;
    if (!reason || !reason.trim()) {
      // ConfirmModal 側で reasonRequired により空欄は確定ボタンが disabled になるため
      // 通常到達しないが、防御的に残す。
      setRejectModalError("却下理由を入力してください");
      return;
    }
    setBusy(true);
    setRejectModalError(null);
    try {
      await adminRejectOperatorApplication(rejectTarget.id, reason.trim(), token);
      setRejectTarget(null);
      closeDetail();
      await reload();
    } catch (e) {
      setRejectModalError(toDisplayMessage(e, "却下に失敗しました"));
    } finally {
      setBusy(false);
    }
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
        title="事前申込の審査"
        description="/business から届いた業者の事前申込を確認し、承認（招待コード発行）または却下します。"
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
        {approveResult ? (
          <div className="mb-4">
            <Notice tone="success">
              承認しました。招待コード：
              <span className="font-mono font-semibold">{approveResult.inviteCode}</span>
              （申込者へ承認メールで送付済みです）
              <button
                type="button"
                onClick={() => setApproveResult(null)}
                className="ml-3 text-xs underline"
              >
                閉じる
              </button>
            </Notice>
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
                placeholder="会社名／メール／許可番号（部分一致）"
              />
              <button type="button" onClick={runSearch} className={`${btnPrimary} shrink-0`}>
                検索
              </button>
            </div>
            {/* r4-fix-frontend2 M4: 状態フィルタ・検索・件数は backend 側の絞り込み結果
                （data.total）に基づく。件数はステータスごとの内訳ではなく現在の絞り込み結果の
                総件数のため、フィルタボタンに件数は付けない。 */}
            <StatusFilterBar options={STATUS_OPTIONS} value={statusFilter} onChange={changeStatus} />
          </div>

          <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="事前申込一覧">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-2 pr-4">ID</th>
                  <th className="pb-2 pr-4">会社名</th>
                  <th className="pb-2 pr-4">担当者</th>
                  <th className="pb-2 pr-4">メール</th>
                  <th className="pb-2 pr-4">許可番号</th>
                  <th className="pb-2 pr-4">申込日時</th>
                  <th className="pb-2 pr-4">状態</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((a) => (
                  <tr key={a.id}>
                    <td className="py-2 pr-4">
                      <CopyableId id={a.id} />
                    </td>
                    <td className="py-2 pr-4 text-slate-700">{a.company_name}</td>
                    <td className="py-2 pr-4 text-slate-700">{a.contact_name}</td>
                    <td className="py-2 pr-4 text-slate-700">{a.contact_email}</td>
                    <td className="py-2 pr-4 text-slate-700">{a.license_number}</td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {new Date(a.created_at).toLocaleString("ja-JP")}
                    </td>
                    <td className="py-2 pr-4">
                      <StatusBadge value={STATUS_BADGE_VALUE[a.status]} label={STATUS_LABEL[a.status]} />
                    </td>
                    <td className="py-2 text-right">
                      <button type="button" onClick={() => openDetail(a)} className={btnSecondary}>
                        詳細を確認
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && data.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">該当する申込はありません。</p>
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

      {selected ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="operatorApplicationModalTitle"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={closeDetail}
        >
          <div
            className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-none border border-slate-200 bg-white p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-4">
              <h2 id="operatorApplicationModalTitle" className="font-normal text-slate-900">
                {selected.company_name} の申込内容
              </h2>
              <button
                type="button"
                onClick={closeDetail}
                aria-label="閉じる"
                className="shrink-0 rounded-none px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                ✕
              </button>
            </div>
            <div className="mt-1">
              <StatusBadge
                value={STATUS_BADGE_VALUE[selected.status]}
                label={STATUS_LABEL[selected.status]}
              />
            </div>

            <dl className="mt-4 grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs text-slate-600">代表者名</dt>
                <dd className="text-slate-700">{selected.representative_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">古物商許可番号</dt>
                <dd className="text-slate-700">{selected.license_number}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-slate-600">法人登録住所</dt>
                <dd className="text-slate-700">{selected.registered_address}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">担当者名</dt>
                <dd className="text-slate-700">{selected.contact_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">電話番号</dt>
                <dd className="text-slate-700">{selected.contact_phone}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">事業形態</dt>
                <dd className="text-slate-700">
                  {selected.business_type === "corp"
                    ? "法人"
                    : selected.business_type === "sole"
                      ? "個人事業主"
                      : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">対応エリア</dt>
                <dd className="text-slate-700">{selected.service_area ?? "—"}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-slate-600">取扱カテゴリ</dt>
                <dd className="text-slate-700">{selected.categories ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">インボイス番号</dt>
                <dd className="text-slate-700">{selected.invoice_number ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">同意した規約バージョン</dt>
                <dd className="text-slate-700">{selected.agreed_terms_version ?? "—"}</dd>
              </div>
              {selected.message ? (
                <div className="sm:col-span-2">
                  <dt className="text-xs text-slate-600">メッセージ</dt>
                  <dd className="whitespace-pre-wrap text-slate-700">{selected.message}</dd>
                </div>
              ) : null}
              {selected.status === "rejected" && selected.reject_reason ? (
                <div className="sm:col-span-2">
                  <dt className="text-xs text-slate-600">却下理由</dt>
                  <dd className="text-slate-700">{selected.reject_reason}</dd>
                </div>
              ) : null}
            </dl>

            <div className="mt-4 border-t border-slate-100 pt-4">
              <h3 className="text-xs font-semibold text-slate-500">振込先口座情報</h3>
              {selected.bank_account ? (
                <div className="mt-2 text-sm text-slate-700">
                  <p>
                    {selected.bank_account.bank_name} {selected.bank_account.branch_name}（
                    {accountTypeLabel(selected.bank_account.account_type)}）
                  </p>
                  <p>
                    口座番号:{" "}
                    {bankReveal ? bankReveal.account_number : selected.bank_account.account_number_masked}
                  </p>
                  <p>口座名義: {bankReveal ? bankReveal.account_holder : selected.bank_account.account_holder}</p>
                  {!bankReveal ? (
                    <button
                      type="button"
                      onClick={() => void revealBankAccount()}
                      disabled={bankRevealLoading}
                      className={`${btnSecondary} mt-2`}
                    >
                      {bankRevealLoading ? "取得中…" : "口座情報を全桁表示"}
                    </button>
                  ) : null}
                  {bankRevealError ? (
                    <p className="mt-1 text-xs text-red-600">{bankRevealError}</p>
                  ) : null}
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-500">口座情報は登録されていません。</p>
              )}
            </div>

            {selected.status === "received" ? (
              <div className="mt-4 flex justify-end gap-2 border-t border-slate-100 pt-4">
                <button
                  type="button"
                  className={btnDanger}
                  disabled={busy}
                  onClick={() => {
                    setRejectModalError(null);
                    setRejectTarget(selected);
                  }}
                >
                  却下する
                </button>
                <button
                  type="button"
                  className={btnPrimary}
                  disabled={busy}
                  onClick={() => {
                    setApproveModalError(null);
                    setApproveTarget(selected);
                  }}
                >
                  承認する
                </button>
              </div>
            ) : (
              <p className="mt-4 border-t border-slate-100 pt-4 text-xs text-slate-600">
                審査済み（
                {selected.reviewed_at ? new Date(selected.reviewed_at).toLocaleString("ja-JP") : "—"}
                ）のため操作できません。
              </p>
            )}
          </div>
        </div>
      ) : null}

      {approveTarget ? (
        <ConfirmModal
          title={`${approveTarget.company_name}を承認します`}
          message="承認すると招待コードが発行され、申込者へ承認メールが送信されます。よろしいですか？"
          confirmLabel="承認する"
          error={approveModalError}
          busy={busy}
          onCancel={() => {
            setApproveModalError(null);
            setApproveTarget(null);
          }}
          onConfirm={() => void confirmApprove()}
        />
      ) : null}

      {rejectTarget ? (
        <ConfirmModal
          title={`${rejectTarget.company_name}を却下します`}
          message="却下理由は申込者へメールで送信されます。理由を入力してください。"
          confirmLabel="却下する"
          danger
          withReason
          reasonRequired
          reasonLabel="却下理由（必須・申込者に表示されます）"
          error={rejectModalError}
          busy={busy}
          onCancel={() => {
            setRejectModalError(null);
            setRejectTarget(null);
          }}
          onConfirm={(reason) => void confirmReject(reason)}
        />
      ) : null}
    </div>
  );
}
