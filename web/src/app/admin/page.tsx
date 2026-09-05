"use client";

/** 管理画面: 招待コード発行（単発/バルク）/ 業者承認 / セル密度監視（role=admin のみ）。 */

import { useCallback, useEffect, useRef, useState } from "react";
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
import { AdminPagination } from "./_components/AdminPagination";
import { ConfirmModal } from "./_components/ConfirmModal";
import { formatPurposeLabel } from "@/lib/case-labels";
import { StatusFilterBar } from "./_components/StatusFilterBar";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  adminBulkCreateInvites,
  adminCreateInvite,
  adminGetCellDensity,
  adminGetOperatorLicenseImage,
  adminListContacts,
  adminListInvites,
  adminListOperatorApplications,
  adminListOperators,
  adminSuspendOperator,
  adminVerifyOperator,
  listIdentityDocumentsAdmin,
  toDisplayMessage,
  type AdminOperatorListResponse,
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
  const [operatorsData, setOperatorsData] = useState<AdminOperatorListResponse | null>(null);
  const [cellDensity, setCellDensity] = useState<CellDensityRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // r4-fix-frontend2 M1: reload() を Promise.allSettled に分離した各区画専用のエラー。
  // 1区画の5xxで他区画（招待コード・業者・セル密度）が使えなくなるのを防ぐ。
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [operatorListError, setOperatorListError] = useState<string | null>(null);
  const [cellDensityError, setCellDensityError] = useState<string | null>(null);
  /** reload() が一度でも完了したか。allSettled化により単一の error state だけでは
   *  初回スケルトン表示の終了を判定できないため専用フラグを持つ。 */
  const [initialLoadDone, setInitialLoadDone] = useState(false);

  const [inviteEmail, setInviteEmail] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  const [bulkCount, setBulkCount] = useState(10);
  const [bulkLotName, setBulkLotName] = useState("");
  const [bulkResult, setBulkResult] = useState<InviteBulkCreateResponse | null>(null);

  // r5-fix-frontend H-1: 検索・状態絞り込みは backend 側の絞り込み結果（total/counts）に
  // 基づく。operatorSearchInput は入力中の値、operatorSearchQuery は「検索」実行済みの値
  // （他の admin 一覧ページの qInput/q と同じパターン）。
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [operatorSearchInput, setOperatorSearchInput] = useState("");
  const [operatorSearchQuery, setOperatorSearchQuery] = useState("");
  const [operatorOffset, setOperatorOffset] = useState(0);
  // r8-fix-frontend4: 退会済み業者は既定で一覧・counts から除外される（backend 既定 include_deleted=false）。
  // 運営が「一覧から消えた業者」を判別できるよう、明示トグルで含める。
  const [includeDeletedOperators, setIncludeDeletedOperators] = useState(false);
  const [inviteOffset, setInviteOffset] = useState(0);

  /** 事前申込の未審査（status==="received"）件数（ナビのバッジ用）。
   *  backend の GET /admin/operator-applications?status=received&limit=1 が返す total を使う
   *  （r4-fix-frontend2 M4: 先頭ページ内カウントの近似表示から backend 側の正確な総件数に切替）。 */
  const [pendingApplications, setPendingApplications] = useState<number | null>(null);
  const [pendingApplicationsError, setPendingApplicationsError] = useState<string | null>(null);

  /** 本人確認書類の審査待ち件数（r10 O-M1）。counts.pending は絞り込みに依らない全体の内訳。 */
  const [pendingIdentityDocs, setPendingIdentityDocs] = useState<number | null>(null);
  const [pendingIdentityDocsError, setPendingIdentityDocsError] = useState<string | null>(null);
  /** 未対応のお問い合わせ件数（r10 O-M6）。handled=false&limit=1 の total を使う。 */
  const [unhandledContacts, setUnhandledContacts] = useState<number | null>(null);
  const [unhandledContactsError, setUnhandledContactsError] = useState<string | null>(null);

  const [suspendTarget, setSuspendTarget] = useState<OperatorOut | null>(null);
  // r5-fix-frontend M-2: 失敗時にモーダルを閉じず、ConfirmModal の error prop へ表示する
  // （モーダルを閉じた後の画面上部 Notice は見落とされやすいため）。
  const [suspendModalError, setSuspendModalError] = useState<string | null>(null);
  const [verifyTarget, setVerifyTarget] = useState<OperatorOut | null>(null);
  const [verifyModalError, setVerifyModalError] = useState<string | null>(null);

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

  // r4-fix-frontend2 M1: 6本を Promise.allSettled にし、1本の5xxで画面全体が
  // 不能にならないようにする。各区画は自分の結果だけを見て自分の error state を更新する。
  const reload = useCallback(async () => {
    if (!token) return;
    // r10-review H1 是正: 以下のブロックで（旧応答形式との不整合等により）同期的に例外が
    // 投げられると reload() の Promise が reject し、void reload() 経由の呼び出しでは
    // 未処理のまま setInitialLoadDone(true) に到達しなくなる（/admin が永久スピナー）。
    // finally で必ず解除する。
    try {
      const [invResult, opsResult, densityResult, appsResult, identityResult, contactsResult] =
        await Promise.allSettled([
          adminListInvites({ limit: ADMIN_LIST_DEFAULT_LIMIT, offset: inviteOffset }, token),
          adminListOperators(
            {
              status: statusFilter,
              q: operatorSearchQuery,
              limit: ADMIN_LIST_DEFAULT_LIMIT,
              offset: operatorOffset,
              includeDeleted: includeDeletedOperators,
            },
            token,
          ),
          adminGetCellDensity(token),
          adminListOperatorApplications({ status: "received", limit: 1, offset: 0 }, token),
          // r10 O-M1 / O-M6: 件数バッジ専用の最小取得（limit=1）。本文は各専用画面で読む。
          listIdentityDocumentsAdmin({ status: "pending", limit: 1, offset: 0 }, token),
          adminListContacts({ handled: false, limit: 1, offset: 0 }, token),
        ]);

      if (invResult.status === "fulfilled") {
        setInvites(invResult.value);
        setInviteError(null);
      } else {
        setInviteError(toDisplayMessage(invResult.reason, "招待コードの取得に失敗しました"));
      }

      if (opsResult.status === "fulfilled") {
        setOperatorsData(opsResult.value);
        setOperatorListError(null);
      } else {
        setOperatorListError(toDisplayMessage(opsResult.reason, "業者アカウントの取得に失敗しました"));
      }

      if (densityResult.status === "fulfilled") {
        setCellDensity(densityResult.value);
        setCellDensityError(null);
      } else {
        setCellDensityError(toDisplayMessage(densityResult.reason, "セル密度の取得に失敗しました"));
      }

      if (appsResult.status === "fulfilled") {
        setPendingApplications(appsResult.value.total);
        setPendingApplicationsError(null);
      } else {
        setPendingApplicationsError(
          toDisplayMessage(appsResult.reason, "事前申込件数の取得に失敗しました"),
        );
      }

      if (identityResult.status === "fulfilled") {
        // r10-review H1 是正: 旧応答形式（配列）等で counts が無い場合に備え optional chaining。
        setPendingIdentityDocs(identityResult.value?.counts?.pending ?? null);
        setPendingIdentityDocsError(null);
      } else {
        setPendingIdentityDocsError(
          toDisplayMessage(identityResult.reason, "本人確認の審査待ち件数の取得に失敗しました"),
        );
      }

      if (contactsResult.status === "fulfilled") {
        setUnhandledContacts(contactsResult.value.total);
        setUnhandledContactsError(null);
      } else {
        setUnhandledContactsError(
          toDisplayMessage(contactsResult.reason, "未対応のお問い合わせ件数の取得に失敗しました"),
        );
      }
    } finally {
      setInitialLoadDone(true);
    }
  }, [token, inviteOffset, operatorOffset, statusFilter, operatorSearchQuery, includeDeletedOperators]);

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

  function openSuspendModal(op: OperatorOut) {
    setSuspendModalError(null);
    setSuspendTarget(op);
  }

  function closeSuspendModal() {
    setSuspendModalError(null);
    setSuspendTarget(null);
  }

  function openVerifyModal(op: OperatorOut) {
    setVerifyModalError(null);
    setVerifyTarget(op);
  }

  function closeVerifyModal() {
    setVerifyModalError(null);
    setVerifyTarget(null);
  }

  // 停止／停止解除。停止中は業者の既存トークンが全て 403 になりログインも拒否される。
  // r4回帰是正: window.confirm ではなく ConfirmModal（自前ダイアログ）で確認する（依頼者一覧と同型）。
  async function confirmSuspendChange(op: OperatorOut) {
    if (!token || busy) return;
    const next = !op.is_suspended;
    setBusy(true);
    setSuspendModalError(null);
    try {
      await adminSuspendOperator(op.id, next, token);
      closeSuspendModal();
      await reload();
    } catch (e) {
      // r5-fix-frontend M-2 是正: 失敗時はモーダルを閉じず、ConfirmModal の error prop に
      // 表示する（モーダルを閉じた後の画面上部 Notice は見落とされやすいため）。
      setSuspendModalError(toDisplayMessage(e, "更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  // 承認（active化）・承認取消のいずれも ConfirmModal で確認する
  // （r4監査 M2: 承認取消だけ確認なしで即時実行されていた点も是正）。
  async function confirmVerifyChange(op: OperatorOut) {
    if (!token || busy) return;
    setBusy(true);
    setVerifyModalError(null);
    try {
      await adminVerifyOperator(op.id, op.vendor_status !== "active", token);
      closeVerifyModal();
      await reload();
    } catch (e) {
      // r5-fix-frontend M-2 是正: 失敗時はモーダルを閉じず、ConfirmModal の error prop に
      // 表示する（409「既存業者あり」等の detail もそのまま見える）。
      setVerifyModalError(toDisplayMessage(e, "更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  function changeOperatorStatus(next: string) {
    setOperatorOffset(0);
    setStatusFilter(next);
  }

  function runOperatorSearch() {
    setOperatorOffset(0);
    setOperatorSearchQuery(operatorSearchInput.trim());
  }

  function toggleIncludeDeletedOperators() {
    setOperatorOffset(0);
    setIncludeDeletedOperators((prev) => !prev);
  }

  function copyCode(code: string) {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(code);
      setTimeout(() => setCopied(null), 1500);
    });
  }

  // r5-fix-frontend H-1: status/q/limit/offset を backend 側で絞り込み・集計するため、
  // クライアント側の再フィルタ・再ソートは行わない（pending優先の並びも backend が保証する）。
  const operators = operatorsData?.items ?? null;

  // 各ボタンの件数は backend が返す counts（検索語・絞り込みに関わらず常に全体の内訳）を表示する
  // （r5-ops.md H-1: 審査待ちバッジが「表示中ページのみ」で0件と誤表示される事故の再発防止。
  //   検索語で絞り込んだ結果件数は一覧下部の「全N件中」に出る）。
  const c = operatorsData?.counts;
  const operatorStatusOptions: { value: string; label: string; count?: number }[] = [
    { value: "all", label: "すべて", count: c?.all },
    { value: "active", label: "active", count: c?.active },
    { value: "limited", label: "limited", count: c?.limited },
    { value: "pending", label: "pending", count: c?.pending },
    { value: "rejected", label: "rejected", count: c?.rejected },
    { value: "suspended", label: "停止中", count: c?.suspended },
  ];

  if (loading || !initialLoadDone) {
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
        title="管理画面"
        description="業者招待コードの発行・アカウント承認・セル密度を管理します。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/admin/operator-applications" className={btnSecondary}>
              事前申込の審査へ
              {pendingApplications !== null && pendingApplications > 0 ? (
                <span className="ml-1.5 rounded-none bg-red-600 px-1.5 py-0.5 text-xs font-semibold text-white">
                  {pendingApplications}
                </span>
              ) : null}
              {pendingApplicationsError ? (
                <span className="ml-1.5 text-xs font-normal text-red-600">件数取得失敗</span>
              ) : null}
            </Link>
            <Link href="/admin/cases" className={btnSecondary}>
              案件一覧へ
            </Link>
            <Link href="/admin/transactions" className={btnSecondary}>
              取引一覧へ
            </Link>
            <Link href="/admin/users" className={btnSecondary}>
              依頼者一覧へ
            </Link>
            {/* r10 O-M1 是正: 審査待ちの本人確認書類が /admin トップから見えず、
                個別画面を開くまで滞留に気付けなかった。事前申込バッジと同型で出す。 */}
            <Link href="/admin/identity-documents" className={btnSecondary}>
              本人確認書類の審査へ
              {pendingIdentityDocs !== null && pendingIdentityDocs > 0 ? (
                <span className="ml-1.5 rounded-none bg-red-600 px-1.5 py-0.5 text-xs font-semibold text-white">
                  {pendingIdentityDocs}
                </span>
              ) : null}
              {pendingIdentityDocsError ? (
                <span className="ml-1.5 text-xs font-normal text-red-600">件数取得失敗</span>
              ) : null}
            </Link>
            {/* r10 O-M6 是正: お問い合わせの受信箱への導線と未対応件数。 */}
            <Link href="/admin/contacts" className={btnSecondary}>
              お問い合わせへ
              {unhandledContacts !== null && unhandledContacts > 0 ? (
                <span className="ml-1.5 rounded-none bg-red-600 px-1.5 py-0.5 text-xs font-semibold text-white">
                  {unhandledContacts}
                </span>
              ) : null}
              {unhandledContactsError ? (
                <span className="ml-1.5 text-xs font-normal text-red-600">件数取得失敗</span>
              ) : null}
            </Link>
          </div>
        }
      >
      {error ? (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* 招待コード（単発） */}
        <Card>
          <h2 className="font-normal text-slate-900">業者招待コード（単発）</h2>
          {inviteError ? (
            <div className="mt-2">
              <Notice tone="error">{inviteError}</Notice>
            </div>
          ) : null}
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
                  <p className="text-xs text-slate-600">
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
          {invites ? (
            <AdminPagination
              total={null}
              limit={ADMIN_LIST_DEFAULT_LIMIT}
              offset={inviteOffset}
              itemCount={invites.length}
              onPrev={() => setInviteOffset(Math.max(0, inviteOffset - ADMIN_LIST_DEFAULT_LIMIT))}
              onNext={() => setInviteOffset(inviteOffset + ADMIN_LIST_DEFAULT_LIMIT)}
            />
          ) : null}
        </Card>

        {/* バルク発行 */}
        <Card>
          <h2 className="font-normal text-slate-900">バルク発行</h2>
          <div className="mt-3 space-y-2">
            <div className="flex gap-2">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-slate-500" htmlFor="admin-bulk-count">発行件数（1〜500）</label>
                <input
                  id="admin-bulk-count"
                  type="number"
                  min={1}
                  max={500}
                  value={bulkCount}
                  onChange={(e) => setBulkCount(Number(e.target.value))}
                  className={`${inputBase} w-28`}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <label className="text-xs text-slate-500" htmlFor="admin-bulk-lot-name">ロット名（任意・管理用）</label>
                <input
                  id="admin-bulk-lot-name"
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
            {operatorListError ? (
              <div className="w-full">
                <Notice tone="error">{operatorListError}</Notice>
              </div>
            ) : null}
            <StatusFilterBar options={operatorStatusOptions} value={statusFilter} onChange={changeOperatorStatus} />
          </div>
          {/* r10 O-M4 是正: pending には「申し込んだが許可証未提出で運営が着手できない」業者が
              混ざるため、pending だけでは実際に審査できる件数が読めなかった。内訳を併記する。 */}
          {c ? (
            <p className="mt-2 text-xs text-slate-500">
              pending {c.pending}件（うち許可証提出済み {c.pending_with_license}件＝いま審査に着手できる件数）
            </p>
          ) : null}
          <div className="mt-3 flex gap-2">
            <input
              type="text"
              value={operatorSearchInput}
              onChange={(e) => setOperatorSearchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") runOperatorSearch();
              }}
              className={inputBase}
              placeholder="会社名・メール・許可番号で検索（部分一致）"
            />
            <button type="button" onClick={runOperatorSearch} className={`${btnPrimary} shrink-0`}>
              検索
            </button>
          </div>
          <label className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={includeDeletedOperators}
              onChange={toggleIncludeDeletedOperators}
            />
            退会済みを含める
          </label>
          <ul className="mt-4 divide-y divide-slate-100">
            {operators?.map((op) => {
              const statusInfo = VENDOR_STATUS_LABEL[op.vendor_status] ?? {
                label: op.vendor_status,
                badgeValue: "pending",
              };
              // r8-fix-frontend4: 退会（匿名化）済み業者は backend 側が verify/suspend を 409 で
              // 拒否するため、操作ボタン自体を出さずバッジで理由を示す（include_deleted=true 時のみ表示対象）。
              const isDeleted = Boolean(op.deleted_at);
              return (
                <li key={op.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{op.company_name}</p>
                    <p className="text-xs text-slate-600">
                      {op.contact_email}
                      {op.license_number ? ` ・ ${op.license_number}` : ""}
                    </p>
                    <div className="mt-1 flex gap-1.5">
                      {isDeleted ? <StatusBadge value="cancelled" label="退会済み" /> : null}
                      <StatusBadge
                        value={statusInfo.badgeValue as "completed" | "pending" | "rejected"}
                        label={statusInfo.label}
                      />
                      {op.is_suspended ? <StatusBadge value="cancelled" label="停止中" /> : null}
                      <StatusBadge
                        value={op.has_license_image ? "completed" : "pending"}
                        label={op.has_license_image ? "許可証: 提出済み" : "許可証: 未提出"}
                      />
                      {/* r8-fix-frontend2 M1 是正: 業者都合キャンセルの累計を運営が確認できる
                          唯一の材料。0件時は目立たせず、1件以上のみ警告色で出す。 */}
                      {op.cancel_count > 0 ? (
                        <StatusBadge value="rejected" label={`キャンセル ${op.cancel_count}件`} />
                      ) : null}
                    </div>
                  </div>
                  {isDeleted ? (
                    <p className="text-xs text-slate-600">退会済みのため操作できません</p>
                  ) : (
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
                          onClick={() => openVerifyModal(op)}
                          disabled={
                            busy || op.is_suspended || (op.vendor_status !== "active" && !op.has_license_image)
                          }
                          className={op.vendor_status === "active" ? btnSecondary : btnPrimary}
                        >
                          {op.vendor_status === "active" ? "承認を取消" : "承認する"}
                        </button>
                        {op.is_suspended ? (
                          <p className="text-xs text-red-600">停止中です。承認状態の変更は停止解除後に行ってください</p>
                        ) : op.vendor_status !== "active" && !op.has_license_image ? (
                          <p className="text-xs text-red-600">
                            許可証画像が未提出のため承認できません
                          </p>
                        ) : null}
                      </div>
                      <button
                        type="button"
                        onClick={() => openSuspendModal(op)}
                        disabled={busy}
                        className={op.is_suspended ? btnPrimary : btnDanger}
                      >
                        {op.is_suspended ? "停止を解除" : "停止する"}
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
            {operators && operators.length === 0 ? (
              <li className="py-3 text-sm text-slate-500">該当業者はいません。</li>
            ) : null}
          </ul>
          {operators ? (
            <AdminPagination
              total={operatorsData?.total ?? null}
              limit={ADMIN_LIST_DEFAULT_LIMIT}
              offset={operatorOffset}
              itemCount={operators.length}
              onPrev={() => setOperatorOffset(Math.max(0, operatorOffset - ADMIN_LIST_DEFAULT_LIMIT))}
              onNext={() => setOperatorOffset(operatorOffset + ADMIN_LIST_DEFAULT_LIMIT)}
            />
          ) : null}
        </Card>
      </div>

      {/* セル密度監視 */}
      <div className="mt-6">
        <Card>
          <h2 className="font-normal text-slate-900">セル密度監視（需給バランス）</h2>
          <p className="mt-1 text-xs text-slate-500">
            都道府県×目的別の直近30日案件数 / アクティブ業者数。1.5超は赤表示（需要過多）。
          </p>
          {cellDensityError ? (
            <div className="mt-3">
              <Notice tone="error">{cellDensityError}</Notice>
            </div>
          ) : null}
          {cellDensity && cellDensity.length > 0 ? (
            <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="セル密度一覧">
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
                      <td className="py-2 pr-4 text-slate-600">{formatPurposeLabel(row.purpose)}</td>
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
          ) : cellDensityError ? null : (
            <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
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

      {suspendTarget ? (
        <ConfirmModal
          title={
            suspendTarget.is_suspended
              ? `${suspendTarget.company_name}の停止を解除します`
              : `${suspendTarget.company_name}を停止します`
          }
          message={
            suspendTarget.is_suspended
              ? "停止を解除すると、業者は再びログイン・入札ができるようになります。よろしいですか？"
              : "停止すると、業者の既存トークンは失効しログイン・全操作ができなくなります。よろしいですか？"
          }
          confirmLabel={suspendTarget.is_suspended ? "停止を解除する" : "停止する"}
          danger={!suspendTarget.is_suspended}
          error={suspendModalError}
          busy={busy}
          onCancel={closeSuspendModal}
          onConfirm={() => void confirmSuspendChange(suspendTarget)}
        />
      ) : null}

      {verifyTarget ? (
        <ConfirmModal
          title={
            verifyTarget.vendor_status === "active"
              ? `${verifyTarget.company_name}の承認を取り消します`
              : `${verifyTarget.company_name}を承認します`
          }
          message={
            verifyTarget.vendor_status === "active"
              ? "承認を取り消すと、業者は案件の閲覧・入札ができなくなります。よろしいですか？"
              : "承認すると、業者は案件の閲覧・入札ができるようになります。よろしいですか？"
          }
          confirmLabel={verifyTarget.vendor_status === "active" ? "承認を取り消す" : "承認する"}
          danger={verifyTarget.vendor_status === "active"}
          error={verifyModalError}
          busy={busy}
          onCancel={closeVerifyModal}
          onConfirm={() => void confirmVerifyChange(verifyTarget)}
        />
      ) : null}
    </div>
  );
}
