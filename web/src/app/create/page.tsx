"use client";

/**
 * 案件作成フォーム（4 STEP）。
 * STEP1: 写真撮影 → STEP2: 利用目的 → STEP3: 住居情報 → STEP4: 確認送信。
 * DefectUploader.tsx のファイル選択パターン / Stepper.tsx の進捗パターンを流用。
 */

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon, Spinner } from "@/components/Icon";
import {
  KdzStepper,
  Notice,
  btnPrimary,
  btnSecondary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import { createCase, uploadCasePhoto, KdzApiError } from "@/lib/katadzuke-api";

const STEPS = ["写真", "利用目的", "住居情報", "確認"] as const;
const PURPOSES = ["片付け整理", "遺品整理", "引っ越し", "その他"] as const;
const PREFECTURES = ["東京都", "神奈川県", "埼玉県", "千葉県"] as const;
const HOUSING_TYPES = ["一戸建て", "マンション", "アパート", "その他"] as const;
const FLOOR_PLANS = ["1R/1K", "1DK/1LDK", "2K/2DK", "2LDK", "3LDK", "4LDK以上"] as const;

export default function CreateCasePage() {
  const router = useRouter();
  const { token, loading } = useToken();

  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [purpose, setPurpose] = useState<string>(PURPOSES[0]);
  const [prefecture, setPrefecture] = useState<string>(PREFECTURES[0]);
  const [city, setCity] = useState("");
  const [addressDetail, setAddressDetail] = useState("");
  const [housingType, setHousingType] = useState<string>(HOUSING_TYPES[1]);
  const [floorPlan, setFloorPlan] = useState<string>(FLOOR_PLANS[3]);
  const [floorNumber, setFloorNumber] = useState<string>("");
  const [hasElevator, setHasElevator] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const previews = useMemo(
    () => files.map((f) => ({ name: f.name, url: URL.createObjectURL(f) })),
    [files],
  );

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => `${f.name}:${f.size}`));
      return [...prev, ...selected.filter((f) => !existing.has(`${f.name}:${f.size}`))].slice(
        0,
        20,
      );
    });
    if (inputRef.current) inputRef.current.value = "";
  }

  function canNext(): boolean {
    if (step === 0) return files.length > 0;
    if (step === 2) return city.trim().length > 0;
    return true;
  }

  async function submit() {
    if (!token) {
      setError("ログインが必要です。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const photos: { storage_key: string; sort_order: number }[] = [];
      for (let i = 0; i < files.length; i++) {
        setProgress(`写真をアップロード中… (${i + 1}/${files.length})`);
        const presign = await uploadCasePhoto(files[i], token);
        photos.push({ storage_key: presign.storage_key, sort_order: i });
      }
      setProgress("AIが案件を要約しています…");
      const created = await createCase(
        {
          purpose,
          prefecture,
          city: city.trim(),
          address_detail: addressDetail.trim() || null,
          housing_type: housingType,
          floor_plan: floorPlan,
          floor_number: floorNumber === "" ? null : Number(floorNumber),
          has_elevator: hasElevator,
          photos,
        },
        token,
      );
      router.push(`/cases/${created.id}?created=1`);
    } catch (err) {
      setError(
        err instanceof KdzApiError ? err.message : "送信に失敗しました。もう一度お試しください。",
      );
      setSubmitting(false);
      setProgress("");
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  return (
    <div className="container-aw max-w-2xl py-10">
      <h1 className="text-2xl font-bold text-slate-900">片付けを依頼する</h1>
      <p className="mt-1.5 text-sm text-slate-500">
        部屋の写真と住居情報を送ると、登録業者から見積もりが届きます。
      </p>

      <div className="mt-8">
        <KdzStepper labels={STEPS} current={step} />
      </div>

      <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        {error ? (
          <div className="mb-4">
            <Notice tone="error">{error}</Notice>
          </div>
        ) : null}

        {/* ===== STEP 1: 写真 ===== */}
        {step === 0 && (
          <div className="space-y-4">
            <h2 className="font-bold text-slate-900">片付けたい場所の写真</h2>
            <p className="text-sm leading-relaxed text-slate-500">
              部屋全体が写るように撮影してください（最大20枚）。
              物量がわかるほど、正確な見積もりが届きやすくなります。
            </p>
            <label className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border-2 border-dashed border-brand-300 bg-brand-50/50 px-4 py-8 text-sm font-semibold text-brand-700 transition-colors hover:bg-brand-50">
              <Icon name="camera" className="h-5 w-5" />
              写真を撮影・選択
              <input
                ref={inputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                capture="environment"
                multiple
                className="sr-only"
                onChange={handleFileChange}
              />
            </label>
            {previews.length > 0 && (
              <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                {previews.map((p, i) => (
                  <li key={p.url} className="group relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={p.url}
                      alt={p.name}
                      className="aspect-square w-full rounded-xl border border-slate-200 object-cover"
                    />
                    <button
                      type="button"
                      onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                      className="absolute right-1 top-1 rounded-full bg-slate-900/70 p-1 text-white opacity-80 transition-opacity hover:opacity-100"
                      aria-label={`${p.name} を削除`}
                    >
                      <Icon name="close" className="h-3.5 w-3.5" strokeWidth={2.5} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs text-slate-400">{files.length} / 20 枚選択中</p>
          </div>
        )}

        {/* ===== STEP 2: 利用目的 ===== */}
        {step === 1 && (
          <div className="space-y-4">
            <h2 className="font-bold text-slate-900">利用目的</h2>
            <div className="grid gap-2.5 sm:grid-cols-2">
              {PURPOSES.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPurpose(p)}
                  className={`rounded-xl border px-4 py-3.5 text-left text-sm font-semibold transition-colors ${
                    purpose === p
                      ? "border-brand-600 bg-brand-50 text-brand-700 ring-2 ring-brand-200"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ===== STEP 3: 住居情報 ===== */}
        {step === 2 && (
          <div className="space-y-4">
            <h2 className="font-bold text-slate-900">住居情報</h2>
            <p className="text-sm text-slate-500">
              番地・建物名は業者決定まで公開されません（市区町村までを業者に提示します）。
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">都道府県</span>
                <select
                  value={prefecture}
                  onChange={(e) => setPrefecture(e.target.value)}
                  className={inputBase}
                >
                  {PREFECTURES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">
                  市区町村 <span className="text-red-500">*</span>
                </span>
                <input
                  type="text"
                  required
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  className={inputBase}
                  placeholder="世田谷区"
                />
              </label>
            </div>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">
                番地・建物名・部屋番号（業者決定後にのみ開示）
              </span>
              <input
                type="text"
                value={addressDetail}
                onChange={(e) => setAddressDetail(e.target.value)}
                className={inputBase}
                placeholder="桜丘1-2-3 メゾン桜 101号室"
              />
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">住居タイプ</span>
                <select
                  value={housingType}
                  onChange={(e) => setHousingType(e.target.value)}
                  className={inputBase}
                >
                  {HOUSING_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">間取り</span>
                <select
                  value={floorPlan}
                  onChange={(e) => setFloorPlan(e.target.value)}
                  className={inputBase}
                >
                  {FLOOR_PLANS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">階数</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={floorNumber}
                  onChange={(e) => setFloorNumber(e.target.value)}
                  className={inputBase}
                  placeholder="3"
                />
              </label>
              <label className="flex items-end gap-2 pb-2.5">
                <input
                  type="checkbox"
                  checked={hasElevator}
                  onChange={(e) => setHasElevator(e.target.checked)}
                  className="h-5 w-5 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                />
                <span className="text-sm font-medium text-slate-700">エレベーターあり</span>
              </label>
            </div>
          </div>
        )}

        {/* ===== STEP 4: 確認送信 ===== */}
        {step === 3 && (
          <div className="space-y-4">
            <h2 className="font-bold text-slate-900">内容の確認</h2>
            <dl className="divide-y divide-slate-100 text-sm">
              {[
                ["写真", `${files.length} 枚`],
                ["利用目的", purpose],
                ["エリア", `${prefecture} ${city}`],
                ["住所詳細", addressDetail || "（未入力）"],
                ["住居", `${housingType} / ${floorPlan}`],
                [
                  "階数・EV",
                  `${floorNumber ? `${floorNumber}階` : "—"} / EV${hasElevator ? "あり" : "なし"}`,
                ],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 py-2.5">
                  <dt className="shrink-0 font-medium text-slate-500">{k}</dt>
                  <dd className="text-right text-slate-900">{v}</dd>
                </div>
              ))}
            </dl>
            <Notice tone="info">
              送信するとAIが写真を解析して案件化し、登録業者へ公開されます。
              住所詳細・連絡先は業者決定まで開示されません。
            </Notice>
          </div>
        )}

        {/* ===== ナビゲーション ===== */}
        <div className="mt-8 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0 || submitting}
            className={btnSecondary}
          >
            戻る
          </button>
          {step < STEPS.length - 1 ? (
            <button
              type="button"
              onClick={() => canNext() && setStep((s) => s + 1)}
              disabled={!canNext()}
              className={btnPrimary}
            >
              次へ
            </button>
          ) : (
            <button type="button" onClick={submit} disabled={submitting} className={btnPrimary}>
              {submitting ? (
                <>
                  <Spinner className="h-4 w-4" />
                  {progress || "送信中…"}
                </>
              ) : (
                "この内容で依頼する"
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
