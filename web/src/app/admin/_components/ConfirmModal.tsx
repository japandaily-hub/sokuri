"use client";

/**
 * 破壊的操作（停止／解除等）向けの確認モーダル。
 * window.confirm はブラウザ既定のスタイルで文言が読みにくく、テストもしづらいため使わない。
 * 既存の許可証画像モーダル（admin/page.tsx）・本人確認書類モーダル（identity-documents/page.tsx）と
 * 同じ role="dialog" + 背景クリックで閉じる構成を踏襲する。
 */

import { useState } from "react";
import { btnDanger, btnPrimary, btnSecondary, inputBase } from "@/components/kdz/Ui";

export function ConfirmModal({
  title,
  message,
  confirmLabel,
  cancelLabel = "キャンセル",
  danger = false,
  withReason = false,
  reasonLabel = "理由（任意）",
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
  /** true の場合、任意入力の理由欄を表示し onConfirm に渡す。 */
  withReason?: boolean;
  reasonLabel?: string;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string | null) => void;
}) {
  const [reason, setReason] = useState("");

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="adminConfirmModalTitle"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-none border border-slate-200 bg-white p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="adminConfirmModalTitle" className="font-normal text-slate-900">
          {title}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">{message}</p>
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
          </div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={danger ? btnDanger : btnPrimary}
            onClick={() => onConfirm(withReason ? reason.trim() || null : null)}
            disabled={busy}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
