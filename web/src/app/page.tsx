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

// ===== 利用イメージの物語（8場面ジャーニー） =====
// 「片付けたいなあ」→ すっきり、への変化軸。phase 0:痛み / 1:手軽さ / 2:満足。
// 各場面に生成イラスト（/img/story-01.png … story-08.png）を配置。未生成でも崩れないよう onError でフォールバック。
const STORY: {
  no: string;
  title: string;
  desc: string;
  emo: string;
  phase: 0 | 1 | 2;
  alt: string;
}[] = [
  {
    no: "01",
    title: "「家を片付けたいなあ…」",
    desc: "散らかった部屋を前に、ひと息。何から手をつけるか決まらない、その状態が出発点です。",
    emo: "痛みの起点",
    phase: 0,
    alt: "散らかった部屋を前に、片付けに踏み出せず立ちすくむ女性",
  },
  {
    no: "02",
    title: "気になる品物を1点ずつ撮影",
    desc: "売りたい物を1点ずつ、スマホで撮るだけ。きれいに並べる必要はありません。撮った品物はアルバムにたまっていきます。",
    emo: "手軽さ",
    phase: 1,
    alt: "ソファに座り、不用品を1点ずつスマートフォンで撮影する女性",
  },
  {
    no: "03",
    title: "AIが1点ずつ品目・状態・相場を仮査定",
    desc: "写真からAIが品目と状態を読み取り、相場をもとに参考の仮査定額を1点ずつ提示します。",
    emo: "スピード",
    phase: 1,
    alt: "スマホ画面に品物ごとのAI仮査定額が表示されている様子",
  },
  {
    no: "04",
    title: "たまった品物をまとめて業者へ共有",
    desc: "アルバムにたまった品物を、まとめて登録業者へ共有。共有するのは「写真と品目」のみです。",
    emo: "期待",
    phase: 1,
    alt: "たまった品物のアルバムをまとめて登録業者へ共有するイメージ",
  },
  {
    no: "05",
    title: "登録業者が査定額で競う",
    desc: "複数の登録業者がオンラインで査定額を提示。競争原理がはたらき、査定が伸びやすくなります。",
    emo: "期待",
    phase: 1,
    alt: "複数の登録業者が査定額を提示し合うオンライン入札のイメージ",
  },
  {
    no: "06",
    title: "選ばれた上位3社だけが連絡",
    desc: "連絡が来るのは査定額の上位3社のみ。それ以外の業者には自動でお断りが入り、一斉架電は起こりません。",
    emo: "安心",
    phase: 2,
    alt: "ソファでくつろぎ、上位3社からの連絡をゆったり待つ女性",
  },
  {
    no: "07",
    title: "現物査定して、納得の1社を選ぶ",
    desc: "上位3社と日程を調整し、現物を確認。訪問かオンラインかは、あなたが選べます。3社を比べて、納得できる1社を選ぶだけです。",
    emo: "納得",
    phase: 2,
    alt: "玄関先で買取業者に品物を笑顔で引き渡す女性",
  },
  {
    no: "08",
    title: "家もすっきり／手間なく断捨離成功",
    desc: "片付いた部屋で、ひと安心。売れる物はまとめて一括買取、手間なく断捨離が完了します。",
    emo: "すっきり",
    phase: 2,
    alt: "片付いてすっきりした明るい部屋で、満足そうにくつろぐ女性",
  },
];

// ===== 仕組み 4ステップ =====
const STEPS: { step: string; icon: IconName; title: string; desc: string }[] = [
  {
    step: "01",
    icon: "camera",
    title: "品物を1点ずつ撮るだけ",
    desc: "売りたい物を1点ずつ撮影。AIが1点ずつ仮査定し、たまった品物をまとめて依頼します。",
  },
  {
    step: "02",
    icon: "scan",
    title: "業者から査定が届く",
    desc: "たまった品物（アルバム）を見た登録業者が査定額を提示。あなたは待つだけです。",
  },
  {
    step: "03",
    icon: "scale",
    title: "上位3社と交渉",
    desc: "査定額の上位3社が交渉権を獲得。条件を比べて選べます。",
  },
  {
    step: "04",
    icon: "check-circle",
    title: "取引・引き取り",
    desc: "いちばん条件のよい業者と取引。受け取り日時を選んで完了です。",
  },
];

