"use client";

import "./review.css";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Spinner } from "@/components/Icon";
import { Notice, useToken } from "@/components/kdz/Ui";
import {
  TXN_STATUS_LABEL,
  createReview,
  formatYen,
  getTransaction,
  toDisplayMessage,
  type TransactionDetail,
} from "@/lib/katadzuke-api";

/* ============================================================
   取引完了・評価ページ（カタヅケ）
   デザイン正典: docs/design_handoff_katazuke/取引完了・評価.html
   ?transaction_id= 駆動で getTransaction を取得し、★評価+コメントを
   createReview で送信する（2026-07-03 実配線）。
   タグ選択UIは維持しつつ、送信は rating + comment のみ（選択タグは
   comment 末尾に「良かった点: …」として付与する）。
   ============================================================ */

/** スター数 → ラベル。index 0 は未選択時のプレースホルダ用。 */
const STAR_LABELS = ["", "がっかりした", "もう少し…", "普通", "良かった！", "最高でした！"];

/** 良かった点タグ（複数選択可）。 */
const TAGS: { id: string; label: string }[] = [
  { id: "price", label: "査定額が高い" },
  { id: "speed", label: "対応が速い" },
  { id: "kind", label: "スタッフが親切" },
  { id: "explain", label: "説明が丁寧" },
  { id: "carry", label: "搬出が丁寧" },
  { id: "cancel", label: "キャンセル対応" },
];

const MAX_COMMENT = 300;

/**
 * "YYYY-MM-DD" 形式の date 文字列を日本語表記に整形する。
 * new Date("YYYY-MM-DD") は ISO 8601 の日付限定形式として UTC 深夜0時に解釈されるため、
 * JST 環境では toLocaleString で前日または当日の別時刻にズレる（典型バグ）。
 * ここでは Date化せず文字列を直接分解して組み立てる。
 */
function formatVisitDate(visitDate: string | null): string {
  if (!visitDate) return "—";
  const m = visitDate.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return visitDate;
  const [, y, mo, d] = m;
  return `${y}年${Number(mo)}月${Number(d)}日`;
}

