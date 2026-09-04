"use client";

/**
 * ステータス絞り込みボタン列。既存の業者一覧（admin/page.tsx）・本人確認書類一覧
 * （identity-documents/page.tsx）の statusFilter ボタンと同一の見た目・挙動を汎用化したもの。
 */
export function StatusFilterBar<S extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: S; label: string; count?: number }[];
  value: S;
  onChange: (next: S) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded-none px-3 py-1.5 text-xs font-medium transition-colors ${
            value === opt.value
              ? "bg-brand-600 text-white"
              : "bg-slate-100 text-slate-600 hover:bg-slate-200"
          }`}
        >
          {opt.label}
          {opt.count !== undefined ? ` ${opt.count}` : ""}
        </button>
      ))}
    </div>
  );
}