// ===== 上位3社の査定オークション図解（イメージ値） =====
const AUCTION_BIDS: { name: string; amount: string; selected: boolean }[] = [
  { name: "A社", amount: "¥48,000", selected: true },
  { name: "B社", amount: "¥45,500", selected: true },
  { name: "C社", amount: "¥44,000", selected: true },
  { name: "D社", amount: "お断り連絡", selected: false },
];

// ===== 対応エリア =====
const AREAS: { name: string; desc: string }[] = [
  { name: "東京", desc: "23区を中心に対応" },
  { name: "千葉", desc: "県内主要エリアに対応" },
  { name: "埼玉", desc: "県内主要エリアに対応" },
  { name: "神奈川", desc: "県内主要エリアに対応" },
];

// ===== 安心・個人情報 =====
const SAFETY: { icon: IconName; title: string; desc: string }[] = [
  {
    icon: "lock",
    title: "情報は段階的に開示",
    desc: "査定段階で業者へ共有するのは「写真と品目」のみ。連絡先・住所は交渉が成立した業者にのみ、あなたの同意のうえで開示します。",
  },
  {
    icon: "shield",
    title: "訪問買取はクーリングオフ対象",
    desc: "訪問による買取には特定商取引法が適用されます。法定書面の交付、8日間のクーリングオフ、その期間中の物品引き渡し拒絶権など、消費者としての保護を受けられます。",
  },
  {
    icon: "close",
    title: "辞退後の再連絡はなし",
    desc: "連絡や取引を辞退した場合、その業者からの再勧誘は行われません。一斉架電のない、落ち着いたやり取りを設計しています。",
  },
];

