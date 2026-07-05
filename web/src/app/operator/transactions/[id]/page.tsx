"use client";

/**
 * 業者: 落札管理（/operator/transactions/[id]）。
 *
 * デザインレビュー対応:
 *  - B-1: 旧 Tailwind/slate 実装を廃し、katazuke トークン・部品
 *    （listing-card/decided-card/reduction 表示/review-card 等、operator-shared.css に定義）に統一。
 *    OperatorHeader を追加しナビ不能だった問題も解消。
 *  - B-2: 減額申請・キャンセルの確認を window.confirm/prompt からブランドモーダルへ置換
 *    （operator-shared.css の .modal-overlay/.modal-card を使用）。
 * 機能ロジック（createReduction・cancelTransaction・createReview）は保持。
 */

import "../../operator-shared.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { OperatorHeader } from "@/components/kdz/OperatorHeader";
import { useToken } from "@/components/kdz/Ui";
import { DisclosureNotice } from "@/components/kdz/DisclosureNotice";
import {
  TXN_STATUS_LABEL,
  cancelTransaction,
  createReduction,
  createReview,
  formatYen,
  getTransaction,
  photoSrc,
  toDisplayMessage,
  type TransactionDetail,
} from "@/lib/katadzuke-api";

const REDUCTION_STATUS_LABEL = {
  pending: "回答待ち",
  approved: "承認",
  rejected: "却下",
} as const;
const REDUCTION_CHIP_CLASS = { pending: "warn", approved: "bidding", rejected: "done" } as const;

