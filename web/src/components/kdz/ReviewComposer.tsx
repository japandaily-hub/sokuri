"use client";

/**
 * 評価（よかった／伸びしろ）とコメントの入力フォーム（共通部品）。
 * /review・/cases/[id]・/operator/transactions/[id] の3画面で共通利用する。
 * デザイン正典: .agent-state/review-verdict/DESIGN.md (5)。
 *
 * 内部状態は verdict（初期 null・既定値なし）と comment のみ。チップの選択状態は
 * comment 文字列から hasPhrase() で導出し、チップ専用の状態は持たない。
 * busy は呼び出し側が管理する制御 props（送信中はボタンを無効化するだけで、
 * このコンポーネント自身は fetch を行わない＝実際の送信・エラー処理は onSubmit の先で
 * 呼び出し側が行う）。送信が失敗しても呼び出し側がこのコンポーネントを描画し続ける限り
 * verdict/comment は保持される（内部 state のため、busy が false に戻っても消えない）。
 */

import "./review-composer.css";

import { useId, useState } from "react";
import type { ReviewVerdict } from "@/lib/katadzuke-api";
import {
  REVIEW_COMMENT_MAX,
  REVIEW_PHRASES,
  REVIEW_PLACEHOLDER,
  REVIEW_VERDICT_LABEL,
  appendPhrase,
  canAppend,
  hasPhrase,
  removePhrase,
  type ReviewDirection,
} from "@/lib/review-verdict";

/** 評価の選択肢の補助文（ラベルだけでは基準が伝わらないため）。 */
const VERDICT_HINT: Record<ReviewVerdict, string> = {
  good: "満足できた",
  improve: "改善してほしい点があった",
};

/** チェック図形（review/page.tsx の done-ic / submitted-ic と同じ意匠を再利用）。 */
function CheckGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}

export type ReviewComposerProps = {
  /** 評価の向き。to_operator=依頼者→業者／to_user=業者→依頼者。候補文・公開注意書きの出し分けに使う。 */
  direction: ReviewDirection;
  /** 送信ボタンの文言（呼び出し側の既存文言をそのまま渡す。E2E がこの文言に依存する画面がある）。 */
  submitLabel: string;
  /** 送信中かどうか（呼び出し側が管理する）。true の間は送信ボタンを無効化する。 */
  busy: boolean;
  /** 送信ハンドラ。呼び出し側で createReview() 等の実際の送信・エラー処理を行う。 */
  onSubmit: (value: { verdict: ReviewVerdict; comment?: string }) => void | Promise<void>;
};

/** 評価とコメントの入力フォーム（3画面共通）。 */
export function ReviewComposer({ direction, submitLabel, busy, onSubmit }: ReviewComposerProps) {
  const [verdict, setVerdict] = useState<ReviewVerdict | null>(null);
  const [comment, setComment] = useState("");

  const baseId = useId();
  const commentId = `${baseId}-comment`;
  const countId = `${baseId}-count`;
  const submitHintId = `${baseId}-submit-hint`;

  const phrases = verdict ? REVIEW_PHRASES[direction][verdict] : null;
  const canSubmit = !busy && verdict !== null;

  function handleChipClick(phrase: string, selected: boolean) {
    if (!selected && !canAppend(comment, phrase)) return;
    setComment((prev) => (selected ? removePhrase(prev, phrase) : appendPhrase(prev, phrase)));
  }

  function handleSubmit() {
    if (busy || verdict === null) return;
    void onSubmit({ verdict, comment: comment.trim() || undefined });
  }

  return (
    <div className="kdz-review-composer">
      <fieldset className="kdz-review-composer__fieldset">
        <legend className="kdz-review-composer__legend">取引はいかがでしたか？</legend>
        <div className="kdz-review-composer__options">
          {(["good", "improve"] as const).map((v) => {
            const optionId = `${baseId}-verdict-${v}`;
            return (
              <label key={v} className="kdz-review-composer__option" htmlFor={optionId}>
                {/* 補助文は label 内にあり、htmlFor で結ばれた <label> の内容として
                    アクセシブルネーム（例:「よかった 満足できた」）に既に含まれるため、
                    aria-describedby では重ねて読み上げない（QAレビュー Low 対応）。 */}
                <input
                  type="radio"
                  id={optionId}
                  name={`${baseId}-verdict`}
                  className="kdz-review-composer__option-input"
                  checked={verdict === v}
                  onChange={() => setVerdict(v)}
                />
                <span className="kdz-review-composer__option-box" aria-hidden="true">
                  <CheckGlyph />
                </span>
                <span className="kdz-review-composer__option-text">
                  <span className="kdz-review-composer__option-label">{REVIEW_VERDICT_LABEL[v]}</span>
                  <span className="kdz-review-composer__option-hint">{VERDICT_HINT[v]}</span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {phrases ? (
        <div
          className="kdz-review-composer__chips"
          role="group"
          aria-label="よく使われる文（タップで追加・もう一度で削除）"
        >
          {phrases.map((phrase) => {
            const selected = hasPhrase(comment, phrase);
            const disabled = !selected && !canAppend(comment, phrase);
            return (
              <button
                key={phrase}
                type="button"
                className={`kdz-review-composer__chip${selected ? " is-selected" : ""}`}
                aria-pressed={selected}
                aria-disabled={disabled ? "true" : undefined}
                onClick={() => handleChipClick(phrase, selected)}
              >
                {phrase}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="kdz-review-composer__guidance">
          『よかった』か『伸びしろ』を選ぶと、よく使われる文を1タップで入力できます
        </p>
      )}

      <label className="kdz-review-composer__comment-label" htmlFor={commentId}>
        コメント（任意）
      </label>
      <textarea
        id={commentId}
        className="kdz-review-composer__textarea"
        placeholder={REVIEW_PLACEHOLDER[direction]}
        maxLength={REVIEW_COMMENT_MAX}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        aria-describedby={countId}
      />
      <p className="kdz-review-composer__count" id={countId}>
        {comment.length}/{REVIEW_COMMENT_MAX}文字
      </p>

      {direction === "to_operator" ? (
        <p className="kdz-review-composer__disclosure">
          評価とコメントは業者のプロフィールで公開されます。お名前や住所など、個人が特定される情報は書かないでください。
        </p>
      ) : null}

      <div className="kdz-review-composer__submit-area">
        {verdict === null ? (
          <p className="kdz-review-composer__submit-hint" id={submitHintId}>
            評価を選択すると送信できます
          </p>
        ) : null}
        <button
          type="button"
          className="btn btn-primary btn-block btn-lg"
          disabled={!canSubmit}
          aria-describedby={verdict === null ? submitHintId : undefined}
          onClick={handleSubmit}
        >
          {busy ? (
            <>
              <span className="spinning">↻</span> 送信中…
            </>
          ) : (
            submitLabel
          )}
        </button>
      </div>
    </div>
  );
}
