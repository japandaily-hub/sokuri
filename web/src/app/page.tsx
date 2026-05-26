'use client';

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { analyzeImage, ApiError, type AnalyzeResponse } from "@/lib/api";
import { fileToBase64 } from "@/lib/format";
import { Icon, Spinner, type IconName } from "@/components/Icon";
import { ServiceIntro } from "@/components/landing/ServiceIntro";
import { Features } from "@/components/landing/Features";
import { Comparison } from "@/components/landing/Comparison";
import { Faq } from "@/components/landing/Faq";

type PageState = "idle" | "loading" | "error";

const SESSION_KEY_ANALYZE = "aw_analyze_result";

// ===== カテゴリ定義 =====
const CATEGORIES: { icon: IconName; label: string; sub: string }[] = [
  { icon: "device", label: "家電・デジタル", sub: "スマホ・PC・カメラ" },
  { icon: "apparel", label: "ファッション", sub: "衣類・シューズ・帽子" },
  { icon: "bag", label: "ブランド品", sub: "バッグ・財布・小物" },
  { icon: "gem", label: "時計・貴金属", sub: "腕時計・指輪・ネックレス" },
  { icon: "gamepad", label: "ゲーム・おもちゃ", sub: "ゲーム機・フィギュア" },
  { icon: "music", label: "楽器", sub: "ギター・鍵盤・管楽器" },
  { icon: "book", label: "本・コミック", sub: "書籍・漫画・雑誌" },
  { icon: "sport", label: "スポーツ・アウトドア", sub: "用具・ウェア・自転車" },
  { icon: "sofa", label: "家具・インテリア", sub: "テーブル・チェア・照明" },
  { icon: "beauty", label: "美容・コスメ", sub: "スキンケア・メイク" },
  { icon: "art", label: "アート・コレクション", sub: "絵画・切手・コイン" },
  { icon: "car", label: "カー用品", sub: "パーツ・カーナビ・タイヤ" },
];

// ===== 対応チャネル定義 =====
const CHANNELS: { name: string; desc: string }[] = [
  { name: "メルカリ", desc: "個人間売買 No.1" },
  { name: "ヤフオク", desc: "オークション最大手" },
  { name: "PayPayフリマ", desc: "即時買取に対応" },
  { name: "ラクマ", desc: "手数料が最安水準" },
  { name: "ブックオフ", desc: "本・CD・ゲーム専門" },
  { name: "セカンドストリート", desc: "ブランド・古着に強い" },
  { name: "ハードオフ", desc: "家電・楽器専門" },
  { name: "トレジャーファクトリー", desc: "総合リサイクル" },
];

// ===== 利用手順 =====
const STEPS: { step: string; icon: IconName; title: string; desc: string }[] = [
  {
    step: "01",
    icon: "camera",
    title: "写真を撮る",
    desc: "商品の写真を1枚撮影するか、既存の画像をアップロードするだけ。",
  },
  {
    step: "02",
    icon: "scan",
    title: "AIが商品を識別",
    desc: "AIが商品名・カテゴリ・コンディションを自動で判定します。",
  },
  {
    step: "03",
    icon: "yen",
    title: "最高値チャネルを確認",
    desc: "メルカリ・ヤフオク・買取店など複数チャネルの査定額を比較。",
  },
];

// ===== ヒーローの信頼シグナル =====
const TRUST_CHIPS = ["完全無料", "登録不要", "30秒で査定完了", "全カテゴリ対応"];

