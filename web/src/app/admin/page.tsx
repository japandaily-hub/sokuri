"use client";

/** 管理画面: 招待コード発行（単発/バルク）/ 業者承認 / セル密度監視（role=admin のみ）。 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
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
  adminGetOperatorLicenseImage,
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
  const [operatorSearchQuery, setOperatorSearchQuery] = useState("");

  /* ---- 許可証画像確認モーダル ---- */
  const [licenseModalOperator, setLicenseModalOperator] = useState<OperatorOut | null>(null);
  const [licenseImageUrl, setLicenseImageUrl] = useState<string | null>(null);
  const [licenseImageLoading, setLicenseImageLoading] = useState(false);
  const [licenseImageError, setLicenseImageError] = useState<string | null>(null);
  // 直近でモーダルを開いた業者の id。fetch解決時にこれと不一致なら結果を捨てる
  // （業者Aのモーダルを開いた直後に業者Bへ素早く切り替えた場合の
  //  レース条件＝Aの遅延レスポンスがBの画面に誤表示される問題を防ぐガード）。
  const licenseRequestOperatorIdRef = useRef<string | null>(null);

  // licenseImageUrl が新しい値に切り替わる直前・アンマウント時に必ず revoke する
  // （blob URL のメモリリーク防止を useEffect の cleanup に一元化）。
  useEffect(() => {
    return () => {
      if (licenseImageUrl) URL.revokeObjectURL(licenseImageUrl);
    };
  }, [licenseImageUrl]);

  async function openLicenseModal(op: OperatorOut) {
    licenseRequestOperatorIdRef.current = op.id;
    setLicenseModalOperator(op);
    setLicenseImageUrl(null);
    setLicenseImageError(null);
    if (!token) return;
    setLicenseImageLoading(true);
    try {
      const blob = await adminGetOperatorLicenseImage(op.id, token);
      // fetch解決までの間に別の業者へ切り替えられていたら、この結果は表示しない。
      if (licenseRequestOperatorIdRef.current !== op.id) return;
      setLicenseImageUrl(URL.createObjectURL(blob));
    } catch (e) {
      if (licenseRequestOperatorIdRef.current !== op.id) return;
      setLicenseImageError(toDisplayMessage(e, "許可証画像の取得に失敗しました"));
    } finally {
      if (licenseRequestOperatorIdRef.current === op.id) setLicenseImageLoading(false);
    }
  }

  function closeLicenseModal() {
    // モーダルを閉じた後に前回のfetchが解決しても、もはやどの業者の表示にも一致しないため無視させる。
    licenseRequestOperatorIdRef.current = null;
    setLicenseModalOperator(null);
    setLicenseImageUrl(null);
    setLicenseImageError(null);
  }

  // エラーメッセージを表示し、画面上部のエラー表示までスクロールして見落としを防ぐ。
  function showError(message: string) {
    setError(message);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

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
      showError(toDisplayMessage(e, "取得に失敗しました"));
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
      showError(toDisplayMessage(e, "発行に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  async function issueBulk() {
    if (!token || busy) return;
    if (!Number.isInteger(bulkCount) || bulkCount < 1 || bulkCount > 500) {
      showError("発行件数は1〜500の整数で指定してください");
      return;
    }
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
      showError(toDisplayMessage(e, "バルク発行に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  // CSVインジェクション対策（先頭が =+-@\t\r の値はアプリで数式扱いされないよう ' を前置）と
  // 値中の " , 改行の正しいクォート処理をまとめて行う。
  function csvCell(value: string): string {
    let cell = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
    if (/["\n\r,]/.test(cell)) {
      cell = `"${cell.replace(/"/g, '""')}"`;
    }
    return cell;
  }

  function downloadBulkCsv(result: InviteBulkCreateResponse) {
    const now = new Date().toISOString().slice(0, 10);
    const header = ["code", "lot_name", "created_at"].map(csvCell).join(",");
    const rows = result.codes.map((c) =>
      [csvCell(c), csvCell(result.lot_name ?? ""), csvCell(now)].join(","),
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safeLot = (result.lot_name ?? "bulk").replace(/[\\/:*?"<>|\r\n\t]/g, "_").slice(0, 40) || "bulk";
    a.download = `invites_${safeLot}_${now}.csv`;
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
      showError(toDisplayMessage(e, "更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  // 承認（active化）の前だけ確認ダイアログを挟む。承認取消は従来通り即時実行する。
  function handleVerifyClick(op: OperatorOut) {
    if (op.vendor_status !== "active") {
      const ok = window.confirm(`${op.company_name}を承認（active化）します。よろしいですか？`);
      if (!ok) return;
    }
    void toggleVerify(op);
  }

  function copyCode(code: string) {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(code);
      setTimeout(() => setCopied(null), 1500);
    });
  }

  // 承認待ち（pending）が埋もれないよう pending → limited → active の順に並べる。
  // 同一ステータス内は既存の順序を維持するため、安定ソートに依存する。
  const VENDOR_STATUS_ORDER: Record<string, number> = { pending: 0, limited: 1, active: 2 };
  const sortedOperators = operators
    ? [...operators].sort(
        (a, b) =>
          (VENDOR_STATUS_ORDER[a.vendor_status] ?? 99) -
          (VENDOR_STATUS_ORDER[b.vendor_status] ?? 99),
      )
    : null;

  const normalizedOperatorSearch = operatorSearchQuery.trim().toLowerCase();
  const matchesOperatorSearch = (op: { company_name: string; contact_email: string }) =>
    normalizedOperatorSearch === "" ||
    op.company_name.toLowerCase().includes(normalizedOperatorSearch) ||
    op.contact_email.toLowerCase().includes(normalizedOperatorSearch);

  // 件数バッジは検索語を反映した件数にする（バッジと空状態表示が矛盾しないように）
  const searchedOperators = sortedOperators?.filter(matchesOperatorSearch) ?? null;
  const operatorStatusCounts =
    searchedOperators?.reduce<Record<string, number>>((acc, op) => {
      acc[op.vendor_status] = (acc[op.vendor_status] ?? 0) + 1;
      return acc;
    }, {}) ?? {};

  const filteredOperators = searchedOperators?.filter(
    (op) => statusFilter === "all" || op.vendor_status === statusFilter,
  );

  if (loading || (!invites && !error)) {
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
      <PageShell title="管理画面" description="業者招待コードの発行・アカウント承認・セル密度を管理します。">
      {error ? (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* 招待コード（単発） */}
        <Card>
          <h2 className="font-normal text-slate-900">業者招待コード（単発）</h2>
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
                  <p className="font-mono text-sm font-semibold text-slate-900">{inv.code}</p>
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
          <h2 className="font-normal text-slate-900">バルク発行</h2>
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
            <div className="mt-4 rounded-none bg-green-50 p-3">
              <p className="text-sm font-semibold text-green-800">
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-normal text-slate-900">業者アカウント</h2>
            <div className="flex flex-wrap gap-2">
              {["all", "active", "limited", "pending"].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatusFilter(s)}
                  className={`rounded-none px-3 py-1.5 text-xs font-medium transition-colors ${
                    statusFilter === s
                      ? "bg-brand-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {s === "all" ? "すべて" : s} {s === "all" ? searchedOperators?.length ?? 0 : operatorStatusCounts[s] ?? 0}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3">
            <input
              type="text"
              value={operatorSearchQuery}
              onChange={(e) => setOperatorSearchQuery(e.target.value)}
              className={inputBase}
              placeholder="会社名・メールで検索"
            />
          </div>
          <ul className="mt-4 divide-y divide-slate-100">
            {filteredOperators?.map((op) => {
              const statusInfo = VENDOR_STATUS_LABEL[op.vendor_status] ?? {
                label: op.vendor_status,
                badgeValue: "pending",
              };
              return (
                <li key={op.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{op.company_name}</p>
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
                      <StatusBadge
                        value={op.has_license_image ? "completed" : "pending"}
                        label={op.has_license_image ? "許可証: 提出済み" : "許可証: 未提出"}
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void openLicenseModal(op)}
                      disabled={!op.has_license_image}
                      className={btnSecondary}
                    >
                      許可証画像を確認
                    </button>
                    <div className="flex flex-col items-end gap-1">
                      <button
                        type="button"
                        onClick={() => handleVerifyClick(op)}
                        disabled={busy || (op.vendor_status !== "active" && !op.has_license_image)}
                        className={op.vendor_status === "active" ? btnSecondary : btnPrimary}
                      >
                        {op.vendor_status === "active" ? "承認を取消" : "承認する"}
                      </button>
                      {op.vendor_status !== "active" && !op.has_license_image ? (
                        <p className="text-xs text-red-600">
                          許可証画像が未提出のため承認できません
                        </p>
                      ) : null}
                    </div>
                  </div>
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
          <h2 className="font-normal text-slate-900">セル密度監視（需給バランス）</h2>
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
                          <span className="rounded-none border border-red-300 bg-transparent px-2 py-0.5 text-xs font-semibold text-red-700">
                            需要過多
                          </span>
                        ) : (
                          <span className="rounded-none border border-slate-300 bg-transparent px-2 py-0.5 text-xs text-slate-500">
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

      {/* 許可証画像確認モーダル */}
      {licenseModalOperator ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="licenseModalTitle"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={closeLicenseModal}
        >
          <div
            className="w-full max-w-lg rounded-none border border-slate-200 bg-white p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-4">
              <h2 id="licenseModalTitle" className="font-normal text-slate-900">
                {licenseModalOperator.company_name} の古物商許可証
              </h2>
              <button
                type="button"
                onClick={closeLicenseModal}
                aria-label="閉じる"
                className="shrink-0 rounded-none px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                ✕
              </button>
            </div>
            <div className="mt-4 flex min-h-[200px] items-center justify-center overflow-hidden rounded-none bg-slate-50">
              {licenseImageLoading ? (
                <Spinner className="h-6 w-6 text-brand-600" />
              ) : licenseImageError ? (
                <p className="p-4 text-center text-sm text-red-600">{licenseImageError}</p>
              ) : licenseImageUrl ? (
                // next/image はBlob URLの最適化に対応しないため、確認用途の一時表示としてimg要素を使う。
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={licenseImageUrl}
                  alt={`${licenseModalOperator.company_name}の古物商許可証画像`}
                  className="max-h-[70vh] w-full object-contain"
                />
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
