'use client';

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getAssessment,
  ApiError,
  type EstimateResponse,
  type RecommendedChannel,
} from "@/lib/api";
import { formatPrice } from "@/lib/format";
import ChannelCard from "@/components/ChannelCard";
import DefectUploader from "@/components/DefectUploader";
import { Icon, Spinner } from "@/components/Icon";
import { Stepper } from "@/components/Stepper";

const SESSION_KEY_ESTIMATE = "aw_estimate_result";

type LoadState = "loading" | "loaded" | "error";

/** sessionStorage から EstimateResponse を読み出す */
function readFromSession(): EstimateResponse | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY_ESTIMATE);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed === null ||
      typeof parsed !== "object" ||
      !("assessment_id" in parsed) ||
      !("estimated_price" in parsed) ||
      !("recommendations" in parsed)
    ) {
      return null;
    }
    return parsed as EstimateResponse;
  } catch {
    return null;
  }
}

function sortByRank(channels: RecommendedChannel[]): RecommendedChannel[] {
  return [...channels].sort((a, b) => a.rank - b.rank);
}

function ResultContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const assessmentId = searchParams.get("assessment_id") ?? "";

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [assessment, setAssessment] = useState<EstimateResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    // 1. sessionStorage に結果があれば即時表示
    const cached = readFromSession();
    if (cached) {
      sessionStorage.removeItem(SESSION_KEY_ESTIMATE);
      setAssessment(cached);
      setLoadState("loaded");
      return;
    }

    // 2. sessionStorage になければ assessment_id で API フォールバック
    if (!assessmentId) {
      setErrorMessage("査定 ID が見つかりません。最初からやり直してください。");
      setLoadState("error");
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const data = await getAssessment(assessmentId);
        if (!cancelled) {
          setAssessment(data);
          setLoadState("loaded");
        }
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof ApiError
              ? `エラー (${err.status}): ${err.message}`
              : "査定結果の取得に失敗しました。";
          setErrorMessage(message);
          setLoadState("error");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [assessmentId]);

  // --- ローディング ---
  if (loadState === "loading") {
    return (
      <div className="flex flex-col items-center gap-4 rounded-2xl border border-slate-200 bg-white py-16 shadow-card">
        <Spinner className="h-9 w-9 text-brand-500" />
        <p className="text-sm text-slate-500">査定結果を取得しています…</p>
      </div>
    );
  }

  // --- エラー ---
  if (loadState === "error" || !assessment) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-card">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-red-50 text-red-500">
          <Icon name="alert" className="h-6 w-6" />
        </span>
        <p className="mt-4 text-sm text-slate-600">{errorMessage}</p>
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

  // --- 結果表示 ---
  const sortedChannels = sortByRank(assessment.recommendations);

  return (
    <div className="flex flex-col gap-6">
      {/* タイトル */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-slate-900">査定結果</h1>
        <p className="mt-1 text-sm text-slate-500">
          推定相場と、おすすめの売却チャネルをご確認ください。
        </p>
      </div>

      {/* 推定価格カード */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-brand-700 to-brand-950 p-6 shadow-elevated">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-full bg-brand-400/25 blur-3xl"
        />
        <div className="relative">
          <p className="flex items-center gap-1.5 text-sm font-medium text-brand-100">
            <Icon name="yen" className="h-4 w-4" />
            推定相場
          </p>
          <p className="mt-1 text-4xl font-bold tracking-tight tabular-nums text-white">
            {formatPrice(assessment.estimated_price)}
          </p>
          <p className="mt-2.5 text-xs leading-relaxed text-brand-200">
            ※ 相場は市場状況により変動します。AIによる参考値としてご利用ください。
          </p>
        </div>
      </div>

      {/* 瑕疵アップロード（必要な場合） */}
      {assessment.defect_evidence_required && (
        <DefectUploader assessmentId={assessment.assessment_id} />
      )}

      {/* 推奨チャネル */}
      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-base font-bold text-slate-900">おすすめの売却チャネル</h2>
          {sortedChannels.length > 0 && (
            <span className="text-xs text-slate-400">
              {sortedChannels.length}件を提案
            </span>
          )}
        </div>
        {sortedChannels.length > 0 ? (
          <div className="flex flex-col gap-3">
            {sortedChannels.map((channel) => (
              <ChannelCard key={channel.rank} channel={channel} />
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white py-10 text-center">
            <p className="text-sm text-slate-400">推奨チャネルが見つかりませんでした。</p>
          </div>
        )}
      </section>

      {/* もう一度査定ボタン */}
      <button
        type="button"
        onClick={() => router.replace("/")}
        className="inline-flex items-center justify-center gap-2 rounded-xl border border-brand-200 bg-white px-6 py-3 text-sm font-semibold text-brand-700 transition-colors hover:bg-brand-50 active:bg-brand-100 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
      >
        <Icon name="camera" className="h-4 w-4" />
        別の商品を査定する
      </button>
    </div>
  );
}

export default function ResultPage() {
  return (
    <div className="container-aw py-8 sm:py-12">
      <div className="mx-auto max-w-xl">
        <Stepper current={2} />
        <div className="mt-8">
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-24">
                <Spinner className="h-8 w-8 text-brand-500" />
              </div>
            }
          >
            <ResultContent />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