export default function HomePage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [pageState, setPageState] = useState<PageState>("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    if (!file) return;
    setSelectedFile(file);
    setErrorMessage("");
    setPageState("idle");
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
  }

  function clearSelectedFile() {
    setSelectedFile(null);
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return "";
    });
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleSubmit() {
    if (!selectedFile) return;
    setPageState("loading");
    setErrorMessage("");
    try {
      const base64 = await fileToBase64(selectedFile);
      const result: AnalyzeResponse = await analyzeImage({
        image: base64,
        mime_type: selectedFile.type || "image/jpeg",
      });
      sessionStorage.setItem(SESSION_KEY_ANALYZE, JSON.stringify(result));
      router.push(`/analyzing?item_id=${encodeURIComponent(result.item_id)}`);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `エラー (${err.status}): ${err.message}`
          : "解析に失敗しました。もう一度お試しください。";
      setErrorMessage(message);
      setPageState("error");
    }
  }

  const isLoading = pageState === "loading";

  return (
    <div>
      {/* ============================================================
          HERO — アップロードエリア
      ============================================================ */}
      <section className="hero-surface">
        <div className="container-aw grid items-center gap-10 py-14 lg:grid-cols-2 lg:gap-14 lg:py-20">
          {/* 左: キャッチコピー */}
          <div className="animate-fade-up">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">
              <Icon name="sparkle" className="h-3.5 w-3.5" />
              AI査定 × リユース
            </span>

            <h1 className="mt-5 text-[2rem] font-bold leading-[1.18] tracking-tight text-slate-900 sm:text-[2.75rem]">
              写真1枚で、
              <br />
              <span className="text-brand-600">最高値</span>で売ろう。
            </h1>

            <p className="mt-5 max-w-md text-base leading-relaxed text-slate-600">
              AIが商品を自動で識別し、メルカリ・ヤフオク・買取店など、
              最適な売却チャネルと査定額を<strong className="font-semibold text-slate-900">即時に提案</strong>します。
            </p>

            <ul className="mt-6 flex flex-wrap gap-2">
              {TRUST_CHIPS.map((chip) => (
                <li
                  key={chip}
                  className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-xs ring-1 ring-slate-200"
                >
                  <Icon name="check" className="h-3.5 w-3.5 text-accent-600" strokeWidth={2.5} />
                  {chip}
                </li>
              ))}
            </ul>
          </div>

          {/* 右: アップロードカード */}
          <div className="animate-fade-up rounded-2xl border border-slate-200/70 bg-white p-5 shadow-elevated sm:p-6 [animation-delay:120ms]">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <Icon name="camera" className="h-5 w-5" />
              </span>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-brand-600">
                  Step 1
                </p>
                <h2 className="text-sm font-bold text-slate-900">写真をアップロードして査定開始</h2>
              </div>
            </div>

            {/* アップロードエリア */}
            <div className="mt-4">
              {previewUrl ? (
                <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-900">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={previewUrl}
                    alt="選択した商品画像"
                    className="mx-auto max-h-60 w-full object-contain"
                  />
                  <button
                    type="button"
                    onClick={clearSelectedFile}
                    className="absolute right-2.5 top-2.5 rounded-full bg-slate-900/70 p-2 text-white backdrop-blur-sm transition-colors hover:bg-slate-900 focus-visible:ring-2 focus-visible:ring-white"
                    aria-label="画像を削除"
                  >
                    <Icon name="close" className="h-4 w-4" strokeWidth={2.5} />
                  </button>
                </div>
              ) : (
                <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 px-6 py-9 text-center transition-colors hover:border-brand-400 hover:bg-brand-50/50">
                  <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-white text-brand-500 shadow-xs ring-1 ring-slate-200">
                    <Icon name="image" className="h-6 w-6" />
                  </span>
                  <span className="mt-3 text-sm font-semibold text-slate-800">
                    写真を撮影 / ファイルを選択
                  </span>
                  <span className="mt-1 text-xs text-slate-400">JPEG / PNG / WebP に対応</span>
                  <input
                    ref={inputRef}
                    type="file"
                    accept="image/*"
                    capture="environment"
                    className="sr-only"
                    onChange={handleFileChange}
                  />
                </label>
              )}
            </div>

            {/* エラー */}
            {pageState === "error" && (
              <div className="mt-3 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3">
                <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                <p className="text-sm text-red-700">{errorMessage}</p>
              </div>
            )}

            {/* 査定ボタン */}
            <button
              type="button"
              disabled={!selectedFile || isLoading}
              onClick={handleSubmit}
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-6 py-3.5 text-base font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 active:bg-brand-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
            >
              {isLoading ? (
                <>
                  <Spinner className="h-5 w-5" />
                  解析中…
                </>
              ) : (
                <>
                  査定する
                  <Icon name="arrow-right" className="h-4 w-4" strokeWidth={2.25} />
                </>
              )}
            </button>

            <p className="mt-3 flex items-center justify-center gap-1.5 text-center text-xs text-slate-400">
              <Icon name="lock" className="h-3.5 w-3.5" />
              登録不要・無料。明るい場所で商品全体を撮ると精度が上がります。
            </p>
          </div>
        </div>
      </section>

      {/* ===== サービス紹介・特徴・比較 ===== */}
      <ServiceIntro />
      <Features />
      <Comparison />

      {/* ============================================================
          CATEGORY SECTION
      ============================================================ */}
      <section id="categories" className="bg-slate-50 py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
              Categories
            </p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              ほぼ全カテゴリに対応
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-500">
              気になるカテゴリを選んで、そのまま写真をアップロード。家電からブランド品まで幅広く査定できます。
            </p>
          </div>

          <div className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {CATEGORIES.map(({ icon, label, sub }) => (
              <button
                key={label}
                type="button"
                onClick={() => inputRef.current?.click()}
                className="group flex items-center gap-3.5 rounded-2xl border border-slate-200 bg-white p-4 text-left transition-all hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-card focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
              >
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition-colors group-hover:bg-brand-100">
                  <Icon name={icon} className="h-6 w-6" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-slate-900">
                    {label}
                  </span>
                  <span className="block truncate text-xs text-slate-400">{sub}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================================
          HOW IT WORKS
      ============================================================ */}
      <section id="how-it-works" className="bg-white py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
              How it works
            </p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              かんたん3ステップで査定完了
            </h2>
            <p className="mt-3 text-sm text-slate-500">
              登録不要・完全無料。スマホで撮ってすぐ査定できます。
            </p>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-3">
            {STEPS.map(({ step, icon, title, desc }, index) => (
              <div
                key={step}
                className="relative rounded-2xl border border-slate-200 bg-white p-6 shadow-card"
              >
                {/* ステップ間のコネクタ（PC表示のみ） */}
                {index < STEPS.length - 1 && (
                  <span
                    aria-hidden="true"
                    className="absolute right-0 top-12 hidden h-px w-5 translate-x-full bg-slate-200 sm:block"
                  />
                )}
                <div className="flex items-center gap-3">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white">
                    <Icon name={icon} className="h-6 w-6" />
                  </span>
                  <span className="text-3xl font-bold tracking-tight text-slate-200">{step}</span>
                </div>
                <h3 className="mt-4 text-base font-bold text-slate-900">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================================
          CHANNELS
      ============================================================ */}
      <section id="channels" className="bg-slate-50 py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-600">
              Channels
            </p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              対応売却チャネル一覧
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-500">
              複数チャネルの査定額を一括で比較し、最も高く売れる場所を選べます。
            </p>
          </div>

          <div className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {CHANNELS.map(({ name, desc }) => (
              <div
                key={name}
                className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-sm font-bold text-brand-700 ring-1 ring-brand-100">
                  {name.charAt(0)}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-slate-900">{name}</span>
                  <span className="block truncate text-xs text-slate-400">{desc}</span>
                </span>
              </div>
            ))}
          </div>

          <p className="mt-6 text-center text-xs text-slate-400">
            ※ チャネルの提案には広告（PR）を含む場合があります。査定額はAIによる参考値です。
          </p>
        </div>
      </section>

      {/* ===== FAQ ===== */}
      <Faq />

      {/* ============================================================
          CTA BANNER
      ============================================================ */}
      <section className="bg-white py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-brand-800 to-brand-950 px-6 py-14 text-center sm:px-12">
            {/* 装飾光彩 */}
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-brand-500/30 blur-3xl"
            />
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -bottom-24 -left-16 h-56 w-56 rounded-full bg-brand-400/20 blur-3xl"
            />
            <div className="relative">
              <h2 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
                まずは1枚、写真を撮ってみよう
              </h2>
              <p className="mt-3 text-sm text-brand-100 sm:text-base">
                登録不要・完全無料。最短30秒で査定結果が出ます。
              </p>
              <button
                type="button"
                onClick={() => {
                  window.scrollTo({ top: 0, behavior: "smooth" });
                  setTimeout(() => inputRef.current?.click(), 500);
                }}
                className="mt-7 inline-flex items-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-brand-700 shadow-lg transition-transform hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-brand-900"
              >
                <Icon name="camera" className="h-5 w-5" />
                今すぐ無料で査定する
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
