'use client';

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { AnalyzeResponse, Condition } from "@/lib/api";
import { Icon, Spinner } from "@/components/Icon";
import { Stepper } from "@/components/Stepper";

const SESSION_KEY_ANALYZE = "aw_analyze_result";

/**
 * 解析結果の型ガード
 */
function isAnalyzeResponse(value: unknown): value is AnalyzeResponse {
  if (value === null || typeof value !== "object") return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.item_id === "string" &&
    typeof obj.detected_name === "string" &&
    typeof obj.initial_condition === "string" &&
    typeof obj.category_tier === "string"
  );
}

const VALID_CONDITIONS: Condition[] = [
  "new",
  "like_new",
  "good",
  "fair",
  "poor",
];

function isCondition(value: string): value is Condition {
  return (VALID_CONDITIONS as string[]).includes(value);
}

function AnalyzingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const itemId = searchParams.get("item_id") ?? "";

  const [detectedName, setDetectedName] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    // sessionStorage から解析結果を読み出す
    const raw = sessionStorage.getItem(SESSION_KEY_ANALYZE);
    if (!raw) {
      setError("解析データが見つかりません。最初からやり直してください。");
      return;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      setError("データの読み込みに失敗しました。最初からやり直してください。");
      return;
    }

    if (!isAnalyzeResponse(parsed)) {
      setError("データ形式が不正です。最初からやり直してください。");
      return;
    }

    setDetectedName(parsed.detected_name);

    const condition: Condition = isCondition(parsed.initial_condition)
      ? parsed.initial_condition
      : "good";

    // 演出のため 1.5 秒待ってからコンディション選択へ
    const timer = setTimeout(() => {
      sessionStorage.removeItem(SESSION_KEY_ANALYZE);
      const params = new URLSearchParams({
        item_id: parsed.item_id,
        name: parsed.detected_name,
        condition,
        category_tier: parsed.category_tier,
      });
      router.replace(`/condition?${params.toString()}`);
    }, 1500);

    return () => clearTimeout(timer);
  }, [router, itemId]);

  // --- エラー ---
  if (error) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-card">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-red-50 text-red-500">
          <Icon name="alert" className="h-6 w-6" />
        </span>
        <p className="mt-4 text-sm text-slate-600">{error}</p>
        <button
          type="button"
          onClick={() => router.replace("/")}
          className="mt-5 inline-flex items-center gap-1.5 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
        >
          <Icon name="arrow-left" className="h-4 w-4" strokeWidth={2.25} />
          トップに戻る
        </button>
      </div>
    );
  }

  // --- 解析中 ---
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-card sm:p-10">
      {/* スキャンビジュアル */}
      <div className="relative mx-auto h-24 w-24">
        <span className="absolute inset-0 animate-ping rounded-2xl bg-brand-200 opacity-60" />
        <span className="absolute inset-2 animate-ping rounded-2xl bg-brand-300 opacity-40 [animation-delay:300ms]" />
        <div className="relative flex h-24 w-24 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-800 shadow-cta">
          <Icon name="scan" className="h-11 w-11 text-white" />
        </div>
      </div>

      <h1 className="mt-7 text-lg font-bold text-slate-900">AIが商品を解析しています</h1>
      {detectedName ? (
        <p className="mt-2 text-sm text-slate-500">
          <span className="inline-flex rounded-full bg-brand-50 px-2.5 py-0.5 font-semibold text-brand-700">
            {detectedName}
          </span>{" "}
          を識別しました
        </p>
      ) : (
        <p className="mt-2 text-sm text-slate-500">商品名・カテゴリ・状態を判定中…</p>
      )}

      {/* 進行ドット */}
      <div className="mt-6 flex justify-center gap-1.5" aria-hidden="true">
        <span className="h-2 w-2 animate-bounce rounded-full bg-brand-400" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-brand-500 [animation-delay:150ms]" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-brand-600 [animation-delay:300ms]" />
      </div>
    </div>
  );
}

export default function AnalyzingPage() {
  return (
    <div className="container-aw py-8 sm:py-12">
      <div className="mx-auto max-w-xl">
        <Stepper current={0} />
        <div className="mt-8">
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-24">
                <Spinner className="h-8 w-8 text-brand-500" />
              </div>
            }
          >
            <AnalyzingContent />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
