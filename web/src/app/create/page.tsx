"use client";

/**
 * 案件作成フロー（4 STEP・新デザイン）。
 * STEP1 写真 → STEP2 利用目的 → STEP3 住居情報 → STEP4 確認送信。
 * 既存の配線を完全維持: useToken / uploadCasePhoto ループ / createCase → /cases/{id}?created=1。
 * デザインは品目カード型だが、バックエンド契約（case単位）維持のため既存フローに視覚言語のみ適用。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { useToken } from "@/components/kdz/Ui";
import { createCase, uploadCasePhoto, KdzApiError } from "@/lib/katadzuke-api";
import "./create.css";

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

  // Blob URL のメモリリーク防止: previews 更新時/アンマウント時に旧URLを解放
  useEffect(() => {
    return () => {
      previews.forEach((p) => URL.revokeObjectURL(p.url));
    };
  }, [previews]);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => `${f.name}:${f.size}`));
      return [...prev, ...selected.filter((f) => !existing.has(`${f.name}:${f.size}`))].slice(0, 20);
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
      setError(err instanceof KdzApiError ? err.message : "送信に失敗しました。もう一度お試しください。");
      setSubmitting(false);
      setProgress("");
    }
  }

  if (loading) {
    return (
      <div className="create-page flow-bg">
        <div className="form-loading">
          <span className="spinning">↻</span>
        </div>
      </div>
    );
  }

  return (
    <div className="create-page flow-bg">
      {/* flow-header */}
      <div className="flow-header">
        <div className="flow-header-inner">
          <Link href="/" aria-label="カタヅケ トップへ">
            <KdzLogo size={18} />
          </Link>
          <div className="flow-steps">
            {STEPS.map((label, i) => {
              const cls = i < step ? "done" : i === step ? "active" : "";
              return (
                <div key={label} className={`flow-step ${cls}`.trim()}>
                  <div className="fs-dot">{i < step ? <Ic name="check" style={{ fontSize: 12, strokeWidth: 3 }} /> : i + 1}</div>
                  <div className="fs-label">{label}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <main id="main">
        <div className="flow-wrap">
          {error && (
            <div className="auth-error" style={{ marginBottom: 16 }}>
              <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "#cc3333", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                <circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" />
              </svg>
              {error}
            </div>
          )}

          {/* STEP 1: 写真 */}
          {step === 0 && (
            <div>
              <h2 className="step-title">片付けたい場所を撮影</h2>
              <p className="step-desc">部屋全体が写るように撮影してください（最大20枚）。物量がわかるほど、正確な見積もりが届きやすくなります。</p>
              <div className="form-card">
                <label className="photo-drop">
                  <span className="pd-ic"><Ic name="camera" /></span>
                  <span className="pd-title">写真を撮影・選択</span>
                  <span className="pd-sub">JPEG / PNG / WebP・最大20枚</span>
                  <input ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" multiple className="sr-only" onChange={handleFileChange} />
                </label>
                {previews.length > 0 && (
                  <div className="photo-grid">
                    {previews.map((p, i) => (
                      <div key={p.url} className="photo-thumb">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={p.url} alt={p.name} />
                        <button type="button" className="photo-remove" onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))} aria-label={`${p.name} を削除`}>
                          <Ic name="x" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <p className="photo-count">{files.length} / 20 枚選択中</p>
                <div className="photo-quality-hint">
                  <Ic name="spark" />
                  <span><strong>コツ：</strong>部屋全体 → 気になる物のアップ、の順で撮ると物量が伝わりやすく、見積もりの精度が上がります。</span>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: 利用目的 */}
          {step === 1 && (
            <div>
              <h2 className="step-title">ご利用目的を選択</h2>
              <p className="step-desc">あてはまるものを選んでください。業者のマッチングに使用します。</p>
              <div className="form-card">
                <div className="purpose-grid">
                  {PURPOSES.map((p) => (
                    <button key={p} type="button" className={`purpose-card${purpose === p ? " selected" : ""}`} onClick={() => setPurpose(p)}>
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* STEP 3: 住居情報 */}
          {step === 2 && (
            <div>
              <h2 className="step-title">住居情報を入力</h2>
              <p className="step-desc">番地・建物名は業者決定まで公開されません（市区町村までを業者に提示します）。</p>
              <div className="form-card">
                <div className="field-row">
                  <div className="field">
                    <label>都道府県</label>
                    <div className="select-wrap">
                      <select value={prefecture} onChange={(e) => setPrefecture(e.target.value)}>
                        {PREFECTURES.map((p) => <option key={p} value={p}>{p}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="field">
                    <label>市区町村<span className="req">必須</span></label>
                    <input type="text" value={city} onChange={(e) => setCity(e.target.value)} placeholder="世田谷区" />
                  </div>
                </div>
                <div className="field">
                  <label>番地・建物名・部屋番号<span className="opt">業者決定後に開示</span></label>
                  <input type="text" value={addressDetail} onChange={(e) => setAddressDetail(e.target.value)} placeholder="桜丘1-2-3 メゾン桜 101号室" />
                </div>
                <div className="field-row">
                  <div className="field">
                    <label>住居タイプ</label>
                    <div className="select-wrap">
                      <select value={housingType} onChange={(e) => setHousingType(e.target.value)}>
                        {HOUSING_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="field">
                    <label>間取り</label>
                    <div className="select-wrap">
                      <select value={floorPlan} onChange={(e) => setFloorPlan(e.target.value)}>
                        {FLOOR_PLANS.map((f) => <option key={f} value={f}>{f}</option>)}
                      </select>
                    </div>
                  </div>
                </div>
                <div className="field-row">
                  <div className="field">
                    <label>階数</label>
                    <input type="number" min={0} max={100} value={floorNumber} onChange={(e) => setFloorNumber(e.target.value)} placeholder="3" />
                  </div>
                  <div className="field">
                    <label>エレベーター</label>
                    <div className="check-row">
                      <input type="checkbox" id="ev" checked={hasElevator} onChange={(e) => setHasElevator(e.target.checked)} />
                      <label htmlFor="ev">エレベーターあり</label>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 4: 確認 */}
          {step === 3 && (
            <div>
              <h2 className="step-title">内容を確認</h2>
              <p className="step-desc">この内容で出品します。送信するとAIが写真を解析して案件化し、登録業者へ公開されます。</p>
              <div className="form-card">
                {[
                  ["写真", `${files.length} 枚`],
                  ["利用目的", purpose],
                  ["エリア", `${prefecture} ${city}`],
                  ["住所詳細", addressDetail || "（未入力）"],
                  ["住居", `${housingType} / ${floorPlan}`],
                  ["階数・EV", `${floorNumber ? `${floorNumber}階` : "—"} / EV${hasElevator ? "あり" : "なし"}`],
                ].map(([k, v]) => (
                  <div key={k} className="confirm-row"><span className="lbl">{k}</span><span className="val">{v}</span></div>
                ))}
              </div>
              <div className="hint-banner">
                <Ic name="lock" className="hint-ic" />
                <span>住所詳細・連絡先は業者決定まで開示されません。査定に回るのは写真と品目・住居情報のみです。</span>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* flow-footer */}
      <div className="flow-footer">
        <div className="inner">
          {step > 0 && (
            <button type="button" className="btn-flow-back" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={submitting}>
              戻る
            </button>
          )}
          {step < STEPS.length - 1 ? (
            <button type="button" className="btn-flow-next" onClick={() => canNext() && setStep((s) => s + 1)} disabled={!canNext()}>
              次へ<Ic name="arrow" />
            </button>
          ) : (
            <button type="button" className="btn-flow-next" onClick={submit} disabled={submitting}>
              {submitting ? (
                <><span className="spinning">↻</span> {progress || "送信中…"}</>
              ) : (
                <>この内容で依頼する<Ic name="arrow" /></>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
