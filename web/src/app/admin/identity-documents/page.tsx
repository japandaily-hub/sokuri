"use client";

/**
 * 管理画面: 本人確認書類の審査（role=admin のみ）。
 * 一覧 → 行選択で表面/裏面画像を確認 → 承認 or 却下（理由必須）。
 * 既存 /admin（招待コード・業者承認）と同じ Tailwind/Card/StatusBadge 構成を踏襲する。
 */

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
import { AdminPagination } from "../_components/AdminPagination";
import { ConfirmModal } from "../_components/ConfirmModal";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  listIdentityDocumentsAdmin,
  fetchIdentityDocumentBlobAdmin,
  approveIdentityDocument,
  rejectIdentityDocument,
  toDisplayMessage,
  KdzApiError,
  IDENTITY_STATUS_LABEL,
  IDENTITY_DOC_TYPES,
  type AdminIdentityDocument,
} from "@/lib/katadzuke-api";

/** 画像取得が 404/410 の場合、退会等で画像が削除済みであることを示す固定文言。 */
const IMAGE_GONE_MESSAGE = "画像は削除されています（退会済み）";

function docTypeLabel(id: string): string {
  return IDENTITY_DOC_TYPES.find((d) => d.id === id)?.label ?? id;
}

export default function AdminIdentityDocumentsPage() {
  const { token, loading } = useToken();
  const [statusFilter, setStatusFilter] = useState<"pending" | "all">("pending");
  const [docs, setDocs] = useState<AdminIdentityDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [selected, setSelected] = useState<AdminIdentityDocument | null>(null);
  const [frontUrl, setFrontUrl] = useState<string | null>(null);
  const [backUrl, setBackUrl] = useState<string | null>(null);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [imagesError, setImagesError] = useState<string | null>(null);
  /** 画像取得が 404/410 の場合 true。承認/却下ボタンを無効化する（退会済み等で実体が無い）。 */
  const [imagesGone, setImagesGone] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [offset, setOffset] = useState(0);
  const [showApproveConfirm, setShowApproveConfirm] = useState(false);

  // レース条件対策（openDetailの完了前に別行を選択した場合、古い結果を捨てる）
  const selectedIdRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (frontUrl) URL.revokeObjectURL(frontUrl);
      if (backUrl) URL.revokeObjectURL(backUrl);
    };
  }, [frontUrl, backUrl]);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setDocs(
        await listIdentityDocumentsAdmin(
          statusFilter,
          { limit: ADMIN_LIST_DEFAULT_LIMIT, offset },
          token,
        ),
      );
      setError(null);
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [token, statusFilter, offset]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function changeStatusFilter(next: "pending" | "all") {
    setOffset(0);
    setStatusFilter(next);
  }

  async function openDetail(doc: AdminIdentityDocument) {
    selectedIdRef.current = doc.id;
    setSelected(doc);
    setFrontUrl(null);
    setBackUrl(null);
    setImagesError(null);
    setImagesGone(false);
    setRejectReason("");
    setShowRejectForm(false);
    if (!token) return;
    setImagesLoading(true);
    try {
      const front = await fetchIdentityDocumentBlobAdmin(doc.id, "front", token);
      if (selectedIdRef.current !== doc.id) return;
      setFrontUrl(URL.createObjectURL(front));
      if (doc.has_back) {
        const back = await fetchIdentityDocumentBlobAdmin(doc.id, "back", token);
        if (selectedIdRef.current !== doc.id) return;
        setBackUrl(URL.createObjectURL(back));
      }
    } catch (e) {
      if (selectedIdRef.current !== doc.id) return;
      if (e instanceof KdzApiError && (e.status === 404 || e.status === 410)) {
        setImagesGone(true);
        setImagesError(IMAGE_GONE_MESSAGE);
      } else {
        setImagesError(toDisplayMessage(e, "画像の取得に失敗しました"));
      }
    } finally {
      if (selectedIdRef.current === doc.id) setImagesLoading(false);
    }
  }

  function closeDetail() {
    selectedIdRef.current = null;
    setSelected(null);
    setFrontUrl(null);
    setBackUrl(null);
    setImagesGone(false);
    setShowApproveConfirm(false);
  }

  async function onApprove() {
    if (!selected || !token || busy) return;
    setBusy(true);
    setError(null);
    try {
      await approveIdentityDocument(selected.id, token);
      setShowApproveConfirm(false);
      closeDetail();
      await reload();
    } catch (e) {
      // r4-fix-frontend2 M2 波及是正: 失敗時も対象（確認モーダル）をクリアして閉じ、
      // 隠れずに見える Notice でエラーを出す（admin/page.tsx 等と同型）。
      setShowApproveConfirm(false);
      setError(toDisplayMessage(e, "承認に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  async function onReject() {
    if (!selected || !token || busy) return;
    if (!rejectReason.trim()) {
      setError("却下理由を入力してください");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await rejectIdentityDocument(selected.id, rejectReason.trim(), token);
      closeDetail();
      await reload();
    } catch (e) {
      setError(toDisplayMessage(e, "却下に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!docs && !error)) {
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
        title="本人確認書類の審査"
        description="依頼者から提出された本人確認書類を確認し、承認・却下します。"
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-normal text-slate-900">提出一覧</h2>
            <div className="flex gap-2">
              {(["pending", "all"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => changeStatusFilter(s)}
                  className={`rounded-none px-3 py-1.5 text-xs font-medium transition-colors ${
                    statusFilter === s
                      ? "bg-brand-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {s === "pending" ? "審査待ち" : "すべて"}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-2 pr-4">メール</th>
                  <th className="pb-2 pr-4">氏名</th>
                  <th className="pb-2 pr-4">書類種別</th>
                  <th className="pb-2 pr-4">提出日時</th>
                  <th className="pb-2 pr-4">状態</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {docs?.map((d) => (
                  <tr key={d.id}>
                    <td className="py-2 pr-4 text-slate-700">{d.user_email}</td>
                    <td className="py-2 pr-4 text-slate-700">{d.user_name ?? "—"}</td>
                    <td className="py-2 pr-4 text-slate-700">{docTypeLabel(d.doc_type)}</td>
                    <td className="py-2 pr-4 text-slate-500">
                      {new Date(d.submitted_at).toLocaleString("ja-JP")}
                    </td>
                    <td className="py-2 pr-4">
                      <StatusBadge
                        value={d.status === "approved" ? "approved" : d.status}
                        label={IDENTITY_STATUS_LABEL[d.status]}
                      />
                    </td>
                    <td className="py-2 text-right">
                      <button type="button" onClick={() => void openDetail(d)} className={btnSecondary}>
                        確認する
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {docs && docs.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">該当する提出はありません。</p>
            ) : null}
          </div>
          {docs ? (
            <AdminPagination
              total={null}
              limit={ADMIN_LIST_DEFAULT_LIMIT}
              offset={offset}
              itemCount={docs.length}
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
          aria-labelledby="identityDocModalTitle"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={closeDetail}
        >
          <div
            className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-none border border-slate-200 bg-white p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-4">
              <h2 id="identityDocModalTitle" className="font-normal text-slate-900">
                {selected.user_name ?? selected.user_email} の本人確認書類
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
            <p className="mt-1 text-xs text-slate-500">
              {docTypeLabel(selected.doc_type)} ・ 提出: {new Date(selected.submitted_at).toLocaleString("ja-JP")}
            </p>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="flex min-h-[160px] items-center justify-center overflow-hidden rounded-none bg-slate-50">
                {imagesLoading ? (
                  <Spinner className="h-6 w-6 text-brand-600" />
                ) : frontUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={frontUrl} alt="表面" className="max-h-[40vh] w-full object-contain" />
                ) : imagesGone ? (
                  <p className="p-4 text-center text-xs text-slate-400">{IMAGE_GONE_MESSAGE}</p>
                ) : (
                  <p className="p-4 text-center text-xs text-slate-400">表面画像なし</p>
                )}
              </div>
              {selected.has_back ? (
                <div className="flex min-h-[160px] items-center justify-center overflow-hidden rounded-none bg-slate-50">
                  {imagesLoading ? (
                    <Spinner className="h-6 w-6 text-brand-600" />
                  ) : backUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={backUrl} alt="裏面" className="max-h-[40vh] w-full object-contain" />
                  ) : imagesGone ? (
                    <p className="p-4 text-center text-xs text-slate-400">{IMAGE_GONE_MESSAGE}</p>
                  ) : (
                    <p className="p-4 text-center text-xs text-slate-400">裏面画像なし</p>
                  )}
                </div>
              ) : null}
            </div>
            {imagesError ? (
              <p className="mt-2 text-xs text-red-600">{imagesError}</p>
            ) : null}

            {showRejectForm ? (
              <div className="mt-4">
                <label className="text-xs text-slate-500" htmlFor="reject-reason">
                  却下理由（本人に表示されます）
                </label>
                <textarea
                  id="reject-reason"
                  className={`${inputBase} mt-1`}
                  rows={3}
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="例: 書類の住所が登録住所と一致していません"
                />
                <div className="mt-2 flex justify-end gap-2">
                  <button type="button" className={btnSecondary} onClick={() => setShowRejectForm(false)}>
                    キャンセル
                  </button>
                  <button type="button" className={btnDanger} disabled={busy || imagesGone} onClick={() => void onReject()}>
                    却下を確定する
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  className={btnDanger}
                  disabled={busy || imagesGone}
                  onClick={() => setShowRejectForm(true)}
                >
                  却下する
                </button>
                <button
                  type="button"
                  className={btnPrimary}
                  disabled={busy || imagesGone}
                  onClick={() => setShowApproveConfirm(true)}
                >
                  承認する
                </button>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {showApproveConfirm && selected ? (
        <ConfirmModal
          title={`${selected.user_name ?? selected.user_email}の本人確認を承認します`}
          message="承認すると、依頼者は本人確認済みの状態になります。よろしいですか？"
          confirmLabel="承認する"
          busy={busy}
          onCancel={() => setShowApproveConfirm(false)}
          onConfirm={() => void onApprove()}
        />
      ) : null}
    </div>
  );
}