function ReviewPageInner() {
  const search = useSearchParams();
  const transactionId = search.get("transaction_id");
  const { token, loading } = useToken();

  const [txn, setTxn] = useState<TransactionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  /* ---- 評価フォーム状態 ---- */
  const [star, setStar] = useState(0);
  const [hoverStar, setHoverStar] = useState(0);
  const [popStar, setPopStar] = useState<number | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");

  /* ---- 送信フロー ---- */
  const [busy, setBusy] = useState(false);
  const [justSubmitted, setJustSubmitted] = useState(false);
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

  function toggleTag(id: string) {
    setTags((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  }

  function selectStar(v: number) {
    setStar(v);
    setPopStar(v);
    window.setTimeout(() => setPopStar(null), 200);
  }

  function showToast(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2400);
  }

  async function submitReview() {
    if (busy || !token || !txn || star === 0) return;
    setBusy(true);
    setError(null);
    try {
      const tagLabels = TAGS.filter((t) => tags.includes(t.id)).map((t) => t.label);
      const commentBody = [
        comment.trim(),
        tagLabels.length > 0 ? `良かった点: ${tagLabels.join("、")}` : "",
      ]
        .filter(Boolean)
        .join("\n");
      await createReview(
        { transaction_id: txn.id, rating: star, comment: commentBody || undefined },
        token,
      );
      setJustSubmitted(true);
      await reload();
      showToast("評価を送信しました");
    } catch (e) {
      setError(toDisplayMessage(e, "評価の送信に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  const displayStar = hoverStar || star;

  if (loading || (!txn && !error && transactionId)) {
    return (
      <div className="review-page">
        <AppHeader unread />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  if (!transactionId || (!txn && error)) {
    return (
      <div className="review-page">
        <AppHeader unread />
        <main>
          <div className="review-wrap">
            <Notice tone="error">
              {!transactionId
                ? "評価対象の取引が指定されていません。"
                : (error ?? "取引情報の取得に失敗しました。")}
            </Notice>
            <Link href="/cases" className="btn btn-primary btn-lg btn-block" style={{ marginTop: 16 }}>
              マイ案件一覧へ戻る
            </Link>
          </div>
        </main>
      </div>
    );
  }

  if (!txn) return null;

  const alreadyReviewed = txn.reviews.some((r) => r.reviewer_type === "user");
  const isCompleted = txn.status === "completed";
  const isCancelled = txn.status === "cancelled";
  // completed のみ評価フォームを活性化する（cases/[id] の既存インラインレビューと同じ条件）。
  const showSubmittedScreen = isCompleted && (alreadyReviewed || justSubmitted);
  const vendorName = txn.operator?.company_name ?? "業者";
  const amountText = formatYen(txn.final_amount ?? txn.initial_amount);
  const itemsText = txn.case?.purpose ?? "—";
  const visitText = txn.visit_date
    ? `${formatVisitDate(txn.visit_date)}${txn.visit_time_slot ? ` ${txn.visit_time_slot}` : ""}`
    : "—";

  return (
    <div className="review-page">
      <AppHeader unread />

      <main>
        <div className="review-wrap">
          {/* 状態バナー: completed のみ「完了」表示。pending/visiting は進行中、cancelled はキャンセル表示。 */}
          {isCompleted ? (
            <div className="done-banner">
              <div className="done-ic">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5l4.5 4.5L19 7" />
                </svg>
              </div>
              <div className="done-title">取引が完了しました！</div>
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
              取引が進行中です（{TXN_STATUS_LABEL[txn.status]}）。作業完了後に業者を評価できます。
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

              {/* スター選択 */}
              <div className="star-selector" onMouseLeave={() => setHoverStar(0)}>
                {[1, 2, 3, 4, 5].map((v) => (
                  <button
                    key={v}
                    type="button"
                    className={`star-btn${v <= star ? " active" : ""}${popStar === v ? " star-pop" : ""}`}
                    style={v <= displayStar ? { color: "#f0a030" } : undefined}
                    aria-label={`${v}つ星`}
                    aria-pressed={v <= star}
                    onMouseEnter={() => setHoverStar(v)}
                    onClick={() => selectStar(v)}
                  >
                    ★
                  </button>
                ))}
              </div>
              <div className="star-label">{STAR_LABELS[star] || "タップして評価する"}</div>

              {/* 評価タグ */}
              <div className="tag-title">良かった点（複数選択可）</div>
              <div className="tag-grid">
                {TAGS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`tag-chip${tags.includes(t.id) ? " selected" : ""}`}
                    aria-pressed={tags.includes(t.id)}
                    onClick={() => toggleTag(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {/* コメント */}
              <div className="tag-title">コメント（任意）</div>
              <textarea
                className="review-textarea"
                placeholder="業者の対応や査定の印象をご記入ください。"
                maxLength={MAX_COMMENT}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <div className="textarea-count">
                {comment.length}/{MAX_COMMENT}文字
              </div>

              {/* アクション */}
              <div className="submit-area">
                <button
                  type="button"
                  className="btn btn-primary btn-block btn-lg"
                  disabled={busy || star === 0}
                  onClick={submitReview}
                >
                  {busy ? (
                    <>
                      <span className="spinning">↻</span> 送信中…
                    </>
                  ) : (
                    "評価を送信する"
                  )}
                </button>
              </div>
            </div>
          ) : (
            <div className="submitted-screen">
              <div className="submitted-ic">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5l4.5 4.5L19 7" />
                </svg>
              </div>
              <h2>評価を送信しました！</h2>
              <p>
                ご協力ありがとうございました。
                <br />
                評価は投稿済みです。
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
              <Link href="/cases" className="next-action-btn">
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

export default function ReviewPage() {
  return (
    <Suspense
      fallback={
        <div className="review-page">
          <AppHeader unread />
          <div className="flex min-h-[50vh] items-center justify-center">
            <Spinner className="h-6 w-6 text-brand-600" />
          </div>
        </div>
      }
    >
      <ReviewPageInner />
    </Suspense>
  );
}
