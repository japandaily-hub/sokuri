/**
 * 従来の売り方との比較表セクション（差別化提示）。
 */

import { Icon } from "@/components/Icon";

type Mark = "good" | "mid" | "bad";

const ROWS: { label: string; flea: Mark; bulk: Mark; sokuri: Mark; note: string }[] = [
  { label: "出品・入力の手間", flea: "bad", bulk: "mid", sokuri: "good", note: "1点ずつ撮るだけ" },
  { label: "価格・相場の調査", flea: "bad", bulk: "mid", sokuri: "good", note: "業者が査定を提示" },
  { label: "連絡・営業電話", flea: "mid", bulk: "bad", sokuri: "good", note: "連絡は上位3社のみ" },
  { label: "査定額の伸びやすさ", flea: "mid", bulk: "mid", sokuri: "good", note: "業者が競うから伸びやすい" },
];

/** 評価マーク 1 セル分。良 / 中 / 不可 を視覚的に区別する。 */
function MarkCell({ value }: { value: Mark }) {
  if (value === "good") {
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-accent-100 text-accent-600">
        <Icon name="check" className="h-4 w-4" strokeWidth={3} />
      </span>
    );
  }
  if (value === "bad") {
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 text-slate-300">
        <Icon name="close" className="h-4 w-4" strokeWidth={2.5} />
      </span>
    );
  }
  return (
    <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-slate-100">
      <span className="h-0.5 w-3 rounded-full bg-slate-400" />
    </span>
  );
}

export function Comparison() {
  return (
    <section className="bg-white py-16 sm:py-20 lg:py-24">
      <div className="container-aw">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
            Comparison
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            他の売り方と、どう違う？
          </h2>
        </div>

        <div className="relative mt-10">
        <div className="overflow-x-auto">
          <table className="mx-auto w-full min-w-[620px] max-w-3xl border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="w-1/3 px-4 pb-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                  比較項目
                </th>
                <th className="px-4 pb-3 text-center text-sm font-semibold text-slate-500">
                  フリマで自力出品
                </th>
                <th className="px-4 pb-3 text-center text-sm font-semibold text-slate-500">
                  一括査定
                </th>
                <th className="rounded-t-2xl bg-brand-600 px-4 py-3 text-center text-sm font-bold text-white shadow-[0_-8px_24px_-8px_rgb(31_84_222/0.35)]">
                  カタヅケ
                </th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row, index) => {
                const isLast = index === ROWS.length - 1;
                return (
                  <tr key={row.label}>
                    <td className="border-t border-slate-200 px-4 py-4 text-left font-semibold text-slate-800">
                      {row.label}
                    </td>
                    <td className="border-t border-slate-200 px-4 py-4 text-center">
                      <MarkCell value={row.flea} />
                    </td>
                    <td className="border-t border-slate-200 px-4 py-4 text-center">
                      <MarkCell value={row.bulk} />
                    </td>
                    <td
                      className={[
                        "bg-brand-50 px-4 py-4 text-center align-middle",
                        isLast ? "rounded-b-2xl" : "",
                      ].join(" ")}
                    >
                      <MarkCell value={row.sokuri} />
                      <span className="mt-1 block text-xs font-medium text-brand-700">
                        {row.note}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {/* 右端フェード: 横スクロールの続きを示唆（モバイルのみ） */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-white to-transparent sm:hidden"
        />
        </div>
      </div>
    </section>
  );
}