type ModalState = { kind: "reduction"; amount: number; reason: string } | { kind: "cancel" } | null;

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
  const [modal, setModal] = useState<ModalState>(null);
  const [cancelReason, setCancelReason] = useState("");

  // モーダルを開いたトリガー要素を保持し、閉じた際にフォーカスを戻す（アクセシビリティ対応）。
  const modalTriggerRef = useRef<HTMLButtonElement | null>(null);
  // 減額申請フォームの送信ボタン（モーダルを開くトリガー）。
  const reductionSubmitRef = useRef<HTMLButtonElement | null>(null);
  // 各モーダル内で最初にフォーカスすべき操作可能要素。
  const reductionModalFirstFieldRef = useRef<HTMLButtonElement | null>(null);
  const cancelModalFirstFieldRef = useRef<HTMLTextAreaElement | null>(null);

  function closeModal() {
    setModal(null);
    modalTriggerRef.current?.focus();
  }

  // モーダルopen時にモーダル内の最初の操作可能要素へフォーカスを移す。
  useEffect(() => {
    if (modal?.kind === "reduction") {
      reductionModalFirstFieldRef.current?.focus();
    } else if (modal?.kind === "cancel") {
      cancelModalFirstFieldRef.current?.focus();
    }
  }, [modal?.kind]);

  // Escapeキー押下でモーダルを閉じる。
  useEffect(() => {
    if (!modal) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        closeModal();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modal]);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setTxn(await getTransaction(txnId, token));
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [txnId, token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function act(fn: () => Promise<unknown>) {
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

  if (loading || (!txn && !error)) {
    return (
      <div className="case-detail-page">
        <OperatorHeader active="transactions" />
        <div style={{ display: "flex", minHeight: "50vh", alignItems: "center", justifyContent: "center" }}>
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  if (!txn) {
    return (
      <div className="case-detail-page">
        <OperatorHeader active="transactions" />
        <div className="op-wrap narrow">
          <div className="op-alert error">{error ?? "成約情報が見つかりません。"}</div>
        </div>
      </div>
    );
  }

  const currentAmount = txn.final_amount ?? txn.initial_amount;
  const pendingReduction = txn.reduction_requests.find((r) => r.status === "pending");
  const myReview = txn.reviews.find((r) => r.reviewer_type === "operator");
  const active = txn.status === "pending" || txn.status === "visiting";
  const disclosed = Boolean(txn.address) && !txn.awaiting_approval;

  function openReductionModal(e: React.FormEvent) {
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
    setError(null);
    modalTriggerRef.current = reductionSubmitRef.current;
    setModal({ kind: "reduction", amount: value, reason: reason.trim() });
  }

  return (
    <div className="case-detail-page">
      <OperatorHeader active="transactions" hasAttention={Boolean(pendingReduction)} />
      <main id="main">
        <div className="op-wrap narrow">
          {error ? <div className="op-alert error">{error}</div> : null}

          {/* ===== 概要 ===== */}
          <div className="listing-card">
            <div className="listing-info">
              <div className="listing-title">{txn.case?.purpose ?? "片付け案件"}</div>
              <div className="listing-meta">
                落札額 {formatYen(txn.initial_amount)}
                {txn.final_amount != null && txn.final_amount !== txn.initial_amount
                  ? ` → 確定額 ${formatYen(txn.final_amount)}`
                  : ""}
              </div>
            </div>
            <div className={`listing-status-badge ${txn.status === "completed" ? "badge-active" : txn.status === "cancelled" ? "badge-done" : "badge-waiting"}`}>
              {TXN_STATUS_LABEL[txn.status]}
            </div>
          </div>

          <div className="op-card">
            <DisclosureNotice viewer="operator" disclosed={disclosed} awaitingApproval={txn.awaiting_approval} />
          </div>

          {txn.address ? (
            <div className="decided-card">
              <div className="decided-label">✓ 住所開示済み</div>
              <div style={{ fontFamily: "var(--head)", fontWeight: 700, fontSize: 17, color: "var(--navy)" }}>
                {txn.address.prefecture} {txn.address.city} {txn.address.address_detail ?? ""}
              </div>
              {txn.contact_email ? <p className="listing-meta" style={{ marginTop: 6 }}>お客様連絡先: {txn.contact_email}</p> : null}
            </div>
          ) : txn.awaiting_approval ? null : (
            <div className="op-alert warn">住所詳細は表示できません（キャンセル済みの可能性）。</div>
          )}

          {txn.case?.photos?.length ? (
            <div className="op-card">
              <h2>写真</h2>
              <div className="op-photo-grid">
                {txn.case.photos.map((p) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={photoSrc(p.url)} alt="" key={p.id} />
                ))}
              </div>
            </div>
          ) : null}

          {txn.case?.ai_summary ? (
            <div className="op-card">
              <p className="op-ai-summary">AI要約</p>
              <p>{txn.case.ai_summary}</p>
            </div>
          ) : null}

          {/* ===== 減額申請 ===== */}
          <div className="op-card">
            <h2>減額申請</h2>
            {txn.reduction_requests.length > 0 && (
              <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                {txn.reduction_requests.map((r) => (
                  <li key={r.id} style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-s)", padding: "12px 14px" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ fontFamily: "var(--head)", fontWeight: 700, color: "var(--navy)" }}>
                        {formatYen(r.original_amount)} → {formatYen(r.requested_amount)}
                      </span>
                      <span className={`status-chip ${REDUCTION_CHIP_CLASS[r.status]}`}>{REDUCTION_STATUS_LABEL[r.status]}</span>
                    </div>
                    <p style={{ fontSize: 13, color: "var(--body)", lineHeight: 1.75, marginTop: 6 }}>{r.reason}</p>
                  </li>
                ))}
              </ul>
            )}

            {active && !pendingReduction ? (
              <form onSubmit={openReductionModal} style={{ marginTop: txn.reduction_requests.length > 0 ? 18 : 4 }}>
                <p style={{ fontSize: 13, color: "var(--body-soft)", marginBottom: 14, lineHeight: 1.8 }}>
                  現地確認の結果、物量・状態が想定と異なる場合のみ申請してください。現在の金額:{" "}
                  <strong style={{ color: "var(--navy)" }}>{formatYen(currentAmount)}</strong>
                </p>
                <div className="field">
                  <label htmlFor="reductionAmount">
                    減額後の提示額（円） <span className="req">必須</span>
                  </label>
                  <div className="yen-input-wrap">
                    <span className="yen-prefix">¥</span>
                    <input
                      id="reductionAmount"
                      type="number"
                      required
                      min={1}
                      max={currentAmount - 1}
                      value={requestedAmount}
                      onChange={(e) => setRequestedAmount(e.target.value)}
                    />
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="reductionReason">
                    理由 <span className="req">必須・10文字以上</span>
                  </label>
                  <textarea
                    id="reductionReason"
                    required
                    minLength={10}
                    rows={3}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="現地確認の結果、想定より家電の破損が多く再販価値が下がるため"
                  />
                  <p style={{ fontSize: 11.5, color: "var(--body-soft)", marginTop: 5 }}>お客様に表示されます。</p>
                </div>
                <button type="submit" ref={reductionSubmitRef} disabled={busy} className="btn btn-primary">
                  減額を申請する
                </button>
              </form>
            ) : null}
            {pendingReduction ? <div className="op-alert warn" style={{ marginTop: 14, marginBottom: 0 }}>お客様の回答待ちの申請があります。</div> : null}
            {!active ? <p style={{ fontSize: 13, color: "var(--body-soft)", marginTop: 8 }}>この成約では申請できません。</p> : null}
          </div>

          {/* ===== キャンセル ===== */}
          {active && (
            <div className="op-card">
              <h2>キャンセル</h2>
              <p style={{ fontSize: 13, color: "var(--body-soft)", marginTop: 4, marginBottom: 14 }}>
                業者都合のキャンセルは記録され、アカウント評価に影響します。
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={(e) => {
                  modalTriggerRef.current = e.currentTarget;
                  setCancelReason("");
                  setModal({ kind: "cancel" });
                }}
                className="btn"
                style={{ border: "1.5px solid #f3c8c8", color: "#c43d3d", background: "#fff" }}
              >
                この成約をキャンセルする
              </button>
            </div>
          )}

          {/* ===== レビュー ===== */}
          {txn.status === "completed" && (
            <div className="review-card">
              <h4>お客様を評価する</h4>
              {myReview ? (
                <p style={{ marginTop: 10 }}>レビュー投稿済み（★{myReview.rating}）ありがとうございました。</p>
              ) : (
                <>
                  <div className="review-stars-input" style={{ marginTop: 10 }}>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button key={n} type="button" onClick={() => setRating(n)} aria-label={`星${n}`} className={n <= rating ? "on" : ""}>
                        ★
                      </button>
                    ))}
                  </div>
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    className="modal-textarea"
                    style={{ marginTop: 12 }}
                    rows={3}
                    placeholder="取引の感想（任意）"
                  />
                  <button
                    type="button"
                    disabled={busy}
                    className="btn btn-primary"
                    onClick={() =>
                      act(() => createReview({ transaction_id: txn.id, rating, comment: comment.trim() || undefined }, token!))
                    }
                  >
                    レビューを投稿
                  </button>
                </>
              )}
            </div>
          )}

          <Link href="/operator/transactions" style={{ display: "inline-block", marginTop: 8, fontSize: 13.5, fontWeight: 700, color: "var(--blue)" }}>
            ← 落札管理一覧へ
          </Link>
        </div>
      </main>

      {/* ===== 減額申請 確認モーダル（B-2: window.confirm を置換） ===== */}
      <div className={`modal-overlay${modal?.kind === "reduction" ? " show" : ""}`}>
        {modal?.kind === "reduction" && (
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="reductionModalTitle">
            <h2 className="modal-title" id="reductionModalTitle">減額を申請しますか？</h2>
            <p className="modal-sub">お客様の承認後に金額が確定します。承認されるまでは現在の金額のままです。</p>
            <div className="modal-biz">
              <div className="modal-biz-avatar" style={{ background: "var(--gold, #b9892f)" }}>
                ¥
              </div>
              <div>
                <div className="modal-biz-name">{formatYen(currentAmount)} → {formatYen(modal.amount)}</div>
                <div className="modal-biz-amount" style={{ fontSize: 13, fontWeight: 600, color: "var(--body-soft)" }}>{modal.reason}</div>
              </div>
            </div>
            <div className="modal-actions">
              <button type="button" ref={reductionModalFirstFieldRef} className="btn-modal-cancel" onClick={closeModal} disabled={busy}>
                戻る
              </button>
              <button
                type="button"
                className="btn-modal-confirm"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await createReduction(txn.id, { requested_amount: modal.amount, reason: modal.reason }, token!);
                    closeModal();
                    setRequestedAmount("");
                    setReason("");
                  })
                }
              >
                申請する
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ===== キャンセル確認モーダル（B-2: window.prompt を置換） ===== */}
      <div className={`modal-overlay${modal?.kind === "cancel" ? " show" : ""}`}>
        {modal?.kind === "cancel" && (
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="cancelModalTitle">
            <h2 className="modal-title" id="cancelModalTitle">本当にキャンセルしますか？</h2>
            <p className="modal-sub">
              <strong>業者都合のキャンセルは記録され、アカウント評価に影響します。</strong>
              <br />
              理由を入力してください。
            </p>
            <textarea
              ref={cancelModalFirstFieldRef}
              className="modal-textarea"
              placeholder="キャンセル理由（必須）"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              rows={3}
            />
            <div className="modal-actions">
              <button type="button" className="btn-modal-cancel" onClick={closeModal} disabled={busy}>
                戻る
              </button>
              <button
                type="button"
                className="btn-modal-confirm danger"
                disabled={busy || !cancelReason.trim()}
                onClick={() =>
                  act(async () => {
                    await cancelTransaction(txn.id, cancelReason.trim(), token!);
                    closeModal();
                    setCancelReason("");
                  })
                }
              >
                キャンセルする
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
