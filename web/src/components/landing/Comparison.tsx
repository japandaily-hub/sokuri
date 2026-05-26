/**
 * 従来の売り方との比較表セクション（差別化提示）。
 */

import { Icon } from "@/components/Icon";

type Mark = "good" | "mid" | "bad";

const ROWS: { label: string; flea: Mark; bulk: Mark; sokuri: Mark; note: string }[] = [
  { label: "出品・入力の手間", flea: "bad", bulk: "mid", sokuri: "good", note: "写真を撮るだけ" },
  { label: "価格・相場の調査", flea: "bad", bulk: "mid", sokuri: "good", note: "AIが自動で算出" },
  { label: "連絡・営業電話", flea: "mid", bulk: "bad", sokuri: "good", note: "一斉架電なし" },
  { label: "対応カテゴリ", flea: "mid", bulk: "mid", sokuri: "good", note: "ほぼ全カテゴリ" },
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

        <div className="mt-10 overflow-x-auto">
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
                  何でも一括査定
                </th>
                <th className="rounded-t-2xl bg-brand-600 px-4 py-3 text-center text-sm font-bold text-white">
                  ソクウリ
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
      </div>
    </section>
  );
}
