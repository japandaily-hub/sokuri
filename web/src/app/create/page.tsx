"use client";

/**
 * 案件作成フロー（4 STEP・新デザイン）。
 * STEP1 写真 → STEP2 利用目的 → STEP3 住居情報 → STEP4 確認送信。
 * STEP1 は「商品ごとに撮影→アルバムとして確定→次の商品を追加」を繰り返す albums フローと、
 * 従来通りの「まとめて撮る」フラット撮影（loose）の 2 系統を list/shoot のモード遷移で提供する。
 * バックエンド契約: POST /cases に items（商品アルバム, 任意）と photos（フラット, 必須）を両方送る。
 * 既存の配線を完全維持: useToken / uploadCasePhoto ループ / createCase → /cases/{id}?created=1。
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { useToken } from "@/components/kdz/Ui";
import { createCase, uploadCasePhoto, toDisplayMessage } from "@/lib/katadzuke-api";
import "./create.css";

const STEPS = ["写真", "利用目的", "住居情報", "確認"] as const;
const PURPOSES = ["片付け整理", "遺品整理", "引っ越し", "その他"] as const;
const PREFECTURES = ["東京都", "神奈川県", "埼玉県", "千葉県"] as const;
const HOUSING_TYPES = ["一戸建て", "マンション", "アパート", "その他"] as const;
const FLOOR_PLANS = ["1R/1K", "1DK/1LDK", "2K/2DK", "2LDK", "3LDK", "4LDK以上"] as const;

/** 案件全体の写真上限（items 内 + loose 合計、バックエンド契約に合わせる）。 */
const CASE_PHOTO_LIMIT = 150;
/** 商品1点あたりの写真上限。 */
const ITEM_PHOTO_LIMIT = 12;
/** 商品数の上限。 */
const ITEM_LIMIT = 30;

/** 撮影のコツ（表示のみ）。撮影完了の前提となる確認レ点は `${itemId}:confirm` キーで checkedHints に持つ（APIには送らない）。 */
const HINT_ITEMS: { key: string; icon: IcName; label: string }[] = [
  { key: "angles", icon: "scan", label: "全方位（正面・背面・側面・底面など）から撮る" },
  { key: "damage", icon: "zoom", label: "傷・汚れ・色あせ・凹みも隠さずアップで撮る" },
  { key: "tag", icon: "tag", label: "メーカーロゴ・型番シール・タグもアップで撮る" },
];

type DraftPhoto = { id: string; file: File; previewUrl: string; uploadedKey?: string };

/* ---- 端末側の縮小（アップロード前） ----
   上限を 150 枚に引き上げたため、スマホの原寸写真（3〜10MB）をそのまま送ると
   通信時間とサーバー側ディスクが持たない。長辺 2000px・JPEG 品質 0.85 に縮小して
   から扱う（縮小に失敗した場合は元ファイルをそのまま使う）。 */
const DOWNSCALE_MAX_EDGE = 2000;
const DOWNSCALE_SKIP_BYTES = 1_200_000;

async function downscaleImage(file: File): Promise<File> {
  if (typeof createImageBitmap !== "function") return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const longEdge = Math.max(bitmap.width, bitmap.height);
    if (longEdge <= DOWNSCALE_MAX_EDGE && file.size <= DOWNSCALE_SKIP_BYTES) {
      bitmap.close();
      return file;
    }
    const scale = Math.min(1, DOWNSCALE_MAX_EDGE / longEdge);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      bitmap.close();
      return file;
    }
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.85),
    );
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: file.lastModified });
  } catch {
    return file;
  }
}

type DraftItem = { id: string; name: string; photos: DraftPhoto[] };
type Step1Mode = { kind: "list" } | { kind: "shoot"; itemId: string };

/** 案件作成フロー内でのみ使う軽量な一意ID（サーバーには送らない）。 */
function makeId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
}

