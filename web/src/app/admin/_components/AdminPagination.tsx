"use client";

/** 50件ページング共通部品。前へ／次へボタン＋総件数表示。 */
export function AdminPagination({
  total,
  limit,
  offset,
  itemCount,
  onPrev,
  onNext,
}: {
  total: number;
  limit: number;
  offset: number;
  itemCount: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + itemCount;
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-500">
      <p>
        全{total.toLocaleString("ja-JP")}件中 {from.toLocaleString("ja-JP")}〜
        {to.toLocaleString("ja-JP")}件を表示
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={offset === 0}
          className="inline-flex items-center justify-center gap-1.5 rounded-none border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          前へ
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={offset + limit >= total}
          className="inline-flex items-center justify-center gap-1.5 rounded-none border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          次へ
        </button>
      </div>
    </div>
  );
}
