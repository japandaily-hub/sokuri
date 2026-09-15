"use client";

/**
 * 50件ページング共通部品。前へ／次へボタン＋総件数表示。
 * total が null の場合（backend が total を返さない一覧向け）は「全X件中」を出さず
 * 「表示中 N〜M件」のみ表示し、次へボタンの活性判定は取得件数が limit に達しているか
 * （＝次ページが存在しうるか）で代用する（r4監査 ADD-H1 対応）。
 *
 * 契約: フェッチ失敗（error state セット中）は呼び出し側がこのコンポーネント自体を描画しない
 * こと。本コンポーネントは常に itemCount===0 を「正常系の0件」として表示するため、エラー時に
 * そのまま渡すと通信エラーと実際の0件が文言上区別できなくなる（design-audit-admin-static 指摘）。
 */
export function AdminPagination({
  total,
  limit,
  offset,
  itemCount,
  onPrev,
  onNext,
}: {
  total: number | null;
  limit: number;
  offset: number;
  itemCount: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const from = itemCount === 0 ? 0 : offset + 1;
  // r4-fix-frontend2 M5 是正: itemCount===0 のとき offset+itemCount では offset がそのまま
  // 出てしまい「0件」なのに「100〜100件」等と誤表示していた。0件時は必ず0にする。
  const to = itemCount === 0 ? 0 : offset + itemCount;
  const nextDisabled = total !== null ? offset + limit >= total : itemCount < limit;
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-500">
      <p>
        {itemCount === 0
          ? total !== null
            ? `全${total.toLocaleString("ja-JP")}件中 表示中 0件`
            : "表示中 0件"
          : total !== null
            ? `全${total.toLocaleString("ja-JP")}件中 ${from.toLocaleString("ja-JP")}〜${to.toLocaleString("ja-JP")}件を表示`
            : `表示中 ${from.toLocaleString("ja-JP")}〜${to.toLocaleString("ja-JP")}件`}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={offset === 0}
          className="inline-flex items-center justify-center gap-1.5 rounded-none border border-kdz-line bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          前へ
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={nextDisabled}
          className="inline-flex items-center justify-center gap-1.5 rounded-none border border-kdz-line bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          次へ
        </button>
      </div>
    </div>
  );
}
