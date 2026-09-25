"use client";

import "./review.css";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AppHeader } from "@/components/kdz/AppHeader";
import { formatVisitSchedule } from "@/lib/categories";
import { formatPurposeLabel } from "@/lib/case-labels";
import { Spinner } from "@/components/Icon";
import { Notice, useToken } from "@/components/kdz/Ui";
import {
  TXN_STATUS_LABEL,
  createReview,
  formatYen,
  getTransaction,
  toDisplayMessage,
  type ReviewVerdict,
  type TransactionDetail,
} from "@/lib/katadzuke-api";
import { REVIEW_VERDICT_LABEL } from "@/lib/review-verdict";
import { ReviewComposer } from "@/components/kdz/ReviewComposer";

/* ============================================================
   取引完了・評価ページ（カタヅケ）
   デザイン正典: docs/design_handoff_katazuke/取引完了・評価.html
   ?transaction_id= 駆動で getTransaction を取得し、評価（よかった／伸びしろ）+
   コメントを createReview で送信する（2026-07-03 実配線、2026-09-25 評価を
   2択化＋ワンタップ入力に刷新。共通部品 ReviewComposer に委譲する）。
   ============================================================ */

/**
 * "YYYY-MM-DD" 形式の date 文字列を日本語表記に整形する。
 * new Date("YYYY-MM-DD") は ISO 8601 の日付限定形式として UTC 深夜0時に解釈されるため、
 * JST 環境では toLocaleString で前日または当日の別時刻にズレる（典型バグ）。
 * ここでは Date化せず文字列を直接分解して組み立てる。
 */