export default function CreateCasePage() {
  const router = useRouter();
  const { token, loading } = useToken();

  // 導線: 未ログインで撮影を始めさせない（送信時に初めてログインを求めると撮影が無駄になる）。
  useEffect(() => {
    if (!loading && !token) router.replace("/login?callbackUrl=%2Fcreate");
  }, [loading, token, router]);

  const [step, setStep] = useState(0);

  // STEP1: 商品ごとのアルバム（items）+ まとめ撮影（loose）
  const [mode, setMode] = useState<Step1Mode>({ kind: "list" });
  const [items, setItems] = useState<DraftItem[]>([]);
  const [loosePhotos, setLoosePhotos] = useState<DraftPhoto[]>([]);
  const [showLooseSection, setShowLooseSection] = useState(false);
  const [checkedHints, setCheckedHints] = useState<Set<string>>(new Set());
  const looseInputRef = useRef<HTMLInputElement>(null);
  const itemInputRef = useRef<HTMLInputElement>(null);

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
  /**
   * 冪等キー（crypto.randomUUID()）。AI 解析は backend 側で背景実行されるため
   * POST /cases 自体は即応答するが、通信断・二重タップでの再送信時に同一案件を
   * 二重作成させないよう、送信の最初の試行で1度だけ発行し、リトライでは使い回す。
   */
  const idempotencyKeyRef = useRef<string | null>(null);

  // ---- H3対策: 撮影済みの写真がある状態での離脱を防ぐ ----
  /** 離脱確認モーダル（ブラウザバック検知時）の開閉。 */
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false);
  /** true の間はブラウザバックのガードを素通しする（確認モーダルで「離れる」を選んだ直後）。 */
  const allowLeaveRef = useRef(false);
  /** 履歴に番兵エントリを積んだかどうか（写真が0→1枚になった最初の1回だけ積む）。 */
  const guardArmedRef = useRef(false);

  // Blob URL のメモリリーク防止: 個別削除時に都度 revoke、それ以外はアンマウント時にまとめて revoke する。
  // items/loosePhotos は ref に都度同期し、アンマウント時のクリーンアップはこの ref から読む
  // （commit のたびに revoke される既存バグ = previews を useMemo(files) で再生成する実装を避ける）。
  const itemsRef = useRef(items);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);
  const loosePhotosRef = useRef(loosePhotos);
  useEffect(() => {
    loosePhotosRef.current = loosePhotos;
  }, [loosePhotos]);
  useEffect(() => {
    return () => {
      itemsRef.current.forEach((it) => it.photos.forEach((p) => URL.revokeObjectURL(p.previewUrl)));
      loosePhotosRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
  }, []);

  const totalPhotoCount =
    items.reduce((sum, it) => sum + it.photos.length, 0) + loosePhotos.length;
  const totalItemCount = items.length;

  // H3対策 1/2: リロード・タブを閉じる離脱に標準の確認ダイアログを出す。
  // ブラウザは returnValue の文言を無視し固定の汎用テキストを表示する仕様のため、
  // ここでは preventDefault + returnValue セットのみ行う（カスタム文言は表示できない）。
  useEffect(() => {
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      if (totalPhotoCount === 0) return;
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [totalPhotoCount]);

  // H3対策 2/2: ブラウザバックに確認モーダルを挟む。
  // 履歴に番兵エントリを1つ積み、popstate（=バック操作）を検知したら即座に
  // 履歴を押し戻して離脱を一旦キャンセルし、代わりに確認モーダルを出す
  // （SPAで一般的な「二重pushで戻るを横取りする」パターン）。
  useEffect(() => {
    function currentPhotoCount() {
      return (
        itemsRef.current.reduce((sum, it) => sum + it.photos.length, 0) +
        loosePhotosRef.current.length
      );
    }
    function handlePopState() {
      if (allowLeaveRef.current) return;
      if (currentPhotoCount() === 0) return;
      window.history.pushState({ kdzCreateGuard: true }, "", window.location.href);
      setLeaveConfirmOpen(true);
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (totalPhotoCount > 0 && !guardArmedRef.current) {
      guardArmedRef.current = true;
      window.history.pushState({ kdzCreateGuard: true }, "", window.location.href);
    }
  }, [totalPhotoCount]);

  /** 離脱確認モーダル「入力を続ける」（安全側のデフォルト）。 */
  function cancelLeave() {
    setLeaveConfirmOpen(false);
  }

  /**
   * 離脱確認モーダル「ページを離れる」。
   * QAレビュー H1 是正: window.history.go(-2) は履歴段数のハードコードで、
   * /create が新規タブ・直接アクセス等で履歴の先頭にある場合 no-op になり
   * 永久に離脱できなくなる。履歴段数に依存せず、ブラウザバック検知（popstate）
   * 経路も含めて router.push("/mypage") に出口を統一する
   * （/create は入口が複数あるため戻り先はマイページ固定が安全）。
   * allowLeaveRef を先に立てるため、遷移後に popstate ガードが誤って
   * 再度モーダルを開くことはない。
   */
  function confirmLeave() {
    allowLeaveRef.current = true;
    setLeaveConfirmOpen(false);
    router.push("/mypage");
  }

  const currentItemIndex = mode.kind === "shoot" ? items.findIndex((it) => it.id === mode.itemId) : -1;
  const currentItem = currentItemIndex >= 0 ? items[currentItemIndex] : undefined;

  function addNewItem() {
    if (items.length >= ITEM_LIMIT || totalPhotoCount >= CASE_PHOTO_LIMIT) return;
    const id = makeId();
    setItems((prev) => [...prev, { id, name: "", photos: [] }]);
    setMode({ kind: "shoot", itemId: id });
  }

  function editItem(itemId: string) {
    setMode({ kind: "shoot", itemId });
  }

  function deleteItem(itemId: string) {
    setItems((prev) => {
      const target = prev.find((it) => it.id === itemId);
      target?.photos.forEach((p) => URL.revokeObjectURL(p.previewUrl));
      return prev.filter((it) => it.id !== itemId);
    });
  }

  function renameItem(itemId: string, name: string) {
    setItems((prev) => prev.map((it) => (it.id === itemId ? { ...it, name } : it)));
  }

  /** shoot モードを離れる（一覧へ戻る/完了どちらも同じ後始末）。写真0枚のまま離脱した商品は自動で消す。 */
  function exitShoot() {
    if (mode.kind === "shoot") {
      const id = mode.itemId;
      setItems((prev) => prev.filter((it) => it.id !== id || it.photos.length > 0));
    }
    setMode({ kind: "list" });
  }

  /** shoot モード内の「この商品を削除」（写真の有無に関わらず商品ごと削除）。 */
  function deleteCurrentItem() {
    if (mode.kind !== "shoot") return;
    deleteItem(mode.itemId);
    setMode({ kind: "list" });
  }

  function addFilesToItem(itemId: string, files: File[]) {
    if (files.length === 0) return;
    let dropped = false;
    setItems((prev) => {
      const caseTotal = prev.reduce((s, it) => s + it.photos.length, 0) + loosePhotosRef.current.length;
      const caseRemaining = Math.max(0, CASE_PHOTO_LIMIT - caseTotal);
      return prev.map((it) => {
        if (it.id !== itemId) return it;
        const existingKeys = new Set(it.photos.map((p) => `${p.file.name}:${p.file.size}`));
        const dedupedFiles = files.filter((f) => !existingKeys.has(`${f.name}:${f.size}`));
        const itemRemaining = Math.max(0, ITEM_PHOTO_LIMIT - it.photos.length);
        const allowed = dedupedFiles.slice(0, Math.min(itemRemaining, caseRemaining));
        if (allowed.length < dedupedFiles.length) dropped = true;
        if (allowed.length === 0) return it;
        const newPhotos: DraftPhoto[] = allowed.map((f) => ({
          id: makeId(),
          file: f,
          previewUrl: URL.createObjectURL(f),
        }));
        return { ...it, photos: [...it.photos, ...newPhotos] };
      });
    });
    if (dropped) {
      setError(`上限（商品${ITEM_PHOTO_LIMIT}枚・案件合計${CASE_PHOTO_LIMIT}枚）のため、一部の写真は追加されませんでした。`);
    }
  }

  function removePhotoFromItem(itemId: string, photoId: string) {
    setItems((prev) =>
      prev.map((it) => {
        if (it.id !== itemId) return it;
        const target = it.photos.find((p) => p.id === photoId);
        if (target) URL.revokeObjectURL(target.previewUrl);
        return { ...it, photos: it.photos.filter((p) => p.id !== photoId) };
      }),
    );
  }

  async function handleItemFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    if (itemInputRef.current) itemInputRef.current.value = "";
    if (mode.kind !== "shoot") return;
    const targetItemId = mode.itemId;
    const prepared = await Promise.all(selected.map(downscaleImage));
    addFilesToItem(targetItemId, prepared);
  }

  function addLooseFiles(files: File[]) {
    if (files.length === 0) return;
    const itemsTotal = itemsRef.current.reduce((s, it) => s + it.photos.length, 0);
    let dropped = false;
    setLoosePhotos((prev) => {
      const caseRemaining = Math.max(0, CASE_PHOTO_LIMIT - itemsTotal - prev.length);
      const existingKeys = new Set(prev.map((p) => `${p.file.name}:${p.file.size}`));
      const dedupedFiles = files.filter((f) => !existingKeys.has(`${f.name}:${f.size}`));
      const allowed = dedupedFiles.slice(0, caseRemaining);
      if (allowed.length < dedupedFiles.length) dropped = true;
      if (allowed.length === 0) return prev;
      const newPhotos: DraftPhoto[] = allowed.map((f) => ({
        id: makeId(),
        file: f,
        previewUrl: URL.createObjectURL(f),
      }));
      return [...prev, ...newPhotos];
    });
    if (dropped) {
      setError(`上限（案件合計${CASE_PHOTO_LIMIT}枚）のため、一部の写真は追加されませんでした。`);
    }
  }

  async function handleLooseFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    if (looseInputRef.current) looseInputRef.current.value = "";
    const prepared = await Promise.all(selected.map(downscaleImage));
    addLooseFiles(prepared);
  }

  function removeLoosePhoto(photoId: string) {
    setLoosePhotos((prev) => {
      const target = prev.find((p) => p.id === photoId);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((p) => p.id !== photoId);
    });
  }

  function toggleHint(itemId: string, hintKey: string) {
    const key = `${itemId}:${hintKey}`;
    setCheckedHints((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function canNext(): boolean {
    if (step === 0) return totalPhotoCount > 0;
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
      const itemPayloads: { name?: string; sort_order: number; photos: { storage_key: string; sort_order: number }[] }[] = [];

      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.photos.length === 0) continue;
        const photoPayloads: { storage_key: string; sort_order: number }[] = [];
        for (let j = 0; j < item.photos.length; j++) {
          const photo = item.photos[j];
          setProgress(`商品 ${i + 1}/${items.length} の写真をアップロード中… (${j + 1}/${item.photos.length})`);
          let key = photo.uploadedKey;
          if (!key) {
            const presign = await uploadCasePhoto(photo.file, token);
            key = presign.storage_key;
            setItems((prev) =>
              prev.map((it) =>
                it.id === item.id
                  ? { ...it, photos: it.photos.map((p) => (p.id === photo.id ? { ...p, uploadedKey: key } : p)) }
                  : it,
              ),
            );
          }
          photoPayloads.push({ storage_key: key, sort_order: j });
        }
        itemPayloads.push({ name: item.name.trim() || undefined, sort_order: i, photos: photoPayloads });
      }

      const loosePayloads: { storage_key: string; sort_order: number }[] = [];
      for (let i = 0; i < loosePhotos.length; i++) {
        const photo = loosePhotos[i];
        setProgress(`まとめ撮影の写真をアップロード中… (${i + 1}/${loosePhotos.length})`);
        let key = photo.uploadedKey;
        if (!key) {
          const presign = await uploadCasePhoto(photo.file, token);
          key = presign.storage_key;
          setLoosePhotos((prev) => prev.map((p) => (p.id === photo.id ? { ...p, uploadedKey: key } : p)));
        }
        loosePayloads.push({ storage_key: key, sort_order: i });
      }

      setProgress("送信しています…");
      // POST /cases は AI 解析の完了を待たずに応答する（背景実行・r6 H-1）。
      // idempotency_key は最初の試行で1度だけ発行し、通信断による再送信でも使い回すことで
      // 同一案件の二重作成を防ぐ。ネットワーク断時のタイムアウトは request() の既定挙動
      // （ブラウザ既定のタイムアウト）に委ねる。
      if (!idempotencyKeyRef.current) {
        idempotencyKeyRef.current = crypto.randomUUID();
      }
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
          items: itemPayloads.length > 0 ? itemPayloads : undefined,
          photos: loosePayloads,
          idempotency_key: idempotencyKeyRef.current,
        },
        token,
      );
      allowLeaveRef.current = true;
      router.push(`/cases/${created.id}?created=1`);
    } catch (err) {
      setError(toDisplayMessage(err, "送信に失敗しました。もう一度お試しください。"));
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

  const isEmptyStep1 = items.length === 0 && loosePhotos.length === 0;
  const looseVisible = showLooseSection || loosePhotos.length > 0;

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
            <div className="auth-error" role="alert" style={{ marginBottom: 16 }}>
              <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                <circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" />
              </svg>
              {error}
            </div>
          )}

          {/* STEP 1: 写真（list モード） */}
          {step === 0 && mode.kind === "list" && (
            <div>
              <h2 className="step-title">片付けたい商品を撮影</h2>
              <p className="step-desc">
                商品を1点ずつ撮影し、撮った商品をまとめて1つのアルバムにします。業者はこのアルバム全体に買取総額で入札するので、商品ごとに写真がそろっているほど正確な見積もりにつながります（商品最大{ITEM_LIMIT}点・案件合計最大{CASE_PHOTO_LIMIT}枚）。
              </p>

              {isEmptyStep1 ? (
                <button type="button" className="item-empty-cta" onClick={addNewItem}>
                  <span className="pd-ic"><Ic name="camera" /></span>
                  <span className="pd-title">＋ 最初の商品を撮影する</span>
                </button>
              ) : (
                <>
                  {items.length > 0 && (
                    <div className="item-list">
                      {items.map((it, idx) => (
                        <div className="item-card" key={it.id}>
                          <div className="item-card-thumb">
                            {it.photos[0] ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={it.photos[0].previewUrl} alt="" />
                            ) : (
                              <Ic name="box" />
                            )}
                          </div>
                          <div className="item-card-info">
                            <p className="item-card-name">{it.name.trim() || `商品 ${idx + 1}`}</p>
                            <p className="item-card-count">{it.photos.length} 枚</p>
                          </div>
                          <div className="item-card-actions">
                            <button type="button" onClick={() => editItem(it.id)}>編集</button>
                            <button type="button" onClick={() => deleteItem(it.id)}>削除</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="item-list-actions">
                    <button
                      type="button"
                      className="btn-add-item"
                      onClick={addNewItem}
                      disabled={items.length >= ITEM_LIMIT || totalPhotoCount >= CASE_PHOTO_LIMIT}
                    >
                      <Ic name="camera" />＋ 商品を追加
                    </button>
                    {!looseVisible && (
                      <button type="button" className="btn-loose-toggle" onClick={() => setShowLooseSection(true)}>
                        まとめて撮る（商品を分けない）
                      </button>
                    )}
                  </div>

                  {looseVisible && (
                    <div className="form-card">
                      <p className="loose-section-title">まとめ撮影（商品を分けない写真）</p>
                      <label className="photo-drop">
                        <span className="pd-ic"><Ic name="camera" /></span>
                        <span className="pd-title">写真を撮影・選択</span>
                        <span className="pd-sub">JPEG / PNG / WebP</span>
                        <input
                          ref={looseInputRef}
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          capture="environment"
                          multiple
                          className="sr-only"
                          onChange={handleLooseFileChange}
                        />
                      </label>
                      {loosePhotos.length > 0 && (
                        <div className="photo-grid">
                          {loosePhotos.map((p) => (
                            <div key={p.id} className="photo-thumb">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img src={p.previewUrl} alt={p.file.name} />
                              <button type="button" className="photo-remove" onClick={() => removeLoosePhoto(p.id)} aria-label={`${p.file.name} を削除`}>
                                <Ic name="x" />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* 撮影の案内と査定のコツ（文言は /photo-guide と同じ根拠に揃える） */}
              <section className="shoot-guide" aria-labelledby="shoot-guide-title">
                <h3 id="shoot-guide-title" className="sg-title">撮影の流れ</h3>
                <ol className="sg-flow">
                  <li><span className="sg-n">1</span><span>「最初の商品を撮影する」を押し、1つの商品を数枚撮る（全体 → 気になる部分のアップ → ロゴ・型番）</span></li>
                  <li><span className="sg-n">2</span><span>「＋ 商品を追加」で次の商品も同じように撮る。撮った商品はすべて1つのアルバム（まとめ）に入ります</span></li>
                  <li><span className="sg-n">3</span><span>全部そろったら「次へ」。業者は商品1点ずつではなく、このアルバム全体に買取総額で入札します</span></li>
                </ol>
                <h3 className="sg-title">査定額が上がる5つのコツ</h3>
                <ul className="sg-tips">
                  <li><b>明るい場所で撮る</b><span>窓際や照明の下で。フラッシュより自然光のほうがきれいに映り、業者が状態を判断しやすくなります。</span></li>
                  <li><b>全体と細部の両方を</b><span>引きの全体写真＋気になる部分のアップ。この組み合わせが最も評価されます。</span></li>
                  <li><b>ロゴ・型番・タグは接写</b><span>メーカーロゴや型番シールが読めると、業者が価格を調べやすく高い入札につながります。</span></li>
                  <li><b>傷・汚れは隠さず撮る</b><span>状態が正確に伝わるほど業者は安心して入札でき、引き取り時のトラブルも防げます。</span></li>
                  <li><b>付属品・電源ON状態も</b><span>箱・リモコン・充電器・説明書があれば一緒に。家電は電源が入った状態の写真があると買取額が変わります。</span></li>
                </ul>
                <p className="sg-more">
                  カテゴリ別のチェックリストは
                  <a href="/photo-guide" target="_blank" rel="noopener noreferrer">撮影ガイド</a>
                  へ（別タブで開きます。撮影中の内容は消えません）。
                </p>
              </section>
            </div>
          )}

          {/* STEP 1: 写真（shoot モード = 商品ごとの撮影） */}
          {step === 0 && mode.kind === "shoot" && currentItem && (
            <div>
              <button type="button" className="step1-back-link" onClick={exitShoot}>
                <Ic name="arrow" style={{ transform: "rotate(180deg)" }} />← 一覧へ戻る
              </button>
              <h2 className="step-title">商品 {currentItemIndex + 1} の写真</h2>
              <p className="step-desc">全方位・傷や汚れのアップを含めて撮影してください。</p>
              <p className="shoot-hint">
                <b>撮る順番:</b> ①明るい場所で全体 → ②傷・汚れのアップ → ③ロゴ・型番・タグ → ④付属品（箱・リモコン・充電器）。家電は電源が入った状態も1枚。
              </p>
              <div className="form-card">
                <div className="field">
                  <label htmlFor="itemName">
                    商品名<span className="opt">任意</span>
                  </label>
                  <input
                    id="itemName"
                    type="text"
                    maxLength={40}
                    value={currentItem.name}
                    onChange={(e) => renameItem(currentItem.id, e.target.value)}
                    placeholder="例: 洗濯機 / ソファ / ゴルフクラブ"
                  />
                  <p className="item-name-warn">
                    <Ic name="lock" />個人情報・連絡先は入力しないでください
                  </p>
                </div>

                <label className="photo-drop">
                  <span className="pd-ic"><Ic name="camera" /></span>
                  <span className="pd-title">写真を撮影・選択</span>
                  <span className="pd-sub">JPEG / PNG / WebP・最大{ITEM_PHOTO_LIMIT}枚</span>
                  <input
                    ref={itemInputRef}
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    capture="environment"
                    multiple
                    className="sr-only"
                    onChange={handleItemFileChange}
                  />
                </label>

                {currentItem.photos.length > 0 && (
                  <div className="photo-grid">
                    {currentItem.photos.map((p) => (
                      <div key={p.id} className="photo-thumb">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={p.previewUrl} alt={p.file.name} />
                        <button
                          type="button"
                          className="photo-remove"
                          onClick={() => removePhotoFromItem(currentItem.id, p.id)}
                          aria-label={`${p.file.name} を削除`}
                        >
                          <Ic name="x" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="photo-quality-hint">
                  <Ic name="spark" />
                  <div className="pqh-body">
                    <p className="pqh-lead"><strong>高評価のコツ：</strong>この3つを意識すると見積もり精度が上がります。</p>
                    <ul className="pqh-checklist">
                      {HINT_ITEMS.map((h) => (
                        <li key={h.key}>
                          <Ic name={h.icon} />{h.label}
                        </li>
                      ))}
                    </ul>
                    <Link href="/photo-guide" className="pqh-more" target="_blank" rel="noopener noreferrer">
                      撮影のコツを詳しく見る<Ic name="arrow" />
                    </Link>
                    {/* 撮影完了の前提となる確認（レ点なしでは「この商品の撮影を完了」を押せない） */}
                    <label className="pqh-confirm">
                      <input
                        type="checkbox"
                        checked={checkedHints.has(`${currentItem.id}:confirm`)}
                        onChange={() => toggleHint(currentItem.id, "confirm")}
                      />
                      <span>商品の状態が正確に確認できる写真を撮影しました</span>
                    </label>
                  </div>
                </div>

                <button type="button" className="item-delete-link" onClick={deleteCurrentItem}>
                  この商品を削除
                </button>
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
                  [
                    "商品・写真",
                    totalItemCount > 0 ? `商品 ${totalItemCount} 点 / 写真 ${totalPhotoCount} 枚` : `写真 ${totalPhotoCount} 枚`,
                  ],
                  ["利用目的", purpose],
                  ["エリア", `${prefecture} ${city}`],
                  ["住所詳細", addressDetail || "（未入力・任意）"],
                  ["住居", `${housingType} / ${floorPlan}`],
                  ["階数・EV", `${floorNumber ? `${floorNumber}階` : "—"} / EV${hasElevator ? "あり" : "なし"}`],
                ].map(([k, v]) => (
                  <div key={k} className="confirm-row"><span className="lbl">{k}</span><span className="val">{v}</span></div>
                ))}
              </div>
              {items.length > 0 && (
                <div className="form-card">
                  <p className="confirm-item-list-title">商品一覧</p>
                  <ul className="confirm-item-list">
                    {items.map((it, idx) => (
                      <li key={it.id}>
                        {it.name.trim() || `商品 ${idx + 1}`}
                        <span className="confirm-item-list-count">{it.photos.length}枚</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="hint-banner">
                <Ic name="lock" className="hint-ic" />
                <span>住所詳細・連絡先は業者決定まで開示されません。査定に回るのは写真・品目・利用目的・地域（都道府県・市区町村）・住居情報などの出品内容のみです。</span>
              </div>
              <div className="hint-banner">
                <Ic name="clock" className="hint-ic" />
                <span>送信後、AIによる写真の解析は案件詳細画面で進みます（通常1〜2分）。この画面での待ち時間はありません。</span>
              </div>
              {submitting && (
                <div className="hint-banner" role="status">
                  <Ic name="clock" className="hint-ic" />
                  <span>送信しています…この画面を閉じないでください。</span>
                </div>
              )}
            </div>
          )}
        </div>
      </main>

      {/* flow-footer */}
      <div className="flow-footer">
        <div className="inner">
          {step === 0 && mode.kind === "shoot" ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
              <button
                type="button"
                className="btn-flow-next"
                onClick={exitShoot}
                disabled={!currentItem || currentItem.photos.length === 0 || !checkedHints.has(`${currentItem.id}:confirm`)}
                title={currentItem && currentItem.photos.length > 0 && !checkedHints.has(`${currentItem.id}:confirm`) ? "「商品の状態が正確に確認できる写真を撮影しました」にチェックを入れてください" : undefined}
              >
                この商品の撮影を完了<Ic name="arrow" />
              </button>
              {currentItem && currentItem.photos.length === 0 ? (
                <p className="field-error" style={{ margin: 0 }} role="status">
                  写真を1枚以上追加してください
                </p>
              ) : currentItem && !checkedHints.has(`${currentItem.id}:confirm`) ? (
                <p className="field-error" style={{ margin: 0 }} role="status">
                  上の確認にチェックを入れると進めます
                </p>
              ) : null}
            </div>
          ) : (
            <>
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
            </>
          )}
        </div>
      </div>

      {/* 離脱確認モーダル（ブラウザバック検知時。beforeunload はブラウザ標準ダイアログに委ねる） */}
      {leaveConfirmOpen && (
        <div
          className="leave-modal-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) cancelLeave();
          }}
        >
          <div className="leave-modal" role="dialog" aria-modal="true" aria-label="ページを離れる確認">
            <h3>入力中の内容が失われます</h3>
            <p>
              撮影した写真・商品情報はまだ送信されていません。このままページを離れると、入力内容がすべて失われます。
            </p>
            <div className="leave-modal-actions">
              <button type="button" className="btn-flow-back" onClick={confirmLeave}>
                ページを離れる
              </button>
              <button type="button" className="btn-flow-next" onClick={cancelLeave}>
                入力を続ける
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
