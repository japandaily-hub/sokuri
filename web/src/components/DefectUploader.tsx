'use client';

import { useState, useRef } from "react";
import { uploadDefects, ApiError } from "@/lib/api";
import { formatFileSize } from "@/lib/format";
import { Icon, Spinner } from "@/components/Icon";

interface DefectUploaderProps {
  assessmentId: string;
}

type UploadStatus = "idle" | "uploading" | "success" | "error";

/**
 * 瑕疵写真アップロードコンポーネント。
 * defect_evidence_required=true のときに /result ページ内で使用する。
 */
export default function DefectUploader({ assessmentId }: DefectUploaderProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    setFiles((prev) => {
      // 重複除去（name+size で簡易判定）
      const existing = new Set(prev.map((f) => `${f.name}:${f.size}`));
      const next = selected.filter(
        (f) => !existing.has(`${f.name}:${f.size}`),
      );
      return [...prev, ...next];
    });
    // input をリセットして同じファイルの再選択を可能にする
    if (inputRef.current) inputRef.current.value = "";
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleUpload() {
    if (files.length === 0) return;
    setStatus("uploading");
    setErrorMessage("");
    try {
      await uploadDefects(assessmentId, files);
      setStatus("success");
      setFiles([]);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "アップロードに失敗しました。再度お試しください。";
      setErrorMessage(message);
      setStatus("error");
    }
  }

  // --- 完了状態 ---
  if (status === "success") {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-accent-200 bg-accent-50 p-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-100 text-accent-600">
          <Icon name="check" className="h-5 w-5" strokeWidth={2.75} />
        </span>
        <p className="text-sm font-semibold text-accent-700">
          瑕疵写真のアップロードが完了しました。
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
      {/* 案内バナー */}
      <div className="flex items-start gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-600">
          <Icon name="alert" className="h-5 w-5" />
        </span>
        <div>
          <p className="text-sm font-bold text-amber-900">瑕疵の証拠写真が必要です</p>
          <p className="mt-0.5 text-xs leading-relaxed text-amber-700">
            正確な査定のため、傷や汚れの写真をアップロードしてください。
          </p>
        </div>
      </div>

      {/* ファイル選択 */}
      <label className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border-2 border-dashed border-amber-300 bg-white px-4 py-3 text-sm font-semibold text-amber-700 transition-colors hover:bg-amber-50">
        <Icon name="image" className="h-4 w-4" />
        写真を選択
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          className="sr-only"
          onChange={handleFileChange}
        />
      </label>

      {/* 選択済みファイル一覧 */}
      {files.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {files.map((file, i) => (
            <li
              key={`${file.name}:${file.size}`}
              className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                <Icon name="image" className="h-4 w-4 shrink-0 text-slate-400" />
                <span className="truncate text-xs text-slate-700">{file.name}</span>
                <span className="shrink-0 text-xs tabular-nums text-slate-400">
                  {formatFileSize(file.size)}
                </span>
              </div>
              <button
                type="button"
                onClick={() => removeFile(i)}
                className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 focus-visible:ring-2 focus-visible:ring-red-400"
                aria-label={`${file.name} を削除`}
              >
                <Icon name="close" className="h-4 w-4" strokeWidth={2.25} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* エラーメッセージ */}
      {status === "error" && (
        <p className="text-xs font-medium text-red-600">{errorMessage}</p>
      )}

      {/* アップロードボタン */}
      <button
        type="button"
        disabled={files.length === 0 || status === "uploading"}
        onClick={handleUpload}
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-semibold text-white shadow-xs transition-colors hover:bg-amber-600 active:bg-amber-700 focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
      >
        {status === "uploading" ? (
          <>
            <Spinner className="h-4 w-4" />
            アップロード中…
          </>
        ) : (
          "写真をアップロードする"
        )}
      </button>
    </div>
  );
}
