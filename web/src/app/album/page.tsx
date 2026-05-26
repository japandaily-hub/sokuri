"use client";

/**
 * /album — 一括査定アルバム作成画面（Phase 1）
 *
 * ADR (Architecture Decision Record / 暫定):
 *   - 既存 /api/v1/analyze と /api/v1/estimate を N 回呼ぶだけ。バックエンド改修ゼロ。
 *   - アイテム状態は client-side のみ管理（DB 永続化は Phase 2）。
 *   - 各アイテムは初期コンディション "good" 固定（個別調整は Phase 3）。
 *   - 完了時に /album/submitted へ遷移し、メール取得（Wizard of Oz リード化）。
 *
 * 差別化軸:
 *   - 業者は匿名（ユーザー名/連絡先は業者へ非開示）
 *   - 営業電話ゼロ（成約決定後のみ連絡先開示）
 *   - 「家まるごと」を 1 アルバムに束ね、業者の出張採算を担保
 */

import { useCallback, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  analyzeImage,
  estimatePrice,
  ApiError,
  type Condition,
} from "@/lib/api";
import { fileToBase64 } from "@/lib/format";
import { Icon, Spinner } from "@/components/Icon";

/**
 * アルバム内 1 アイテムの状態機械:
 *   uploading → analyzing → estimating → ready | error
 */
type ItemStatus = "uploading" | "analyzing" | "estimating" | "ready" | "error";

interface AlbumItem {
  /** UI 内一意 ID（ファイル選択ごとに採番） */
  localId: string;
  /** プレビュー用 ObjectURL */
  previewUrl: string;
  /** ファイル名（表示用） */
  fileName: string;
  /** 状態機械 */
  status: ItemStatus;
  /** バックエンド item_id（analyze 成功後） */
  itemId?: string;
  /** バックエンド assessment_id（estimate 成功後、POST /albums で使用） */
  assessmentId?: string;
  /** AI 識別商品名 */
  detectedName?: string;
  /** AI 推定コンディション */
  condition?: Condition;
  /** 見積もり額（円） */
  estimatedPrice?: number;
  /** エラーメッセージ */
  errorMessage?: string;
}

const SESSION_KEY_ALBUM = "aw_album_v1";

/** 円フォーマット */
const yen = (n: number) =>
  new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    maximumFractionDigits: 0,
  }).format(n);

/** Condition ラベル */
const CONDITION_LABEL: Record<Condition, string> = {
  new: "新品",
  like_new: "美品",
  good: "良好",
  fair: "可",
  poor: "難あり",
};