// ===== ヒーローの信頼シグナル =====
const TRUST_CHIPS = ["撮るだけ・待つだけ", "業者登録は当面無料", "一斉架電なし", "東京・千葉・埼玉・神奈川"];

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
              不用品の買取マッチング
            </span>

            <h1 className="mt-5 text-[2.1rem] font-bold leading-[1.14] tracking-tight text-slate-900 sm:text-[2.9rem]">
              片付けたい。
              <br />
              でも、<span className="text-brand-600">動けない</span>あなたへ。
            </h1>

            <p className="mt-5 max-w-md text-base leading-relaxed text-slate-600">
              撮るだけ・待つだけ。あとは業者が査定額で競い合う。
              <strong className="font-semibold text-slate-900">競うから査定が伸びやすく</strong>、
              連絡が来るのは上位3社だけ。鳴り止まない営業電話は、もうありません。
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

            <a
              href="#line"
              className="mt-6 inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 shadow-xs transition-colors hover:border-brand-300 hover:bg-brand-50/50 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
            >
              <Icon name="external" className="h-4 w-4" />
              LINEで受付（準備中）
            </a>
          </div>

          {/* 右: 主役写真 + アップロードカード */}
          <div className="animate-fade-up [animation-delay:120ms]">
            {/* 主役写真: スマホで品物を1点ずつ撮影する女性 */}
            <div className="relative mb-5 aspect-[16/9] overflow-hidden rounded-2xl border border-slate-200/70 bg-gradient-to-br from-brand-100 via-brand-200 to-brand-400 shadow-elevated">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/img/hero.png"
                alt="明るい部屋で、不用品をスマートフォンで1点ずつ撮影する女性"
                width={1280}
                height={720}
                loading="eager"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
                className="absolute inset-0 h-full w-full object-cover"
              />
              <span
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 bg-gradient-to-t from-slate-900/55 via-slate-900/10 to-transparent"
              />
              <span className="absolute bottom-3 left-4 right-4 text-sm font-semibold leading-snug text-white drop-shadow">
                品物を1点ずつ撮るだけ。きれいに並べなくて大丈夫。
              </span>
            </div>

          {/* アップロードカード */}
          <div className="rounded-2xl border border-slate-200/70 bg-white p-5 shadow-elevated sm:p-6">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <Icon name="camera" className="h-5 w-5" />
              </span>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-brand-600">
                  Step 1
                </p>
                <h2 className="text-sm font-bold text-slate-900">品物を1点ずつ撮ってAI仮査定を依頼</h2>
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
                  <span className="mt-1 text-xs text-slate-400">
                    家電・家具・ブランド品など、品物を1点ずつアップロード
                  </span>
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
                  AI仮査定を依頼する
                  <Icon name="arrow-right" className="h-4 w-4" strokeWidth={2.25} />
                </>
              )}
            </button>

            <p className="mt-3 flex items-start gap-1.5 text-xs leading-relaxed text-slate-400">
              <Icon name="lock" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              査定段階で業者へ共有するのは「写真と品目」のみ。連絡先・住所は交渉成立後に開示します。AI仮査定はお試しいただけます。
            </p>
          </div>
          </div>
        </div>
      </section>

      {/* ============================================================
          STORY — 利用イメージの物語化（8場面ジャーニー）
      ============================================================ */}
      <section id="story" className="bg-white py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">
              変化のストーリー
            </p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              「片付けたいなあ」が、すっきりに変わるまで
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-500">
              あなたがするのは、品物を1点ずつ撮ること。AIが1点ずつ仮査定し、たまった品物をまとめて業者へ。あとは競った査定が届くのを待つだけ。痛みから、すっきりへ。8つの場面でご覧ください。
            </p>
          </div>

          {/* 感情の流れ（痛み → 手軽さ → 満足） */}
          <div
            aria-hidden="true"
            className="mx-auto mt-8 flex max-w-2xl items-center justify-between gap-2 text-xs font-medium text-slate-400"
          >
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
              痛み
            </span>
            <span className="h-px flex-1 bg-gradient-to-r from-slate-300 via-brand-300 to-accent-400" />
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-brand-400" />
              手軽さ
            </span>
            <span className="h-px flex-1 bg-gradient-to-r from-brand-300 to-accent-400" />
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-accent-500" />
              満足
            </span>
          </div>

          {/* ジャーニー: 横スクロール */}
          <div className="mt-8 flex snap-x snap-mandatory gap-4 overflow-x-auto pb-4 sm:gap-5">
            {STORY.map((scene) => {
              const ring = ["ring-slate-200", "ring-brand-200", "ring-accent-300"][scene.phase];
              const gradient = [
                "from-slate-100 via-slate-200 to-brand-100",
                "from-brand-100 via-brand-200 to-brand-300",
                "from-accent-100 via-brand-100 to-accent-200",
              ][scene.phase];
              const fallbackTint = [
                "text-slate-400",
                "text-brand-500",
                "text-accent-500",
              ][scene.phase];
              const chip = [
                "bg-slate-100 text-slate-600",
                "bg-brand-50 text-brand-700",
                "bg-accent-50 text-accent-700",
              ][scene.phase];
              return (
                <article
                  key={scene.no}
                  className={`flex w-[78vw] max-w-[19rem] shrink-0 snap-start flex-col rounded-2xl border border-slate-200 bg-white p-6 shadow-card ring-1 ring-inset ${ring} transition-shadow hover:shadow-card-hover sm:w-72`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold tabular-nums text-slate-300">
                      {scene.no}
                      <span className="text-slate-200"> / 08</span>
                    </span>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${chip}`}>
                      {scene.emo}
                    </span>
                  </div>
                  {/* 場面イラスト（生成画像）。未生成時は極薄の線画アイコンへフォールバック */}
                  <div
                    className={`relative mt-4 flex aspect-[4/3] items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br ${gradient} ${fallbackTint}`}
                  >
                    <Icon name="image" className="h-9 w-9 opacity-40" aria-hidden="true" />
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/img/story-${scene.no}.png`}
                      alt={scene.alt}
                      width={480}
                      height={360}
                      loading="lazy"
                      onError={(e) => {
                        e.currentTarget.style.display = "none";
                      }}
                      className="absolute inset-0 h-full w-full object-cover"
                    />
                  </div>
                  <h3 className="mt-5 text-base font-bold leading-snug text-slate-900">
                    {scene.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-slate-500">{scene.desc}</p>
                </article>
              );
            })}
          </div>
          <p className="mt-4 text-center text-xs text-slate-400">
            横にスクロールして続きをご覧ください
          </p>

          <p className="mx-auto mt-8 max-w-3xl text-center text-xs leading-relaxed text-slate-400">
            査定額はAIと業者による参考値です。最終的な買取額は業者の現物査定で決まります。複数の登録業者が査定額で競うため、査定が伸びやすい仕組みです。
          </p>
        </div>
      </section>

      {/* ===== 課題提起・特徴・比較 ===== */}
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
              ご利用の流れは4ステップ
            </h2>
            <p className="mt-3 text-sm text-slate-500">
              あなたがすることは、撮ることと、選ぶことだけです。
            </p>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
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
          NEGOTIATION — 上位3社の査定オークション図解
      ============================================================ */}
      <section id="nego" className="bg-slate-50 py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">
              上位3社と交渉
            </p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              査定額の上位3社が、交渉権を得る
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-500">
              登録業者が査定額を提示し、条件のよい上位3社だけがあなたへ連絡。残りの業者には自動でお断りの連絡が入ります。一斉架電は起こりません。
            </p>
          </div>

          <div className="mx-auto mt-10 max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-card sm:p-8">
            {/* あなた */}
            <div className="flex items-center justify-center">
              <div className="flex items-center gap-3 rounded-xl border border-brand-200 bg-white px-5 py-3 shadow-xs">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white">
                  <Icon name="camera" className="h-5 w-5" />
                </span>
                <span className="text-left">
                  <span className="block text-sm font-semibold text-slate-900">あなた</span>
                  <span className="block text-xs text-slate-400">1点ずつ撮って依頼</span>
                </span>
              </div>
            </div>

            <div aria-hidden="true" className="flex justify-center py-3 text-slate-300">
              <Icon name="chevron-down" className="h-6 w-6" />
            </div>

            {/* 登録業者群 */}
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="mb-3 text-center text-xs font-semibold uppercase tracking-wider text-slate-400">
                登録業者へ「写真と品目のみ」を一斉共有
              </p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {AUCTION_BIDS.map((bid) =>
                  bid.selected ? (
                    <div
                      key={bid.name}
                      className="rounded-lg border-2 border-accent-500 bg-accent-50 px-3 py-2.5 text-center"
                    >
                      <p className="text-xs font-semibold text-accent-700">{bid.name}</p>
                      <p className="mt-0.5 text-sm font-bold tabular-nums text-slate-900">
                        {bid.amount}
                      </p>
                    </div>
                  ) : (
                    <div
                      key={bid.name}
                      className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-center opacity-60"
                    >
                      <p className="text-xs font-medium text-slate-400">{bid.name}</p>
                      <p className="mt-0.5 text-xs text-slate-400">{bid.amount}</p>
                    </div>
                  )
                )}
              </div>
            </div>

            <div aria-hidden="true" className="flex justify-center py-3 text-slate-300">
              <Icon name="chevron-down" className="h-6 w-6" />
            </div>

            {/* 上位3社が交渉権を獲得 */}
            <div className="rounded-xl border border-brand-200 bg-brand-50 px-5 py-4 text-center">
              <p className="text-sm font-semibold text-brand-900">上位3社が交渉権を獲得</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-800">
                あなたは3社の条件を比べて、いちばん納得できる業者を選び、取引・引き取りまで進めます。
              </p>
            </div>
            <p className="mt-4 text-center text-xs leading-relaxed text-slate-400">
              表示額はイメージです。査定額はAIと業者による参考値で、最終的な買取額は業者の現物査定により決まります。
            </p>
          </div>

          {/* 写真: 玄関先で品物を引き渡す女性の笑顔 */}
          <div className="mx-auto mt-8 flex max-w-3xl flex-col items-center gap-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-card sm:flex-row sm:p-6">
            <div className="relative aspect-[4/3] w-full shrink-0 overflow-hidden rounded-xl bg-gradient-to-br from-brand-100 via-brand-200 to-accent-200 ring-1 ring-slate-200/70 sm:w-56">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/img/handover.png"
                alt="玄関先で、買取業者に品物を笑顔で引き渡す女性"
                width={800}
                height={600}
                loading="lazy"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
                className="absolute inset-0 h-full w-full object-cover"
              />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">
                最後は、笑顔で
              </p>
              <h3 className="mt-1.5 text-base font-bold text-slate-900">
                選んだ1社と、引き渡しまでスムーズに
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-500">
                条件のよい業者を選んだら、あとは受け取り日時を決めるだけ。訪問かオンラインかも、あなたが選べます。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================
          TIDY — 片付く価値
      ============================================================ */}
      <section id="tidy" className="bg-white py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">
                片付く価値
              </p>
              <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
                売れる物はまとめて一括買取。
                <br className="hidden sm:block" />
                残りも、手放す導線までご案内
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-slate-500">
                1点ずつ売る必要はありません。まとめて査定・一括買取で、まとめて片付きます。値段がつかない物についても、自治体の回収や無償譲渡など「手放す導線」を情報としてご案内します。
              </p>
              <div className="mt-6 space-y-3">
                {[
                  "まとめて一括査定・一括買取。点数が多くても、ひとまとめで依頼できます。",
                  "手放す導線のご案内。自治体回収・無償譲渡・寄付などの選択肢を情報提供します。",
                  "取引・引き取りは業者が実施。あなたは案内に沿って受け取り日時を選ぶだけです。",
                ].map((text) => (
                  <div key={text} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-100 text-accent-700">
                      <Icon name="check" className="h-3.5 w-3.5" strokeWidth={2.5} />
                    </span>
                    <p className="text-sm leading-relaxed text-slate-600">{text}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
              {/* 写真: 片付いてすっきりした部屋で満足げな女性 */}
              <div className="relative aspect-[4/3] w-full bg-gradient-to-br from-accent-100 via-brand-100 to-brand-200">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/img/after.png"
                  alt="片付いてすっきりした明るい部屋で、満足そうにくつろぐ女性"
                  width={800}
                  height={600}
                  loading="lazy"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                  className="absolute inset-0 h-full w-full object-cover"
                />
              </div>
              <div className="p-6 sm:p-8">
              <h3 className="text-base font-bold text-slate-900">品物の扱われ方</h3>
              <div className="mt-4 space-y-3">
                <div className="rounded-xl border border-accent-200 bg-accent-50/60 p-4">
                  <p className="text-sm font-semibold text-accent-700">値段がつく物</p>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    上位3社と交渉し、まとめて一括買取。条件のよい業者と取引します。
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-sm font-semibold text-slate-700">値段がつかない物</p>
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    自治体の粗大ごみ・拠点回収、無償譲渡、寄付などの手放す導線をご案内します。
                  </p>
                </div>
              </div>
              <p className="mt-4 flex items-start gap-1.5 text-xs leading-relaxed text-slate-400">
                <Icon name="info" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                ソクウリは取引の「場」を提供します。買取・回収・運搬は各業者または各導線が行います。
              </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================
          AREA — 対応エリア
      ============================================================ */}
      <section id="area" className="bg-slate-50 py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">
              対応エリア
            </p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              首都圏1都3県でご利用いただけます
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-500">
              現在の対応エリアは、東京・千葉・埼玉・神奈川です。
            </p>
          </div>

          <div className="mx-auto mt-10 grid max-w-3xl grid-cols-2 gap-4 sm:grid-cols-4">
            {AREAS.map(({ name, desc }) => (
              <div
                key={name}
                className="flex flex-col items-center gap-2 rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-card transition-all hover:border-brand-300 hover:shadow-card-hover"
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                  <Icon name="package" className="h-6 w-6" />
                </span>
                <span className="text-base font-semibold text-slate-900">{name}</span>
                <span className="text-xs text-slate-400">{desc}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================================
          SAFETY — 安心・個人情報
      ============================================================ */}
      <section id="safety" className="bg-white py-16 sm:py-20 lg:py-24">
        <div className="container-aw">
          <div className="grid items-center gap-10 lg:grid-cols-2">
            {/* 写真: ソファでくつろぎ連絡を待つ女性 */}
            <div className="relative order-2 aspect-[4/3] overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-brand-100 via-brand-200 to-brand-300 shadow-card lg:order-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/img/relief.png"
                alt="ソファでスマートフォンを見ながら、業者からの連絡をゆったり待つ女性"
                width={800}
                height={600}
                loading="lazy"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
                className="absolute inset-0 h-full w-full object-cover"
              />
            </div>
            <div className="order-1 lg:order-2">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">
                安心・個人情報
              </p>
              <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
                追い立てられない。
                <br className="hidden sm:block" />
                あなたのペースで手放せる
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-slate-500">
                電話が一斉に鳴ることも、急かされることもありません。情報も権利も守られた状態で、ソファで待つだけ。落ち着いてやり取りできる設計です。
              </p>
            </div>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-3">
            {SAFETY.map(({ icon, title, desc }) => (
              <div
                key={title}
                className="rounded-2xl border border-slate-200 bg-white p-6 shadow-card"
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                  <Icon name={icon} className="h-6 w-6" />
                </span>
                <h3 className="mt-4 text-base font-bold text-slate-900">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-500">{desc}</p>
              </div>
            ))}
          </div>

          <div className="mx-auto mt-6 max-w-3xl rounded-2xl border border-amber-200 bg-amber-50 p-5">
            <div className="flex items-start gap-3">
              <span className="rounded-md bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-800">
                PR / 広告
              </span>
              <p className="text-xs leading-relaxed text-amber-900">
                業者の紹介・将来の手数料が関わる箇所には「広告 / PR」を明示します。AIによる査定額は参考値であり、実際の買取額は各業者の現物査定により決定します。
              </p>
            </div>
          </div>
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
                今日、その「片付けたい」を動かす
              </h2>
              <p className="mt-3 text-sm text-brand-100 sm:text-base">
                品物を1点ずつ撮るだけ。あとは待つだけで、競った査定が届きます。
              </p>
              <div className="mt-7 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <button
                  type="button"
                  onClick={() => {
                    window.scrollTo({ top: 0, behavior: "smooth" });
                    setTimeout(() => inputRef.current?.click(), 500);
                  }}
                  className="inline-flex items-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-brand-700 shadow-lg transition-transform hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-brand-900"
                >
                  <Icon name="camera" className="h-5 w-5" />
                  AI仮査定を依頼する
                </button>
                <a
                  href="#line"
                  className="inline-flex items-center gap-2 rounded-xl border border-white/30 bg-white/5 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-brand-900"
                >
                  <Icon name="external" className="h-5 w-5" />
                  LINEで受付（準備中）
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
