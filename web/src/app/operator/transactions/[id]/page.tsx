"use client";

/**
 * 業者: 落札管理。
 * - 住所詳細・連絡先の確認（落札後にのみバックエンドが開示）
 * - 減額申請（理由必須）/ キャンセル / 完了後レビュー
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Spinner } from "@/components/Icon";
import {
  Card,
  Notice,
  StatusBadge,
  btnDanger,
  btnPrimary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import {
  TXN_STATUS_LABEL,
  KdzApiError,
  cancelTransaction,
  createReduction,
  createReview,
  formatYen,
  getTransaction,
  photoSrc,
  type TransactionDetail,
} from "@/lib/katadzuke-api";

const REDUCTION_STATUS_LABEL = {
  pending: "回答待ち",
  approved: "承認",
  rejected: "却下",
} as const;

export default function OperatorTransactionPage() {
  const params = useParams<{ id: string }>();
  const txnId = params.id;
  const { token, loading } = useToken();

  const [txn, setTxn] = useState<TransactionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [requestedAmount, setRequestedAmount] = useState("");
  const [reason, setReason] = useState("");
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setTxn(await getTransaction(txnId, token));
    } catch (e) {
      setError(e instanceof KdzApiError ? e.message : "取得に失敗しました");
    }
  }, [txnId, token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function act(fn: () => Promise<unknown>, confirmMsg?: string) {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(e instanceof KdzApiError ? e.message : "操作に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!txn && !error)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  if (!txn) {
    return (
      <div className="container-aw max-w-3xl py-10">
        <Notice tone="error">{error ?? "成約情報が見つかりません。"}</Notice>
      </div>
    );
  }

  const currentAmount = txn.final_amount ?? txn.initial_amount;
  const pendingReduction = txn.reduction_requests.find((r) => r.status === "pending");
  const myReview = txn.reviews.find((r) => r.reviewer_type === "operator");
  const active = txn.status === "pending" || txn.status === "visiting";

  return (
    <div className="container-aw max-w-3xl space-y-6 py-10">
      {error ? <Notice tone="error">{error}</Notice> : null}

      {/* ===== 概要 + 住所開示 ===== */}
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              {txn.case?.purpose ?? "片付け案件"}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              落札額 {formatYen(txn.initial_amount)}
              {txn.final_amount != null && txn.final_amount !== txn.initial_amount
                ? ` → 確定額 ${formatYen(txn.final_amount)}`
                : ""}
            </p>
          </div>
          <StatusBadge value={txn.status} label={TXN_STATUS_LABEL[txn.status]} />
        </div>

        {txn.address ? (
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">
              訪問先住所（落札により開示）
            </p>
            <p className="mt-1.5 font-bold text-slate-900">
              {txn.address.prefecture} {txn.address.city} {txn.address.address_detail ?? ""}
            </p>
            {txn.contact_email ? (
              <p className="mt-1 text-sm text-slate-600">お客様連絡先: {txn.contact_email}</p>
            ) : null}
          </div>
        ) : (
          <Notice tone="warn">住所詳細は表示できません（キャンセル済みの可能性）。</Notice>
        )}

        {txn.case?.photos?.length ? (
          <ul className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-5">
            {txn.case.photos.map((p) => (
              <li key={p.id}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={photoSrc(p.url)}
                  alt=""
                  className="aspect-square w-full rounded-xl border border-slate-200 object-cover"
                />
              </li>
            ))}
          </ul>
        ) : null}

        {txn.case?.ai_summary ? (
          <div className="mt-4 rounded-xl bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">AI 要約</p>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-700">{txn.case.ai_summary}</p>
          </div>
        ) : null}
      </Card>

      {/* ===== 減額申請 ===== */}
      <Card>
        <h2 className="font-bold text-slate-900">減額申請</h2>
        {txn.reduction_requests.length > 0 && (
          <ul className="mt-3 space-y-2">
            {txn.reduction_requests.map((r) => (
              <li key={r.id} className="rounded-xl border border-slate-200 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-900">
                    {formatYen(r.original_amount)} → {formatYen(r.requested_amount)}
                  </span>
                  <StatusBadge value={r.status} label={REDUCTION_STATUS_LABEL[r.status]} />
                </div>
                <p className="mt-1.5 leading-relaxed text-slate-600">{r.reason}</p>
              </li>
            ))}
          </ul>
        )}

        {active && !pendingReduction ? (
          <form
            className="mt-4 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              const value = Number(requestedAmount);
              if (!Number.isFinite(value) || value <= 0 || value >= currentAmount) {
                setError(`減額後の金額は 1〜${currentAmount - 1} 円で入力してください。`);
                return;
              }
              if (reason.trim().length < 10) {
                setError("減額理由は10文字以上で具体的に記入してください（必須）。");
                return;
              }
              void act(
                () =>
                  createReduction(
                    txn.id,
                    { requested_amount: value, reason: reason.trim() },
                    token!,
                  ),
                "減額申請を送信しますか？お客様の承認後に金額が確定します。",
              );
            }}
          >
            <p className="text-sm text-slate-500">
              現地確認の結果、物量・状態が想定と異なる場合のみ申請してください。
              現在の金額: <strong>{formatYen(currentAmount)}</strong>
            </p>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">
                減額後の提示額（円） <span className="text-red-500">*</span>
              </span>
              <input
                type="number"
                required
                min={1}
                max={currentAmount - 1}
                value={requestedAmount}
                onChange={(e) => setRequestedAmount(e.target.value)}
                className={inputBase}
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">
                理由（必須・10文字以上・お客様に表示されます）
              </span>
              <textarea
                required
                minLength={10}
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className={inputBase}
                placeholder="現地確認の結果、想定より家電の破損が多く再販価値が下がるため"
              />
            </label>
            <button type="submit" disabled={busy} className={btnPrimary}>
              減額を申請する
            </button>
          </form>
        ) : null}
        {pendingReduction ? (
          <Notice tone="info">お客様の回答待ちの申請があります。</Notice>
        ) : null}
        {!active ? (
          <p className="mt-2 text-sm text-slate-400">この成約では申請できません。</p>
        ) : null}
      </Card>

      {/* ===== キャンセル ===== */}
      {active && (
        <Card>
          <h2 className="font-bold text-slate-900">キャンセル</h2>
          <p className="mt-1 text-sm text-slate-500">
            業者都合のキャンセルは記録され、アカウント評価に影響します。
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              const r = window.prompt("キャンセル理由を入力してください") ?? "";
              if (!r.trim()) return;
              void act(
                () => cancelTransaction(txn.id, r.trim(), token!),
                "本当にキャンセルしますか？",
              );
            }}
            className={`${btnDanger} mt-3`}
          >
            この成約をキャンセルする
          </button>
        </Card>
      )}

      {/* ===== レビュー ===== */}
      {txn.status === "completed" && (
        <Card>
          <h2 className="font-bold text-slate-900">お客様を評価する</h2>
          {myReview ? (
            <Notice tone="success">レビュー投稿済み（★{myReview.rating}）</Notice>
          ) : (
            <div className="mt-3">
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setRating(n)}
                    aria-label={`星${n}`}
                    className={`text-2xl ${n <= rating ? "text-amber-400" : "text-slate-300"}`}
                  >
                    ★
                  </button>
                ))}
              </div>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                className={`${inputBase} mt-3`}
                rows={3}
                placeholder="取引の感想（任意）"
              />
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  act(() =>
                    createReview(
                      { transaction_id: txn.id, rating, comment: comment.trim() || undefined },
                      token!,
                    ),
                  )
                }
                className={`${btnPrimary} mt-3`}
              >
                レビューを投稿
              </button>
            </div>
          )}
        </Card>
      )}

      <a
        href="/operator/transactions"
        className="inline-block text-sm font-semibold text-brand-700 hover:underline"
      >
        ← 落札管理一覧へ
      </a>
    </div>
  );
}