export default function AlbumPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const uid = useId();

  const [items, setItems] = useState<AlbumItem[]>([]);
  const [submitting, setSubmitting] = useState(false);

  // -------------------------------------------------------------------
  // 1 アイテムの解析パイプライン: analyze → estimate（並列対応）
  // -------------------------------------------------------------------
  const processOne = useCallback(async (item: AlbumItem, file: File) => {
    /** state を partial 更新するヘルパー */
    const patch = (changes: Partial<AlbumItem>) =>
      setItems((prev) =>
        prev.map((it) => (it.localId === item.localId ? { ...it, ...changes } : it)),
      );

    try {
      patch({ status: "analyzing" });
      const b64 = await fileToBase64(file);
      const analyzed = await analyzeImage({
        image: b64,
        mime_type: file.type || "image/jpeg",
      });

      patch({
        status: "estimating",
        itemId: analyzed.item_id,
        detectedName: analyzed.detected_name,
        condition: analyzed.initial_condition,
      });

      const estimated = await estimatePrice({
        item_id: analyzed.item_id,
        condition: analyzed.initial_condition,
      });

      patch({
        status: "ready",
        assessmentId: estimated.assessment_id,
        estimatedPrice: estimated.estimated_price,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `エラー (${err.status})`
          : "解析に失敗しました";
      patch({ status: "error", errorMessage: message });
    }
  }, []);

  // -------------------------------------------------------------------
  // ファイル選択ハンドラ（複数枚同時）
  // -------------------------------------------------------------------
  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      const fileArray = Array.from(files);
      if (fileArray.length === 0) return;

      const newItems: AlbumItem[] = fileArray.map((file, i) => ({
        localId: `${uid}-${Date.now()}-${i}`,
        previewUrl: URL.createObjectURL(file),
        fileName: file.name,
        status: "uploading",
      }));

      setItems((prev) => [...prev, ...newItems]);

      // 並列解析（同時実行数を絞らない — 数十枚規模を想定）
      newItems.forEach((item, i) => {
        const file = fileArray[i];
        if (file) processOne(item, file);
      });

      if (inputRef.current) inputRef.current.value = "";
    },
    [processOne, uid],
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) handleFiles(e.target.files);
  };

  /** 1 アイテム削除 */
  const removeItem = (localId: string) => {
    setItems((prev) => {
      const target = prev.find((it) => it.localId === localId);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((it) => it.localId !== localId);
    });
  };

  // -------------------------------------------------------------------
  // 派生値
  // -------------------------------------------------------------------
  const totalCount = items.length;
  const readyCount = items.filter((it) => it.status === "ready").length;
  const processingCount = items.filter(
    (it) => it.status === "analyzing" || it.status === "estimating" || it.status === "uploading",
  ).length;
  const errorCount = items.filter((it) => it.status === "error").length;
  const totalEstimate = items
    .filter((it) => it.status === "ready" && typeof it.estimatedPrice === "number")
    .reduce((sum, it) => sum + (it.estimatedPrice ?? 0), 0);
  const canSubmit = readyCount > 0 && processingCount === 0 && !submitting;

  // -------------------------------------------------------------------
  // 業者への一括査定依頼（Phase 2 placeholder — sessionStorage 保存して遷移）
  // -------------------------------------------------------------------
  const handleSubmit = () => {
    if (!canSubmit) return;
    setSubmitting(true);
    const payload = items
      .filter((it) => it.status === "ready" && it.assessmentId)
      .map((it) => ({
        assessment_id: it.assessmentId!,
        item_id: it.itemId,
        detected_name: it.detectedName,
        condition: it.condition,
        estimated_price: it.estimatedPrice,
      }));
    sessionStorage.setItem(
      SESSION_KEY_ALBUM,
      JSON.stringify({ items: payload, total: totalEstimate, count: payload.length }),
    );
    router.push("/album/submitted");
  };

  return (
    <div className="bg-slate-50 pb-32">
      {/* ============================================================
          HERO（簡易）— ページ内紹介
      ============================================================ */}
      <section className="hero-surface">
        <div className="container-aw py-10 sm:py-14">
          <div className="mx-auto max-w-2xl text-center">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">
              <Icon name="sparkle" className="h-3.5 w-3.5" />
              一括査定 × 匿名入札
            </span>
            <h1 className="mt-4 text-[1.75rem] font-bold leading-[1.2] tracking-tight text-slate-900 sm:text-[2.25rem]">
              家中の不用品をまとめて、
              <br className="sm:hidden" />
              <span className="text-brand-600">最高額の業者</span>を選ぶ。
            </h1>
            <p className="mx-auto mt-4 max-w-md text-sm leading-relaxed text-slate-600 sm:text-base">
              写真を撮るだけ。AIが識別した不用品をアルバム化し、提携業者が
              <strong className="font-semibold text-slate-900">匿名で一括入札</strong>。
              成約を決めるまで業者にあなたの連絡先は伝わりません。
            </p>
            <ul className="mt-5 flex flex-wrap justify-center gap-2">
              {["匿名入札", "営業電話ゼロ", "出張費込み比較", "決定するまで連絡先非開示"].map(
                (chip) => (
                  <li
                    key={chip}
                    className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-xs ring-1 ring-slate-200"
                  >
                    <Icon name="check" className="h-3.5 w-3.5 text-accent-600" strokeWidth={2.5} />
                    {chip}
                  </li>
                ),
              )}
            </ul>
          </div>
        </div>
      </section>

      {/* ============================================================
          UPLOAD AREA
      ============================================================ */}
      <section className="container-aw mt-8">
        <label className="block">
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            multiple
            capture="environment"
            className="sr-only"
            onChange={handleInputChange}
          />
          <div className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-brand-300 bg-white px-6 py-10 text-center transition-colors hover:border-brand-500 hover:bg-brand-50/50">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
              <Icon name="camera" className="h-7 w-7" />
            </span>
            <span className="mt-2 text-base font-bold text-slate-900">
              {totalCount === 0 ? "写真をまとめて選択" : "さらに写真を追加"}
            </span>
            <span className="text-xs text-slate-500">
              複数枚同時選択可・連続撮影可・1 枚あたり最大 10MB
            </span>
          </div>
        </label>
      </section>

      {/* ============================================================
          ITEM GALLERY
      ============================================================ */}
      {totalCount > 0 && (
        <section className="container-aw mt-8">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-bold tracking-tight text-slate-900">
              アルバム
              <span className="ml-2 text-sm font-medium text-slate-500">
                {totalCount} 点（解析済み {readyCount} 点
                {processingCount > 0 && ` / 解析中 ${processingCount} 点`}
                {errorCount > 0 && ` / エラー ${errorCount} 点`}）
              </span>
            </h2>
          </div>

          <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((item) => (
              <li
                key={item.localId}
                className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card"
              >
                {/* 画像 */}
                <div className="relative aspect-[4/3] bg-slate-100">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={item.previewUrl}
                    alt={item.detectedName || item.fileName}
                    className="h-full w-full object-cover"
                  />
                  <button
                    type="button"
                    onClick={() => removeItem(item.localId)}
                    className="absolute right-2 top-2 rounded-full bg-slate-900/70 p-1.5 text-white backdrop-blur-sm transition-colors hover:bg-slate-900 focus-visible:ring-2 focus-visible:ring-white"
                    aria-label={`${item.detectedName || item.fileName} を削除`}
                  >
                    <Icon name="close" className="h-3.5 w-3.5" strokeWidth={2.5} />
                  </button>
                </div>

                {/* メタ情報 */}
                <div className="px-4 py-3">
                  {item.status === "ready" && (
                    <>
                      <p className="line-clamp-1 text-sm font-semibold text-slate-900">
                        {item.detectedName ?? "（未識別）"}
                      </p>
                      <div className="mt-1.5 flex items-center justify-between gap-2">
                        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                          {item.condition ? CONDITION_LABEL[item.condition] : "—"}
                        </span>
                        <span className="text-sm font-bold tracking-tight text-brand-700">
                          {typeof item.estimatedPrice === "number" ? yen(item.estimatedPrice) : "—"}
                        </span>
                      </div>
                    </>
                  )}

                  {item.status !== "ready" && item.status !== "error" && (
                    <p className="flex items-center gap-2 text-sm text-slate-600">
                      <Spinner className="h-4 w-4" />
                      {item.status === "uploading" && "アップロード準備中…"}
                      {item.status === "analyzing" && "AI が識別中…"}
                      {item.status === "estimating" && "見積もり計算中…"}
                    </p>
                  )}

                  {item.status === "error" && (
                    <p
                      role="alert"
                      className="flex items-center gap-2 text-sm text-red-600"
                    >
                      <Icon name="alert" className="h-4 w-4" />
                      {item.errorMessage ?? "解析に失敗"}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ============================================================
          EMPTY STATE GUIDE（最初の 1 枚を撮るまで）
      ============================================================ */}
      {totalCount === 0 && (
        <section className="container-aw mt-8">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card sm:p-8">
            <h3 className="text-base font-bold text-slate-900">使い方</h3>
            <ol className="mt-3 space-y-2 text-sm leading-relaxed text-slate-600">
              <li>
                <strong className="font-semibold text-slate-800">1.</strong> 不用品を 1 つずつ撮影
                （ピントが合った写真ほど査定精度が上がります）
              </li>
              <li>
                <strong className="font-semibold text-slate-800">2.</strong> 上のエリアで
                <strong className="font-semibold text-slate-800">複数枚を同時選択</strong>
                （iPhone / Android ともに対応）
              </li>
              <li>
                <strong className="font-semibold text-slate-800">3.</strong>{" "}
                AIが商品を識別後、業者へ匿名一括査定を依頼
              </li>
            </ol>
            <p className="mt-4 text-xs text-slate-500">
              ※ 1 点だけ査定したい方は
              <Link href="/" className="font-semibold text-brand-700 underline-offset-2 hover:underline">
                単品査定モード
              </Link>
              をご利用ください。
            </p>
          </div>
        </section>
      )}

      {/* ============================================================
          STICKY FOOTER — 合計と CTA
      ============================================================ */}
      {totalCount > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 backdrop-blur-md">
          <div className="container-aw flex items-center justify-between gap-4 py-3 sm:py-4">
            <div>
              <p className="text-[11px] font-medium text-slate-500">
                合計査定額（AI 試算）
              </p>
              <p className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
                {yen(totalEstimate)}
              </p>
            </div>
            <button
              type="button"
              disabled={!canSubmit}
              onClick={handleSubmit}
              className="inline-flex items-center gap-1.5 rounded-xl bg-brand-600 px-5 py-3 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 active:bg-brand-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none sm:text-base"
            >
              {submitting ? (
                <>
                  <Spinner className="h-4 w-4" />
                  送信中…
                </>
              ) : (
                <>
                  業者に匿名で一括査定依頼
                  <Icon name="arrow-right" className="h-4 w-4" strokeWidth={2.25} />
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
