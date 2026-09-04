"use client";

/**
 * 破壊的操作（停止／解除等）向けの確認モーダル。
 * window.confirm はブラウザ既定のスタイルで文言が読みにくく、テストもしづらいため使わない。
 * 既存の許可証画像モーダル（admin/page.tsx）・本人確認書類モーダル（identity-documents/page.tsx）と
 * 同じ role="dialog" + 背景クリックで閉じる構成を踏襲する。
 */

import { useEffect, useRef, useState } from "react";
import { Notice, btnDanger, btnPrimary, btnSecondary, inputBase } from "@/components/kdz/Ui";

/** dialog 内でフォーカス移動可能な要素（disabled は除く）を集める共通セレクタ。 */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function ConfirmModal({
  title,
  message,
  confirmLabel,
  cancelLabel = "キャンセル",
  danger = false,
  withReason = false,
  reasonLabel = "理由（任意）",
  reasonRequired = false,
  error = null,
  busy = false,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** true の場合、確定ボタンを btnDanger（停止など不可逆寄りの操作向け）にする。 */
  danger?: boolean;
  /** true の場合、理由欄を表示し onConfirm に渡す。 */
  withReason?: boolean;
  reasonLabel?: string;
  /** true かつ withReason の場合、理由が空だと確定ボタンを disabled にしヒントを表示する（却下理由必須フロー用。r4-fix-frontend2 M2）。 */
  reasonRequired?: boolean;
  /** 操作失敗時のエラーメッセージ。渡された場合、モーダル内にも表示する（r4-fix-frontend2 M2: ConfirmModal拡張）。 */
  error?: string | null;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string | null) => void;
}) {
  const [reason, setReason] = useState("");
  const reasonMissing = withReason && reasonRequired && reason.trim() === "";

  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelBtnRef = useRef<HTMLButtonElement>(null);

  // マウント時: 開いた直前の要素を退避し、最初の操作可能要素（キャンセル）へフォーカスを移す。
  // アンマウント時: 退避しておいた要素へフォーカスを戻す（破壊的操作モーダルなので誤操作を防ぐため
  // 既定フォーカスは確定ボタンではなくキャンセルにする）。
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    cancelBtnRef.current?.focus();
    return () => {
      previouslyFocused?.focus();
    };
  }, []);

  // Esc で閉じる・Tab/Shift+Tab をダイアログ内に循環させる簡易フォーカストラップ。
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="adminConfirmModalTitle"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onCancel}
    >
      <div
        ref={dialogRef}
        className="w-full max-w-md rounded-none border border-slate-200 bg-white p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="adminConfirmModalTitle" className="font-normal text-slate-900">
          {title}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">{message}</p>
        {error ? (
          <div className="mt-3">
            <Notice tone="error">{error}</Notice>
          </div>
        ) : null}
        {withReason ? (
          <div className="mt-3">
            <label className="text-xs text-slate-500" htmlFor="adminConfirmModalReason">
              {reasonLabel}
            </label>
            <textarea
              id="adminConfirmModalReason"
              className={`${inputBase} mt-1`}
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            {reasonMissing ? (
              <p className="mt-1 text-xs text-red-600">理由を入力してください</p>
            ) : null}
          </div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" ref={cancelBtnRef} className={btnSecondary} onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={danger ? btnDanger : btnPrimary}
            onClick={() => onConfirm(withReason ? reason.trim() || null : null)}
            disabled={busy || reasonMissing}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
