'use client';

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { estimatePrice, ApiError, type Condition, type EstimateResponse } from "@/lib/api";
import ConditionCard, { CONDITION_ORDER } from "@/components/ConditionCard";
import { Icon, Spinner } from "@/components/Icon";
import { Stepper } from "@/components/Stepper";

const SESSION_KEY_ESTIMATE = "aw_estimate_result";

function isCondition(value: string | null): value is Condition {
  const valid: Condition[] = ["new", "like_new", "good", "fair", "poor"];
  return value !== null && (valid as string[]).includes(value);
}

function ConditionContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const itemId = searchParams.get("item_id") ?? "";
  const name = searchParams.get("name") ?? "商品";
  const initialConditionParam = searchParams.get("condition");
  const initialCondition: Condition = isCondition(initialConditionParam)
    ? initialConditionParam
    : "good";

  const [selected, setSelected] = useState<Condition>(initialCondition);
  const [defectNote, setDefectNote] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>("");

  // ユーザー入力の傷メモは現状サーバー送信せず、sessionStorage に控えて
  // 後段の /result や業者連絡時の補足情報として活用する（Phase 3 で API 化）。
  const SESSION_KEY_DEFECT_NOTE = "aw_defect_note";

  async function handleSubmit() {
    if (!itemId) {
      setErrorMessage("item_id が見つかりません。最初からやり直してください。");
      return;
    }

    setIsLoading(true);
    setErrorMessage("");

    try {
      const result: EstimateResponse = await estimatePrice({
        item_id: itemId,
        condition: selected,
      });

      // 傷メモは現状サーバー未送信、sessionStorage に控える（Phase 3 で API 拡張時に同送）
      if (defectNote.trim()) {
        sessionStorage.setItem(SESSION_KEY_DEFECT_NOTE, defectNote.trim());
      } else {
        sessionStorage.removeItem(SESSION_KEY_DEFECT_NOTE);
      }
      // 査定結果を sessionStorage に保存してから /result へ遷移
      sessionStorage.setItem(SESSION_KEY_ESTIMATE, JSON.stringify(result));
      router.push(
        `/result?assessment_id=${encodeURIComponent(result.assessment_id)}`,
      );
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `エラー (${err.status}): ${err.message}`
          : "査定に失敗しました。もう一度お試しください。";
      setErrorMessage(message);
      setIsLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* 識別された商品 */}
      <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-100 text-accent-600">
          <Icon name="check-circle" className="h-5 w-5" strokeWidth={2} />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-400">識別された商品</p>
          <p className="truncate text-sm font-bold text-slate-900">{name}</p>
        </div>
      </div>

      {/* 見出し */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-slate-900">商品の状態を選択</h1>
        <p className="mt-1 text-sm leading-relaxed text-slate-500">
          コンディションは査定額に反映されます。実際の状態に最も近いものを選んでください。
        </p>
      </div>

      {/* コンディション選択（ラジオグループ） */}
      <div
        role="radiogroup"
        aria-label="コンディション選択"
        className="flex flex-col gap-2.5"
      >
        {CONDITION_ORDER.map((cond) => (
          <ConditionCard
            key={cond}
            condition={cond}
            selected={selected === cond}
            onSelect={setSelected}
          />
        ))}
      </div>

      {/* 傷の場所・程度メモ（任意） */}
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
        <label
          htmlFor="defect-note"
          className="flex items-center gap-1.5 text-sm font-semibold text-slate-900"
        >
          <Icon name="alert" className="h-4 w-4 text-brand-600" />
          傷・汚れの場所と程度（任意）
        </label>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          画像で見えない傷や、業者に伝えたい状態の補足を書くと査定精度が上がります。
        </p>
        <textarea
          id="defect-note"
          rows={3}
          maxLength={400}
          value={defectNote}
          onChange={(e) => setDefectNote(e.target.value)}
          placeholder="例: 画面右下に長さ 2cm の擦り傷あり / 背面ロゴ部に塗装剥がれ / 動作正常、付属品は箱と充電器あり"
          className="mt-2.5 w-full resize-none rounded-xl border border-slate-300 bg-slate-50 px-3.5 py-2.5 text-sm shadow-xs focus-visible:border-brand-500 focus-visible:bg-white focus-visible:ring-2 focus-visible:ring-brand-200"
        />
        <p className="mt-1.5 text-right text-[11px] text-slate-500">
          {defectNote.length} / 400
        </p>
      </div>

      {/* エラーメッセージ */}
      {errorMessage && (
        <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3">
          <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
          <p className="text-sm text-red-700">{errorMessage}</p>
        </div>
      )}

      {/* 査定ボタン */}
      <button
        type="button"
        disabled={isLoading}
        onClick={handleSubmit}
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand-600 px-6 py-3.5 text-base font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 active:bg-brand-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
      >
        {isLoading ? (
          <>
            <Spinner className="h-5 w-5" />
            査定中…
          </>
        ) : (
          <>
            査定する
            <Icon name="arrow-right" className="h-4 w-4" strokeWidth={2.25} />
          </>
        )}
      </button>
    </div>
  );
}

export default function ConditionPage() {
  return (
    <div className="container-aw py-8 sm:py-12">
      <div className="mx-auto max-w-xl">
        <Stepper current={1} />
        <div className="mt-8">
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-24">
                <Spinner className="h-8 w-8 text-brand-500" />
              </div>
            }
          >
            <ConditionContent />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
