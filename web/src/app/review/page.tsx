"use client";

import "./review.css";

import Link from "next/link";
import { useState } from "react";
import { AppHeader } from "@/components/kdz/AppHeader";

/* ============================================================
   取引完了・評価ページ（カタヅケ）
   デザイン正典: docs/design_handoff_katazuke/取引完了・評価.html
   完了バナー / 取引サマリー / 5スター選択 / 評価タグ複数選択 / コメント /
   公開トグル / 送信・スキップ。
   バックエンド未配線：取引内容はモック定数。評価の送信/スキップは実処理せず
   UI 挙動（送信中スピナー → 送信済み画面 + デモトースト）のみ。
   ============================================================ */

/** 取引サマリー（デモ用モック）。 */
const TXN = {
  vendor: "グリーンリサイクル東京",
  items: "家電・ブランド品 5点",
  visit: "2026年6月21日（土）13:30",
  amount: "¥58,000",
};

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

/** 送信後の完了表示パターン（送信／スキップで文言・アイコンを切替）。 */
type Submitted =
  | { kind: "submitted" }
  | { kind: "skipped" }
  | null;

export default function ReviewPage() {
  /* ---- 評価フォーム状態 ---- */
  const [star, setStar] = useState(0);
  const [hoverStar, setHoverStar] = useState(0);
  const [popStar, setPopStar] = useState<number | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [publish, setPublish] = useState(true);

  /* ---- 送信フロー（実処理なし：UI 挙動のみ） ---- */
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState<Submitted>(null);
  const [toast, setToast] = useState<string | null>(null);

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

  function submitReview() {
    if (busy) return;
    setBusy(true);
    // バックエンド未配線：送信中スピナーを見せたあと送信済み画面へ切替（デモ）。
    window.setTimeout(() => {
      setBusy(false);
      setSubmitted({ kind: "submitted" });
      showToast("評価を送信しました（デモ）");
    }, 900);
  }

  function skipReview() {
    setSubmitted({ kind: "skipped" });
  }

  // 表示用：ホバー中はホバー値、未ホバーなら選択値で塗り分け。
  const displayStar = hoverStar || star;

  return (
    <div className="review-page">
      <AppHeader unread />

      <main>
        <div className="review-wrap">
          {/* 完了バナー */}
          <div className="done-banner">
            <div className="done-ic">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 12.5l4.5 4.5L19 7" />
              </svg>
            </div>
            <div className="done-title">取引が完了しました！</div>
            <div className="done-sub">
              {TXN.vendor} との取引が正常に完了しました。
              <br />
              ご利用ありがとうございました。
            </div>
          </div>

          {/* 取引サマリー */}
          <div className="txn-card">
            <div className="txn-card-title">取引内容</div>
            <div className="txn-row">
              <span className="txn-lbl">業者名</span>
              <span className="txn-val">{TXN.vendor}</span>
            </div>
            <div className="txn-row">
              <span className="txn-lbl">出品内容</span>
              <span className="txn-val">{TXN.items}</span>
            </div>
            <div className="txn-row">
              <span className="txn-lbl">訪問日時</span>
              <span className="txn-val">{TXN.visit}</span>
            </div>
            <div className="txn-row">
              <span className="txn-lbl">受取金額</span>
              <span className="txn-val txn-amount">{TXN.amount}</span>
            </div>
          </div>

          {/* 評価フォーム / 送信済み画面 */}
          {submitted === null ? (
            <div className="rate-card">
              <div className="rate-card-title">業者を評価してください</div>
              <div className="rate-card-sub">
                評価はほかのユーザーの業者選びに役立ちます。ぜひご協力ください（任意）。
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

              {/* 公開設定 */}
              <div className="publish-row">
                <label className="publish-toggle">
                  <input
                    type="checkbox"
                    checked={publish}
                    onChange={(e) => setPublish(e.target.checked)}
                    aria-label="評価をほかのユーザーに公開する"
                  />
                  <span className="toggle-slider" />
                </label>
                <span className="publish-label">
                  評価をほかのユーザーに公開する
                  <br />
                  <span className="publish-note">名前は「田中 美○」のように一部伏字で表示されます</span>
                </span>
              </div>

              {/* アクション */}
              <div className="submit-area">
                <button
                  type="button"
                  className="btn btn-primary btn-block btn-lg"
                  disabled={busy}
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
                <button
                  type="button"
                  className="btn btn-ghost btn-block"
                  style={{ marginTop: 10 }}
                  disabled={busy}
                  onClick={skipReview}
                >
                  スキップする
                </button>
              </div>
            </div>
          ) : (
            <div className="submitted-screen">
              <div className="submitted-ic">
                {submitted.kind === "submitted" ? (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12.5l4.5 4.5L19 7" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 11v-1a7 7 0 0114 0v1" />
                    <path d="M12 3v4M9 13v3M15 13v3M12 13v5" />
                    <path d="M6 13h12l-1 7H7z" />
                  </svg>
                )}
              </div>
              {submitted.kind === "submitted" ? (
                <>
                  <h2>評価を送信しました！</h2>
                  <p>
                    ご協力ありがとうございました。
                    <br />
                    評価は審査後に公開されます。
                  </p>
                </>
              ) : (
                <>
                  <h2>ありがとうございました</h2>
                  <p>またのご利用をお待ちしています。</p>
                </>
              )}
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
              <Link href="/applications" className="next-action-btn">
                <div className="next-action-ic" style={{ background: "#e8faf0", color: "var(--green)" }}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                </div>
                <div className="next-action-body">
                  <strong>申し込み状況を確認</strong>
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