function ReviewPageInner() {
  const search = useSearchParams();
  const transactionId = search.get("transaction_id");
  const { token, loading } = useToken();

  const [txn, setTxn] = useState<TransactionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  /* ---- 送信フロー ---- */
  const [busy, setBusy] = useState(false);
  const [justSubmitted, setJustSubmitted] = useState(false);
  /**
   * 送信直後、reload() が完了して txn.reviews に反映されるまでの間（reload 失敗時はそのまま）
   * myReview がまだ undefined のため、送信した verdict をここに保持し表示のフォールバックにする
   * （QAレビュー Medium 対応: 「評価投稿済み（）」と空の括弧が出ていた）。
   */
  const [submittedVerdict, setSubmittedVerdict] = useState<ReviewVerdict | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token || !transactionId) return;
    try {
      setTxn(await getTransaction(transactionId, token));
    } catch (e) {
      setError(toDisplayMessage(e, "取引情報の取得に失敗しました"));
    }
  }, [token, transactionId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function showToast(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2400);
  }

  async function submitReview(value: { verdict: ReviewVerdict; comment?: string }) {
    if (busy || !token || !txn) return;
    setBusy(true);
    setError(null);
    try {
      await createReview(
        { transaction_id: txn.id, verdict: value.verdict, comment: value.comment },
        token,
      );
      setSubmittedVerdict(value.verdict);
      setJustSubmitted(true);
      await reload();
      showToast("評価を送信しました");
    } catch (e) {
      setError(toDisplayMessage(e, "評価の送信に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!txn && !error && transactionId)) {
    return (
      <div className="review-page">
        <AppHeader />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  if (!transactionId || (!txn && error)) {
    return (
      <div className="review-page">
        <AppHeader />
        <main id="main">
          <div className="review-wrap">
            <Notice tone="error">
              {!transactionId
                ? "評価対象の取引が指定されていません。"
                : (error ?? "取引情報の取得に失敗しました。")}
            </Notice>
            <Link href="/mypage" className="btn btn-primary btn-lg btn-block" style={{ marginTop: 16 }}>
              マイページへ戻る
            </Link>
          </div>
        </main>
      </div>
    );
  }

  if (!txn) return null;

  const myReview = txn.reviews.find((r) => r.reviewer_type === "user");
  // reload 完了前（または失敗時）は myReview がまだ無いため、送信直後に保持した
  // submittedVerdict をフォールバックに使う（空括弧「評価投稿済み（）」を防ぐ）。
  const displayVerdict = myReview?.verdict ?? submittedVerdict;
  const alreadyReviewed = myReview != null;
  const isCompleted = txn.status === "completed";
  const isCancelled = txn.status === "cancelled";
  // completed のみ評価フォームを活性化する（cases/[id] の既存インラインレビューと同じ条件）。
  const showSubmittedScreen = isCompleted && (alreadyReviewed || justSubmitted);
  const vendorName = txn.operator?.company_name ?? "業者";
  const amountText = formatYen(txn.final_amount ?? txn.initial_amount);
  const itemsText = formatPurposeLabel(txn.case?.purpose, "—");
  const visitText = txn.visit_date
    ? formatVisitSchedule(txn.visit_date, txn.visit_time_slot)
    : "—";

  return (
    <div className="review-page">
      <AppHeader />

      <main id="main">
        <div className="review-wrap">
          {/* 状態バナー: completed のみ「完了」表示。pending/visiting は進行中、cancelled はキャンセル表示。 */}
          {isCompleted ? (
            <div className="done-banner">
              <div className="done-ic">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5l4.5 4.5L19 7" />
                </svg>
              </div>
              <div className="done-title">取引が完了しました。</div>
              <div className="done-sub">
                {vendorName} との取引が正常に完了しました。
                <br />
                ご利用ありがとうございました。
              </div>
            </div>
          ) : isCancelled ? (
            <Notice tone="error">この取引はキャンセルされました。</Notice>
          ) : (
            <Notice tone="info">
              取引が進行中です（{TXN_STATUS_LABEL[txn.status]}）。
            </Notice>
          )}

          {error ? <Notice tone="error">{error}</Notice> : null}

          {/* 取引サマリー */}
          <div className="txn-card">
            <div className="txn-card-title">取引内容</div>
            <div className="txn-row">
              <span className="txn-lbl">業者名</span>
              <span className="txn-val">{vendorName}</span>
            </div>
            <div className="txn-row">
              <span className="txn-lbl">出品内容</span>
              <span className="txn-val">{itemsText}</span>
            </div>
            <div className="txn-row">
              <span className="txn-lbl">訪問日時</span>
              <span className="txn-val">{visitText}</span>
            </div>
            <div className="txn-row">
              <span className="txn-lbl">受取金額</span>
              <span className="txn-val txn-amount">{amountText}</span>
            </div>
          </div>

          {/* 評価フォーム / 送信済み画面 / 未完了案内（completed 以外は評価フォームを出さない） */}
          {!isCompleted ? (
            <div className="rate-card">
              <div className="rate-card-title">
                {isCancelled ? "この取引はキャンセルされました" : "取引が進行中です"}
              </div>
              <div className="rate-card-sub">
                {isCancelled
                  ? "キャンセルされた取引は評価できません。"
                  : "作業完了後に業者を評価できます。進捗は案件詳細からご確認いただけます。"}
              </div>
              <Link
                href={`/cases/${txn.case_id}`}
                className="btn btn-primary btn-block btn-lg"
                style={{ marginTop: 16 }}
              >
                案件詳細を見る
              </Link>
            </div>
          ) : !showSubmittedScreen ? (
            <div className="rate-card">
              <div className="rate-card-title">業者を評価してください</div>
              <div className="rate-card-sub">
                評価はほかのユーザーの業者選びに役立ちます。ぜひご協力ください。
              </div>

              <ReviewComposer
                direction="to_operator"
                submitLabel="評価を送信する"
                busy={busy}
                onSubmit={submitReview}
              />
            </div>
          ) : (
            <div className="submitted-screen">
              <div className="submitted-ic">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5l4.5 4.5L19 7" />
                </svg>
              </div>
              <h2>評価を送信しました。</h2>
              <p>
                評価投稿済み（{displayVerdict ? REVIEW_VERDICT_LABEL[displayVerdict] : ""}）
                <br />
                ご協力ありがとうございました。
              </p>
            </div>
          )}

          {/* 次のアクション */}
          <div className="next-card">
            <div className="next-card-title">次に何をしますか？</div>
            <div className="next-actions">
              <Link href="/create" className="next-action-btn">
                <div className="next-action-ic" style={{ background: "var(--pale)", color: "var(--blue)" }}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
                  </svg>
                </div>
                <div className="next-action-body">
                  <strong>また出品する</strong>
                  <span>まだ片付けたいものがありますか？</span>
                </div>
                <div className="next-action-arr">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </div>
              </Link>
              <Link href="/mypage" className="next-action-btn">
                <div className="next-action-ic" style={{ background: "#e8faf0", color: "var(--green)" }}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                </div>
                <div className="next-action-body">
                  <strong>案件状況を確認</strong>
                  <span>他の出品の入札状況を見る</span>
                </div>
                <div className="next-action-arr">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </div>
              </Link>
            </div>
          </div>
        </div>
      </main>

      {toast ? <div className="kdz-toast">{toast}</div> : null}
    </div>
  );
}

/**
 * transaction_id が変わるたびに ReviewPageInner を key で作り直す（QAレビュー予防対応）。
 * ReviewPageInner は内部に busy/justSubmitted/submittedVerdict 等の状態を持つため、
 * 同一ページ内で transaction_id だけがクライアント側遷移で変わった場合、key が無いと
 * インスタンスが使い回され、前の取引の送信済み状態が新しい取引に残ってしまう。
 * ReviewPageInner 自身も useSearchParams を呼ぶため、ここでの呼び出しは
 * key を得るためだけの重複呼び出しになるが副作用は無い（Suspense 構造は維持）。
 */
function ReviewPageKeyed() {
  const search = useSearchParams();
  const transactionId = search.get("transaction_id");
  return <ReviewPageInner key={transactionId ?? ""} />;
}

export default function ReviewPage() {
  return (
    <Suspense
      fallback={
        <div className="review-page">
          <AppHeader />
          <div className="flex min-h-[50vh] items-center justify-center">
            <Spinner className="h-6 w-6 text-brand-600" />
          </div>
        </div>
      }
    >
      <ReviewPageKeyed />
    </Suspense>
  );
}
