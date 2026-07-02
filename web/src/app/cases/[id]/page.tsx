"use client";

/**
 * ユーザー: 案件詳細。
 * - 入札一覧の確認と 1 社選択（落札確定）
 * - 成約後: 減額申請への承認/却下、完了確定、キャンセル、レビュー投稿
 */

import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Spinner } from "@/components/Icon";
import {
  Card,
  Notice,
  StatusBadge,
  btnDanger,
  btnPrimary,
  btnSecondary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import {
  CASE_STATUS_LABEL,
  TXN_STATUS_LABEL,
  cancelTransaction,
  completeTransaction,
  createReview,
  decideReduction,
  formatYen,
  getCase,
  getTransaction,
  listBids,
  photoSrc,
  selectBid,
  toDisplayMessage,
  type BidOut,
  type CaseOut,
  type TransactionDetail,
} from "@/lib/katadzuke-api";

export default function UserCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const caseId = params.id;
  const { token, loading } = useToken();

  const [caseData, setCaseData] = useState<CaseOut | null>(null);
  const [bids, setBids] = useState<BidOut[]>([]);
  const [txn, setTxn] = useState<TransactionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      const c = await getCase(caseId, token);
      setCaseData(c);
      const b = await listBids(caseId, token);
      setBids(b);
      const selected = b.find((x) => x.status === "selected");
      if (selected?.transaction_id) {
        setTxn(await getTransaction(selected.transaction_id, token));
      }
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [caseId, token]);

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
      setError(toDisplayMessage(e, "操作に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!caseData && !error)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="container-aw max-w-3xl py-10">
        <Notice tone="error">{error ?? "案件が見つかりません。"}</Notice>
      </div>
    );
  }

  const pendingReduction = txn?.reduction_requests.find((r) => r.status === "pending");
  const myReview = txn?.reviews.find((r) => r.reviewer_type === "user");

  return (
    <div className="container-aw max-w-3xl space-y-6 py-10">
      {search.get("created") ? (
        <Notice tone="success">
          依頼を受け付けました。業者から入札が届くとメールでお知らせします。
        </Notice>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}

      {/* ===== 案件情報 ===== */}
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">{caseData.purpose}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {caseData.prefecture} {caseData.city}
              {caseData.address_detail ? ` ${caseData.address_detail}` : ""}
            </p>
            <p className="mt-0.5 text-xs text-slate-400">
              {caseData.housing_type ?? "—"} / {caseData.floor_plan ?? "—"} /{" "}
              {caseData.floor_number != null ? `${caseData.floor_number}階` : "—"} / EV
              {caseData.has_elevator == null ? "—" : caseData.has_elevator ? "あり" : "なし"}
            </p>
          </div>
          <StatusBadge value={caseData.status} label={CASE_STATUS_LABEL[caseData.status]} />
        </div>

        {caseData.photos.length > 0 && (
          <ul className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-5">
            {caseData.photos.map((p) => (
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
        )}

        {caseData.ai_summary ? (
          <div className="mt-4 rounded-xl bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              AI 要約（業者に提示されます）
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-700">
              {caseData.ai_summary}
            </p>
          </div>
        ) : null}
      </Card>

      {/* ===== 入札一覧 ===== */}
      {!txn && caseData.status !== "cancelled" && (
        <Card>
          <h2 className="font-bold text-slate-900">入札一覧（{bids.length} 件）</h2>
          {bids.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">
              まだ入札がありません。入札が届くとメールでお知らせします。
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {bids.map((b) => (
                <li
                  key={b.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"
                >
                  <div>
                    <p className="font-bold text-slate-900">
                      {b.operator?.company_name ?? "業者"}
                      {b.operator?.rating != null ? (
                        <span className="ml-2 text-xs font-semibold text-amber-600">
                          ★ {b.operator.rating.toFixed(1)}
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-0.5 text-lg font-bold text-brand-700">
                      {formatYen(b.amount)}
                    </p>
                    {b.message ? (
                      <p className="mt-1 max-w-md text-sm leading-relaxed text-slate-600">
                        {b.message}
                      </p>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      act(
                        () => selectBid(caseId, b.id, token!),
                        `${b.operator?.company_name ?? "この業者"}（${formatYen(b.amount)}）に決定しますか？\n決定後、業者へ住所詳細が開示されます。`,
                      )
                    }
                    className={btnPrimary}
                  >
                    この業者に決める
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {/* ===== 成約パネル ===== */}
      {txn && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-bold text-slate-900">
                成約: {txn.operator?.company_name ?? "業者"}
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                落札額 {formatYen(txn.initial_amount)}
                {txn.final_amount != null && txn.final_amount !== txn.initial_amount
                  ? ` → 確定額 ${formatYen(txn.final_amount)}`
                  : ""}
              </p>
              {txn.contact_email ? (
                <p className="mt-0.5 text-xs text-slate-400">
                  業者連絡先: {txn.contact_email}
                </p>
              ) : null}
            </div>
            <StatusBadge value={txn.status} label={TXN_STATUS_LABEL[txn.status]} />
          </div>

          {/* 減額申請（承認待ち） */}
          {pendingReduction && (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-bold text-amber-900">業者から減額申請が届いています</p>
              <p className="mt-1 text-sm text-amber-800">
                {formatYen(pendingReduction.original_amount)} →{" "}
                <strong>{formatYen(pendingReduction.requested_amount)}</strong>
              </p>
              <p className="mt-2 rounded-lg bg-white/70 p-3 text-sm leading-relaxed text-slate-700">
                理由: {pendingReduction.reason}
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    act(
                      () => decideReduction(txn.id, pendingReduction.id, "approve", token!),
                      "減額を承認しますか？確定額が更新されます。",
                    )
                  }
                  className={btnPrimary}
                >
                  承認する
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    act(() => decideReduction(txn.id, pendingReduction.id, "reject", token!))
                  }
                  className={btnSecondary}
                >
                  却下する
                </button>
              </div>
            </div>
          )}

          {/* 完了・キャンセル */}
          {(txn.status === "pending" || txn.status === "visiting") && (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy || Boolean(pendingReduction)}
                onClick={() =>
                  act(
                    () => completeTransaction(txn.id, token!),
                    "作業の完了を確定しますか？確定後はレビューを投稿できます。",
                  )
                }
                className={btnPrimary}
              >
                作業完了を確定する
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const reason = window.prompt("キャンセル理由（任意）") ?? null;
                  void act(
                    () => cancelTransaction(txn.id, reason, token!),
                    "本当にキャンセルしますか？",
                  );
                }}
                className={btnDanger}
              >
                キャンセル
              </button>
            </div>
          )}
          {pendingReduction ? (
            <p className="mt-2 text-xs text-slate-400">
              ※ 減額申請への回答後に完了確定できます。
            </p>
          ) : null}

          {/* レビュー */}
          {txn.status === "completed" &&
            (myReview ? (
              <Notice tone="success">
                レビュー投稿済み（★{myReview.rating}）ありがとうございました。
              </Notice>
            ) : (
              <div className="mt-4 rounded-xl border border-slate-200 p-4">
                <p className="font-bold text-slate-900">業者を評価する</p>
                <div className="mt-2 flex gap-1">
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
                  placeholder="対応の感想（任意）"
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    act(() =>
                      createReview(
                        {
                          transaction_id: txn.id,
                          rating,
                          comment: comment.trim() || undefined,
                        },
                        token!,
                      ),
                    )
                  }
                  className={`${btnPrimary} mt-3`}
                >
                  レビューを投稿
                </button>
              </div>
            ))}
        </Card>
      )}

      <a href="/cases" className="inline-block text-sm font-semibold text-brand-700 hover:underline">
        ← マイ案件一覧へ
      </a>
    </div>
  );
}
