"use client";

/** 管理画面: 招待コード発行（単発/バルク）/ 業者承認 / セル密度監視（role=admin のみ）。 */

import { useCallback, useEffect, useState } from "react";
import { Spinner } from "@/components/Icon";
import {
  Card,
  Notice,
  PageShell,
  StatusBadge,
  btnPrimary,
  btnSecondary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import {
  adminBulkCreateInvites,
  adminCreateInvite,
  adminGetCellDensity,
  adminListInvites,
  adminListOperators,
  adminVerifyOperator,
  toDisplayMessage,
  type CellDensityRow,
  type InviteBulkCreateResponse,
  type InviteOut,
  type OperatorOut,
} from "@/lib/katadzuke-api";

const VENDOR_STATUS_LABEL: Record<string, { label: string; badgeValue: string }> = {
  active: { label: "active（フル稼働）", badgeValue: "completed" },
  limited: { label: "limited（暫定稼働）", badgeValue: "pending" },
  pending: { label: "pending（未承認）", badgeValue: "rejected" },
};

export default function AdminPage() {
  const { token, loading } = useToken();
  const [invites, setInvites] = useState<InviteOut[] | null>(null);
  const [operators, setOperators] = useState<OperatorOut[] | null>(null);
  const [cellDensity, setCellDensity] = useState<CellDensityRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [inviteEmail, setInviteEmail] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  const [bulkCount, setBulkCount] = useState(10);
  const [bulkLotName, setBulkLotName] = useState("");
  const [bulkResult, setBulkResult] = useState<InviteBulkCreateResponse | null>(null);

  const [statusFilter, setStatusFilter] = useState<string>("all");

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      const [inv, ops, density] = await Promise.all([
        adminListInvites(token),
        adminListOperators(token),
        adminGetCellDensity(token),
      ]);
      setInvites(inv);
      setOperators(ops);
      setCellDensity(density);
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function issueInvite() {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      await adminCreateInvite(inviteEmail.trim() || null, token);
      setInviteEmail("");
      await reload();
    } catch (e) {
      setError(toDisplayMessage(e, "発行に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  async function issueBulk() {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    setBulkResult(null);
    try {
      const result = await adminBulkCreateInvites(
        bulkCount,
        bulkLotName.trim() || undefined,
        token,
      );
      setBulkResult(result);
      await reload();
    } catch (e) {
      setError(toDisplayMessage(e, "バルク発行に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  function downloadBulkCsv(result: InviteBulkCreateResponse) {
    const now = new Date().toISOString().slice(0, 10);
    const header = "code,lot_name,created_at";
    const rows = result.codes.map((c) => `${c},${result.lot_name ?? ""},${now}`);
    const csv = [header, ...rows].join("\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `invites_${result.lot_name ?? "bulk"}_${now}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function toggleVerify(op: OperatorOut) {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      await adminVerifyOperator(op.id, op.vendor_status !== "active", token);
      await reload();
    } catch (e) {
      setError(toDisplayMessage(e, "更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  function copyCode(code: string) {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(code);
      setTimeout(() => setCopied(null), 1500);
    });
  }

  const filteredOperators =
    statusFilter === "all"
      ? operators
      : operators?.filter((op) => op.vendor_status === statusFilter);

  if (loading || (!invites && !error)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  return (
    <PageShell title="管理画面" description="業者招待コードの発行・アカウント承認・セル密度を管理します。">
      {error ? (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* 招待コード（単発） */}
        <Card>
          <h2 className="font-bold text-slate-900">業者招待コード（単発）</h2>
          <div className="mt-3 flex gap-2">
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className={inputBase}
              placeholder="送付先メール（任意・メモ用）"
            />
            <button
              type="button"
              onClick={issueInvite}
              disabled={busy}
              className={`${btnPrimary} shrink-0`}
            >
              発行
            </button>
          </div>
          <ul className="mt-4 max-h-64 divide-y divide-slate-100 overflow-y-auto">
            {invites?.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between gap-2 py-2.5">
                <div>
                  <p className="font-mono text-sm font-bold text-slate-900">{inv.code}</p>
                  <p className="text-xs text-slate-400">
                    {inv.email ?? "宛先未指定"}
                    {inv.lot_name ? ` ・ lot: ${inv.lot_name}` : ""}
                    {" ・ "}
                    {new Date(inv.created_at).toLocaleDateString("ja-JP")}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {inv.used_at ? (
                    <StatusBadge value="rejected" label="使用済み" />
                  ) : (
                    <>
                      <StatusBadge value="open" label="未使用" />
                      <button
                        type="button"
                        onClick={() => copyCode(inv.code)}
                        className={btnSecondary}
                      >
                        {copied === inv.code ? "コピー済" : "コピー"}
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
            {invites && invites.length === 0 ? (
              <li className="py-3 text-sm text-slate-500">まだ発行されていません。</li>
            ) : null}
          </ul>
        </Card>

        {/* バルク発行 */}
        <Card>
          <h2 className="font-bold text-slate-900">バルク発行</h2>
          <div className="mt-3 space-y-2">
            <div className="flex gap-2">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-slate-500">発行件数（1〜500）</label>
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={bulkCount}
                  onChange={(e) => setBulkCount(Number(e.target.value))}
                  className={`${inputBase} w-28`}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <label className="text-xs text-slate-500">ロット名（任意・管理用）</label>
                <input
                  type="text"
                  value={bulkLotName}
                  onChange={(e) => setBulkLotName(e.target.value)}
                  className={inputBase}
                  placeholder="例: 首都圏営業_2026Q3"
                />
              </div>
            </div>
            <button
              type="button"
              onClick={issueBulk}
              disabled={busy}
              className={`${btnPrimary} w-full`}
            >
              {busy ? "発行中…" : `${bulkCount}件まとめて発行`}
            </button>
          </div>
          {bulkResult ? (
            <div className="mt-4 rounded-lg bg-green-50 p-3">
              <p className="text-sm font-bold text-green-800">
                {bulkResult.count}件発行完了
                {bulkResult.lot_name ? `（ロット: ${bulkResult.lot_name}）` : ""}
              </p>
              <p className="mt-1 text-xs text-green-700">
                最初のコード: {bulkResult.codes[0]}
              </p>
              <button
                type="button"
                onClick={() => downloadBulkCsv(bulkResult)}
                className={`${btnSecondary} mt-2`}
              >
                CSVダウンロード
              </button>
            </div>
          ) : null}
        </Card>
      </div>

      {/* 業者承認 */}
      <div className="mt-6">
        <Card>
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-slate-900">業者アカウント</h2>
            <div className="flex gap-2">
              {["all", "active", "limited", "pending"].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatusFilter(s)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    statusFilter === s
                      ? "bg-brand-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {s === "all" ? "すべて" : s}
                </button>
              ))}
            </div>
          </div>
          <ul className="mt-4 divide-y divide-slate-100">
            {filteredOperators?.map((op) => {
              const statusInfo = VENDOR_STATUS_LABEL[op.vendor_status] ?? {
                label: op.vendor_status,
                badgeValue: "pending",
              };
              return (
                <li key={op.id} className="flex items-center justify-between gap-2 py-2.5">
                  <div>
                    <p className="text-sm font-bold text-slate-900">{op.company_name}</p>
                    <p className="text-xs text-slate-400">
                      {op.contact_email}
                      {op.license_number ? ` ・ ${op.license_number}` : ""}
                    </p>
                    <div className="mt-1 flex gap-1.5">
                      <StatusBadge
                        value={statusInfo.badgeValue as "completed" | "pending" | "rejected"}
                        label={statusInfo.label}
                      />
                      {op.is_suspended ? <StatusBadge value="cancelled" label="停止中" /> : null}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleVerify(op)}
                    disabled={busy}
                    className={op.vendor_status === "active" ? btnSecondary : btnPrimary}
                  >
                    {op.vendor_status === "active" ? "承認を取消" : "承認する（active化）"}
                  </button>
                </li>
              );
            })}
            {filteredOperators && filteredOperators.length === 0 ? (
              <li className="py-3 text-sm text-slate-500">該当業者はいません。</li>
            ) : null}
          </ul>
        </Card>
      </div>

      {/* セル密度監視 */}
      <div className="mt-6">
        <Card>
          <h2 className="font-bold text-slate-900">セル密度監視（需給バランス）</h2>
          <p className="mt-1 text-xs text-slate-500">
            都道府県×目的別の直近30日案件数 / アクティブ業者数。1.5超は赤表示（需要過多）。
          </p>
          {cellDensity && cellDensity.length > 0 ? (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                    <th className="pb-2 pr-4">都道府県</th>
                    <th className="pb-2 pr-4">目的</th>
                    <th className="pb-2 pr-4 text-right">案件数</th>
                    <th className="pb-2 pr-4 text-right">業者数</th>
                    <th className="pb-2 pr-4 text-right">需給比率</th>
                    <th className="pb-2 text-center">状態</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {cellDensity.map((row, i) => (
                    <tr
                      key={i}
                      className={row.status === "dense" ? "bg-red-50" : ""}
                    >
                      <td className="py-2 pr-4 font-medium">{row.prefecture}</td>
                      <td className="py-2 pr-4 text-slate-600">{row.purpose}</td>
                      <td className="py-2 pr-4 text-right">{row.open_cases}</td>
                      <td className="py-2 pr-4 text-right">{row.active_suppliers}</td>
                      <td className="py-2 pr-4 text-right font-mono">
                        {row.demand_per_supplier.toFixed(2)}
                      </td>
                      <td className="py-2 text-center">
                        {row.status === "dense" ? (
                          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700">
                            需要過多
                          </span>
                        ) : (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                            通常
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : cellDensity && cellDensity.length === 0 ? (
            <p className="mt-4 text-sm text-slate-500">直近30日に案件はありません。</p>
          ) : (
            <div className="mt-4 flex items-center gap-2 text-sm text-slate-400">
              <Spinner className="h-4 w-4" /> 読み込み中…
            </div>
          )}
        </Card>
      </div>
    </PageShell>
  );
}
