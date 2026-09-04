"use client";

/**
 * ユーザー: 案件詳細。
 * - 入札一覧の確認と 1 社選択（落札確定）
 * - 成約後: 減額申請への承認/却下、完了確定、キャンセル、レビュー投稿
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Icon, Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { ConfirmModal } from "@/components/kdz/ConfirmModal";
import { formatVisitSchedule } from "@/lib/categories";
import { formatPurposeLabel } from "@/lib/case-labels";
import {
  Card,
  Notice,
  StatusBadge,
  btnDanger,
  btnPrimary,
  btnSecondary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import {
  CANCELLED_BY_LABEL,
  CASE_ITEM_CONDITION_LABEL,
  CASE_STATUS_LABEL,
  REDUCTION_STATUS_LABEL,
  TXN_STATUS_LABEL,
  addCaseItemPhoto,
  cancelCase,
  cancelTransaction,
  completeTransaction,
  createReview,
  decideReduction,
  deleteCaseItem,
  deleteCasePhoto,
  formatYen,
  getCase,
  getTransaction,
  listBids,
  photoSrc,
  selectBid,
  toAlbums,
  toDisplayMessage,
  updateCaseItem,
  uploadCasePhoto,
  type BidOut,
  type CaseItemOut,
  type CaseOut,
  type TransactionDetail,
} from "@/lib/katadzuke-api";

/** 編集/削除UIを許可する案件ステータス（それ以外は409になるためバックエンドと同条件でUIも隠す）。 */
const EDITABLE_CASE_STATUSES = new Set(["draft", "open"]);

/** 出品取り下げを許可する案件ステータス（backend の cancel_case と同条件）。 */
const CANCELLABLE_CASE_STATUSES = new Set(["open", "bidding"]);

/** window.confirm の代わりに表示する ConfirmModal の内容（r8-fix-frontend）。 */
type ConfirmState = {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
} | null;

export default function UserCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const caseId = params.id;
  const { token, loading } = useToken();

  const [caseData, setCaseData] = useState<CaseOut | null>(null);
  const [bids, setBids] = useState<BidOut[]>([]);
  const [txn, setTxn] = useState<TransactionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** AI解析ポーリングが打ち切り時間（backend の遅延回収窓=10分）に達したかどうか。 */
  const [aiPollTimedOut, setAiPollTimedOut] = useState(false);
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);

  // ===== 商品の編集/削除・写真の追加/削除 =====
  // busyOps は進行中の操作キー集合。キー形式は "item:{itemId}:save" / "item:{itemId}:delete" /
  // "item:{itemId}:upload" / "photo:{photoId}:delete"。Set にすることで、ある商品カードの操作中でも
  // 別の商品カードのボタンは disabled にならない（商品単位の排他制御。カード内の disabled 表示と
  // 実際の排他範囲を一致させる）。
  const [busyOps, setBusyOps] = useState<Set<string>>(new Set());
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editCondition, setEditCondition] = useState<string>("unknown");
  const [editDescription, setEditDescription] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [uploadTargetItemId, setUploadTargetItemId] = useState<string | null>(null);
  const addPhotoInputRef = useRef<HTMLInputElement>(null);

  const canEditCase = caseData != null && EDITABLE_CASE_STATUSES.has(caseData.status);
  const canCancelCase =
    caseData != null && !txn && CANCELLABLE_CASE_STATUSES.has(caseData.status);

  function beginOp(key: string) {
    setBusyOps((prev) => new Set(prev).add(key));
  }
  function endOp(key: string) {
    setBusyOps((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  }
  /** 指定した商品に対する編集/削除/写真アップロードのいずれかが進行中か（同一商品内の操作競合を防ぐ）。 */
  function isItemBusy(itemId: string): boolean {
    const prefix = `item:${itemId}:`;
    for (const key of busyOps) {
      if (key.startsWith(prefix)) return true;
    }
    return false;
  }

  function startEditItem(item: CaseItemOut) {
    setEditingItemId(item.id);
    setEditName(item.name ?? item.ai_detected_name ?? "");
    setEditCondition(item.user_condition ?? item.ai_condition ?? "unknown");
    setEditDescription(item.user_description ?? item.ai_summary ?? "");
    setEditError(null);
  }

  function cancelEditItem() {
    setEditingItemId(null);
    setEditError(null);
  }

  async function saveEditItem(item: CaseItemOut) {
    if (!token || isItemBusy(item.id)) return;
    const key = `item:${item.id}:save`;
    beginOp(key);
    setEditError(null);
    try {
      await updateCaseItem(
        caseId,
        item.id,
        {
          name: editName.trim() || null,
          user_condition: editCondition,
          user_description: editDescription.trim() || null,
        },
        token,
      );
      await reload();
      setEditingItemId(null);
    } catch (e) {
      setEditError(toDisplayMessage(e, "保存に失敗しました"));
    } finally {
      endOp(key);
    }
  }

  /** 編集内容を破棄し、AI推定値（ai_condition/ai_summary）へ戻す。商品名は変更しない。 */
  function resetEditItemToAi(item: CaseItemOut) {
    if (!token || isItemBusy(item.id)) return;
    setConfirmState({
      title: "AIの推定値に戻しますか？",
      message: "状態・説明の編集内容を破棄して、AIの推定値に戻しますか？",
      confirmLabel: "リセットする",
      onConfirm: () => {
        setConfirmState(null);
        void performResetEditItemToAi(item);
      },
    });
  }

  async function performResetEditItemToAi(item: CaseItemOut) {
    if (!token || isItemBusy(item.id)) return;
    const key = `item:${item.id}:reset`;
    beginOp(key);
    setEditError(null);
    try {
      await updateCaseItem(
        caseId,
        item.id,
        {
          name: editName.trim() || null,
          user_condition: null,
          user_description: null,
        },
        token,
      );
      await reload();
      setEditingItemId(null);
    } catch (e) {
      setEditError(toDisplayMessage(e, "リセットに失敗しました"));
    } finally {
      endOp(key);
    }
  }

  function handleDeleteItem(item: CaseItemOut) {
    if (!token || isItemBusy(item.id)) return;
    setConfirmState({
      title: "商品を削除しますか？",
      message: "この商品を削除しますか？紐づく写真も削除されます。",
      confirmLabel: "削除する",
      danger: true,
      onConfirm: () => {
        setConfirmState(null);
        void performDeleteItem(item);
      },
    });
  }

  async function performDeleteItem(item: CaseItemOut) {
    if (!token || isItemBusy(item.id)) return;
    const key = `item:${item.id}:delete`;
    beginOp(key);
    setError(null);
    try {
      await deleteCaseItem(caseId, item.id, token);
      if (editingItemId === item.id) setEditingItemId(null);
      await reload();
    } catch (e) {
      setError(toDisplayMessage(e, "商品の削除に失敗しました"));
    } finally {
      endOp(key);
    }
  }

  function handleDeletePhoto(photoId: string) {
    if (!token) return;
    const key = `photo:${photoId}:delete`;
    if (busyOps.has(key)) return;
    setConfirmState({
      title: "写真を削除しますか？",
      message: "この写真を削除しますか？",
      confirmLabel: "削除する",
      danger: true,
      onConfirm: () => {
        setConfirmState(null);
        void performDeletePhoto(photoId);
      },
    });
  }

  async function performDeletePhoto(photoId: string) {
    if (!token) return;
    const key = `photo:${photoId}:delete`;
    if (busyOps.has(key)) return;
    beginOp(key);
    setError(null);
    try {
      await deleteCasePhoto(caseId, photoId, token);
      await reload();
    } catch (e) {
      setError(toDisplayMessage(e, "写真の削除に失敗しました"));
    } finally {
      endOp(key);
    }
  }

  function triggerAddPhoto(itemId: string) {
    if (isItemBusy(itemId)) return;
    setUploadTargetItemId(itemId);
    addPhotoInputRef.current?.click();
  }

  async function handleAddPhotoFilesSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    const itemId = uploadTargetItemId;
    setUploadTargetItemId(null);
    if (files.length === 0 || !itemId || !token) return;
    const key = `item:${itemId}:upload`;
    beginOp(key);
    setError(null);
    // 途中の1枚が失敗しても、それまでに保存済みの写真を「消えたように見せない」ため
    // reload() は成否に関わらず必ず finally で実行する（QA指摘対応）。
    let succeeded = 0;
    try {
      const currentItem = caseData?.items?.find((it) => it.id === itemId);
      let nextSortOrder = currentItem?.photos.length ?? 0;
      for (const file of files) {
        const presign = await uploadCasePhoto(file, token);
        await addCaseItemPhoto(caseId, itemId, { storage_key: presign.storage_key, sort_order: nextSortOrder }, token);
        nextSortOrder += 1;
        succeeded += 1;
      }
    } catch (err) {
      const failedCount = files.length - succeeded;
      setError(
        files.length > 1
          ? `${files.length}枚中${failedCount}枚の追加に失敗しました。時間をおいて再度お試しください。`
          : toDisplayMessage(err, "写真の追加に失敗しました"),
      );
    } finally {
      await reload();
      endOp(key);
    }
  }

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      const c = await getCase(caseId, token);
      setCaseData(c);
      const b = await listBids(caseId, token);
      setBids(b);
      const selected = b.find((x) => x.status === "selected");
      if (selected?.transaction_id) {
        setTxn(await getTransaction(selected.transaction_id, token));
      }
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [caseId, token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // AI 解析は backend 側で背景実行される（r6 H-1）。ai_status==="pending" の間は
  // 最初の3分は3秒間隔、それ以降は15秒間隔でポーリングし、"done"/"failed" に遷移したら
  // （依存配列の変化で）自動的に止まる。backend の遅延回収窓（stale pending の10分後
  // 自動回収）に合わせ、10分を超えたら自動更新を打ち切り「再読み込み」導線を表示する。
  useEffect(() => {
    if (!token || caseData?.ai_status !== "pending") return;
    setAiPollTimedOut(false);
    const startedAt = Date.now();
    const FAST_POLL_MS = 3000;
    const SLOW_POLL_MS = 15_000;
    const FAST_WINDOW_MS = 180_000; // 3分
    const MAX_MS = 600_000; // 10分（backend _AI_STALE_PENDING_WINDOW と一致）
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      const elapsed = Date.now() - startedAt;
      if (elapsed > MAX_MS) {
        if (!cancelled) setAiPollTimedOut(true);
        return;
      }
      try {
        const c = await getCase(caseId, token);
        if (!cancelled) setCaseData(c);
      } catch {
        // ポーリング中の一時的な失敗は無視し、次回の間隔で再試行する。
      }
      if (!cancelled) {
        timer = setTimeout(tick, elapsed < FAST_WINDOW_MS ? FAST_POLL_MS : SLOW_POLL_MS);
      }
    };
    timer = setTimeout(tick, FAST_POLL_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [token, caseId, caseData?.ai_status]);

  async function act(fn: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(toDisplayMessage(e, "操作に失敗しました"));
      // 409（他の操作と競合）等で失敗した場合も、画面が古い状態のまま残らないよう最新化する。
      await reload();
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!caseData && !error)) {
    return (
      <>
        <AppHeader />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </>
    );
  }

  if (!caseData) {
    return (
      <>
        <AppHeader />
        <div className="container-aw max-w-3xl py-10">
          <Notice tone="error">{error ?? "案件が見つかりません。"}</Notice>
        </div>
      </>
    );
  }

  // 取り下げ済み等の非アクティブな入札は依頼者側に完全非表示にする（再入札不可の設計に合わせ、
  // 「決める」対象になり得ない入札を一覧・件数・空状態のいずれからも除外する）。
  const activeBids = bids.filter((b) => b.status === "pending");
  const topBidAmount = activeBids.length > 0 ? Math.max(...activeBids.map((b) => b.amount)) : null;
  const topBidCount = activeBids.filter((b) => b.amount === topBidAmount).length;
  const pendingReduction = txn?.reduction_requests.find((r) => r.status === "pending");
  const myReview = txn?.reviews.find((r) => r.reviewer_type === "user");

  return (
    <>
    <AppHeader />
    <div className="container-aw max-w-3xl space-y-6 py-10">
      {search.get("created") ? (
        <Notice tone="success">
          依頼を受け付けました。業者から入札が届くと、LINE連携済みの方はLINEで、未連携の方はメールでお知らせします。
        </Notice>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}

      {/* ===== 案件情報 ===== */}
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-normal text-slate-900">{formatPurposeLabel(caseData.purpose)}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {caseData.prefecture} {caseData.city}
              {caseData.address_detail ? ` ${caseData.address_detail}` : ""}
            </p>
            <p className="mt-0.5 text-xs text-slate-400">
              {caseData.housing_type ?? "—"} / {caseData.floor_plan ?? "—"} /{" "}
              {caseData.floor_number != null ? `${caseData.floor_number}階` : "—"} / EV
              {caseData.has_elevator == null ? "—" : caseData.has_elevator ? "あり" : "なし"}
            </p>
          </div>
          <StatusBadge value={caseData.status} label={CASE_STATUS_LABEL[caseData.status]} />
          {caseData.status === "cancelled" ? (
            <div className="mt-3 w-full rounded-none border border-slate-200 bg-slate-50 p-3 text-sm leading-relaxed text-slate-600" role="status">
              {/* r8-fix-frontend2 M2/ADD-1 是正: 成約後キャンセル（txn が存在）と
                  出品の取り下げ（txn が存在しない）で経緯が異なるため文言を分岐する。
                  従来は成約キャンセルにも「取り下げ済み」「入札を自動でお断り」という
                  事実に反する文言が出ていた。 */}
              {txn
                ? "取引はキャンセルされました。必要であれば新しく出品してください。"
                : "この出品は取り下げ済みです。届いていた入札はすべて自動でお断りになりました。再度依頼する場合は「出品する」から新しく出品してください。"}
            </div>
          ) : null}
        </div>

        {toAlbums(caseData).map((album) => {
          const item = album.id ? (caseData.items?.find((it) => it.id === album.id) ?? null) : null;
          const isEditing = item != null && editingItemId === item.id;
          const isSavingItem = item != null && busyOps.has(`item:${item.id}:save`);
          const isResettingItem = item != null && busyOps.has(`item:${item.id}:reset`);
          const isDeletingItem = item != null && busyOps.has(`item:${item.id}:delete`);
          const isUploadingItem = item != null && busyOps.has(`item:${item.id}:upload`);
          const itemAnyBusy = item != null && isItemBusy(item.id);
          // AI推定値そのものが無ければ「AI推定に戻す」を出しても戻す先が無いため無効化する。
          const hasAiFallback = item != null && (item.ai_condition != null || item.ai_summary != null);

          return (
            <div key={album.id ?? "unassigned"} className="mt-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  {album.title ? (
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-normal text-slate-900">{album.title}</p>
                      {album.condition ? (
                        <span className="rounded-none bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand-700">
                          {CASE_ITEM_CONDITION_LABEL[album.condition] ?? album.condition}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  {album.description ? (
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{album.description}</p>
                  ) : null}
                </div>
                {item && canEditCase && !isEditing ? (
                  <button
                    type="button"
                    disabled={itemAnyBusy}
                    onClick={() => startEditItem(item)}
                    className={btnSecondary}
                  >
                    編集
                  </button>
                ) : null}
              </div>

              {isEditing && item ? (
                <div className="mt-2 space-y-3 rounded-none border border-slate-200 bg-slate-50 p-4">
                  {editError ? <p className="text-xs font-semibold text-red-600">{editError}</p> : null}
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-500">商品名</label>
                    <input
                      type="text"
                      maxLength={40}
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      placeholder="例: 洗濯機 / ソファ"
                      className={inputBase}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-500">状態</label>
                    <select
                      value={editCondition}
                      onChange={(e) => setEditCondition(e.target.value)}
                      className={inputBase}
                    >
                      {Object.entries(CASE_ITEM_CONDITION_LABEL).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-500">説明</label>
                    <textarea
                      value={editDescription}
                      maxLength={500}
                      onChange={(e) => setEditDescription(e.target.value)}
                      rows={3}
                      className={inputBase}
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={isSavingItem || isResettingItem}
                      onClick={() => saveEditItem(item)}
                      className={btnPrimary}
                    >
                      {isSavingItem ? "保存中…" : "保存"}
                    </button>
                    <button
                      type="button"
                      disabled={isSavingItem || isResettingItem}
                      onClick={cancelEditItem}
                      className={btnSecondary}
                    >
                      キャンセル
                    </button>
                    {hasAiFallback ? (
                      <button
                        type="button"
                        disabled={isSavingItem || isResettingItem}
                        onClick={() => resetEditItemToAi(item)}
                        className="inline-flex items-center text-sm font-semibold text-slate-500 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isResettingItem ? "リセット中…" : "AI推定に戻す"}
                      </button>
                    ) : null}
                  </div>
                </div>
              ) : null}

              <ul className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
                {album.photos.map((p) => {
                  const isDeletingPhoto = busyOps.has(`photo:${p.id}:delete`);
                  return (
                    <li key={p.id} className="group relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={photoSrc(p.url)}
                        alt=""
                        className="aspect-square w-full rounded-none border border-slate-200 object-cover"
                      />
                      {canEditCase ? (
                        <button
                          type="button"
                          aria-label="この写真を削除"
                          disabled={isDeletingPhoto}
                          onClick={() => handleDeletePhoto(p.id)}
                          className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-slate-900/70 text-white opacity-0 transition-opacity focus:opacity-100 disabled:opacity-100 group-hover:opacity-100"
                        >
                          {isDeletingPhoto ? (
                            <Spinner className="h-3 w-3" />
                          ) : (
                            <Icon name="close" className="h-3.5 w-3.5" strokeWidth={2.5} />
                          )}
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>

              {item && canEditCase ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={itemAnyBusy}
                    onClick={() => triggerAddPhoto(item.id)}
                    className={btnSecondary}
                  >
                    {isUploadingItem ? "アップロード中…" : "＋ 写真を追加"}
                  </button>
                  <button
                    type="button"
                    disabled={itemAnyBusy}
                    onClick={() => handleDeleteItem(item)}
                    className={btnDanger}
                  >
                    {isDeletingItem ? "削除中…" : "商品を削除"}
                  </button>
                </div>
              ) : null}
            </div>
          );
        })}

        <input
          ref={addPhotoInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          className="hidden"
          onChange={handleAddPhotoFilesSelected}
        />

        {caseData.ai_status === "pending" && aiPollTimedOut ? (
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-none bg-slate-50 p-4" role="status">
            <p className="text-sm leading-relaxed text-slate-600">
              解析に時間がかかっています。ページを再読み込みしてください。
            </p>
            <button type="button" onClick={() => window.location.reload()} className={btnSecondary}>
              再読み込み
            </button>
          </div>
        ) : caseData.ai_status === "pending" ? (
          <div className="mt-4 flex items-center gap-2 rounded-none bg-slate-50 p-4" role="status">
            <Spinner className="h-4 w-4 text-brand-600" />
            <p className="text-sm leading-relaxed text-slate-600">
              AI が写真を解析中です（通常1〜2分）。この画面は自動で更新されます。
            </p>
          </div>
        ) : caseData.ai_status === "failed" ? (
          <div className="mt-4 rounded-none bg-slate-50 p-4">
            <p className="text-sm leading-relaxed text-slate-600">
              AI 要約を作成できませんでした。写真と入力内容で入札を受け付けます。
            </p>
          </div>
        ) : caseData.ai_summary ? (
          <div className="mt-4 rounded-none bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              AI 要約（業者に提示されます）
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-700">
              {caseData.ai_summary}
            </p>
          </div>
        ) : null}
      </Card>

      {/* ===== 入札一覧 ===== */}
      {!txn && caseData.status !== "cancelled" && (
        <Card>
          <h2 className="font-normal text-slate-900">入札一覧（{activeBids.length} 件）</h2>
          {activeBids.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">
              まだ入札がありません。入札が届くと、LINE連携済みの方はLINEで、未連携の方はメールでお知らせします。
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {activeBids.map((b) => (
                <li
                  key={b.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-none border border-slate-200 p-4"
                >
                  <div>
                    <p className="font-normal text-slate-900">
                      {b.operator?.company_name ?? "業者"}
                      {b.operator?.rating != null ? (
                        <span className="ml-2 text-xs font-semibold text-amber-600">
                          ★ {b.operator.rating.toFixed(1)}
                          <span className="ml-1 font-normal text-slate-500">
                            （口コミ{b.operator.review_count}件）
                          </span>
                        </span>
                      ) : (
                        <span className="ml-2 text-xs text-slate-500">口コミはまだありません</span>
                      )}
                      {topBidAmount != null && b.amount === topBidAmount && activeBids.length > 1 ? (
                        <span className="ml-2 rounded-none bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand-700">
                          {topBidCount > 1 ? "同額で最高額" : "最高額"}
                        </span>
                      ) : null}
                    </p>
                    {b.operator ? (
                      <Link
                        href={`/vendors/${b.operator.id}`}
                        className="mt-0.5 inline-block text-xs font-semibold text-brand-700 underline underline-offset-2"
                      >
                        業者のプロフィール・口コミを見る
                      </Link>
                    ) : null}
                    {b.operator?.latest_review_comment ? (
                      <p className="mt-1 max-w-md text-xs leading-relaxed text-slate-500">
                        最新の口コミ: 「{b.operator.latest_review_comment}」
                      </p>
                    ) : null}
                    <p className="mt-0.5 text-lg font-semibold text-brand-700 tabular-nums">
                      {formatYen(b.amount)}
                    </p>
                    {b.message ? (
                      <p className="mt-1 max-w-md text-sm leading-relaxed text-slate-600">
                        {b.message}
                      </p>
                    ) : null}
                    {b.operator_suspended ? (
                      <p className="mt-2 max-w-md text-xs font-semibold leading-relaxed text-red-600" role="alert">
                        この業者は現在利用停止中です。運営（<Link href="/contact" className="underline">/contact</Link>）にお問い合わせください。
                      </p>
                    ) : null}
                  </div>
                  {/* 一覧は activeBids（pending のみ）だが、多層防御として描画直前にも再確認する。 */}
                  {b.status === "pending" ? (
                    <button
                      type="button"
                      disabled={busy || b.operator_suspended}
                      title={b.operator_suspended ? "この業者は現在利用停止中のため選択できません" : undefined}
                      onClick={() =>
                        setConfirmState({
                          title: "この業者に決定しますか？",
                          message: `${b.operator?.company_name ?? "この業者"}（${formatYen(b.amount)}）に決定しますか？決定後、業者へ住所詳細が開示されます。`,
                          confirmLabel: "決定する",
                          onConfirm: () => {
                            setConfirmState(null);
                            void act(() => selectBid(caseId, b.id, token!));
                          },
                        })
                      }
                      className={btnPrimary}
                    >
                      この業者に決める
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {canCancelCase ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (!token) return;
                  // prompt の「キャンセル」（null）は取り下げ自体の中止。空文字は理由なしで続行。
                  const reason = window.prompt("取り下げ理由（任意）");
                  if (reason === null) return;
                  setConfirmState({
                    title: "出品を取り下げますか？",
                    message: "出品を取り下げますか？付いている入札はすべて無効になり、元に戻せません。",
                    confirmLabel: "取り下げる",
                    danger: true,
                    onConfirm: () => {
                      setConfirmState(null);
                      void act(() => cancelCase(caseId, reason === "" ? null : reason, token));
                    },
                  });
                }}
                className={`mt-4 ${btnDanger}`}
              >
                出品を取り下げる
              </button>
              <p className="mt-2 text-xs text-slate-400">
                ※ 業者決定後の取消は取引画面の「キャンセル」から行えます。
              </p>
            </>
          ) : null}
        </Card>
      )}

      {/* ===== 成約パネル ===== */}
      {txn && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-normal text-slate-900">
                成約: {txn.operator?.company_name ?? "業者"}
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                落札額 {formatYen(txn.initial_amount)}
                {txn.final_amount != null && txn.final_amount !== txn.initial_amount
                  ? ` → 確定額 ${formatYen(txn.final_amount)}`
                  : ""}
              </p>
              {txn.contact_email ? (
                <p className="mt-0.5 text-xs text-slate-400">
                  業者連絡先: {txn.contact_email}
                </p>
              ) : null}
            </div>
            <StatusBadge value={txn.status} label={TXN_STATUS_LABEL[txn.status]} />
          </div>

          {txn.operator_deleted ? (
            <div className="mt-3 rounded-none border border-red-200 bg-red-50 p-3 text-sm leading-relaxed text-red-700" role="alert">
              この業者は退会したため、この取引は進められません。キャンセルして新しく出品してください
            </div>
          ) : txn.operator_suspended ? (
            <div className="mt-3 rounded-none border border-red-200 bg-red-50 p-3 text-sm leading-relaxed text-red-700" role="alert">
              この業者は現在利用停止中です。運営（
              <Link href="/contact" className="underline">
                /contact
              </Link>
              ）にお問い合わせください。
            </div>
          ) : null}

          {/* r8-fix-frontend2 H2 是正: キャンセルの理由が相手方に一切届かなかった問題への対応。
              誰が・なぜ・いつキャンセルしたかを表示する。 */}
          {txn.cancellation ? (
            <div className="mt-3 rounded-none border border-slate-200 bg-slate-50 p-3 text-sm leading-relaxed text-slate-700" role="status">
              <p className="font-semibold text-slate-900">
                キャンセル: {CANCELLED_BY_LABEL[txn.cancellation.cancelled_by]}による
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {new Date(txn.cancellation.cancelled_at).toLocaleString("ja-JP")}
              </p>
              {txn.cancellation.reason ? (
                <p className="mt-1 break-words">理由: {txn.cancellation.reason}</p>
              ) : (
                <p className="mt-1 text-slate-400">理由の記載なし</p>
              )}
            </div>
          ) : null}

          {/* 業者とのやり取り導線（チャット/日程調整）。r8-fix-frontend5 対応:
              業者退会時はチャット送信・日程調整に進めないため導線ごと非表示にする。 */}
          {txn.status !== "cancelled" && !txn.operator_deleted && (
            <div className="mt-4 flex flex-wrap gap-2">
              <a href={`/chat/${txn.id}`} className={btnPrimary}>
                業者とチャット
                {txn.unread_count > 0 ? `（未読${txn.unread_count}）` : ""}
              </a>
              {txn.status === "pending" && txn.visit_date == null ? (
                <a href={`/schedule?transaction_id=${txn.id}`} className={btnSecondary}>
                  訪問日程を調整する
                </a>
              ) : null}
              {txn.visit_date ? (
                <p className="self-center text-sm font-semibold text-slate-600">
                  訪問予定: {formatVisitSchedule(txn.visit_date, txn.visit_time_slot)}
                </p>
              ) : null}
              {txn.operator_suspended ? (
                <p className="w-full text-xs font-semibold text-red-600">
                  ※ 業者が対応できないため、チャット送信・日程調整の返信が届かない場合があります。
                </p>
              ) : null}
            </div>
          )}

          {/* 減額申請の履歴（承認・却下済みを含む全件。r6-flow M-4 対応。
              ラベル定義は operator/transactions/[id]/page.tsx と共通の
              REDUCTION_STATUS_LABEL（lib/katadzuke-api.ts）を使う。 */}
          {txn.reduction_requests.length > 0 && (
            <div className="mt-4">
              <p className="text-sm font-normal text-slate-900">減額申請の履歴</p>
              <ul className="mt-2 space-y-2">
                {txn.reduction_requests.map((r) => (
                  <li
                    key={r.id}
                    className="rounded-none border border-slate-200 p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-slate-900">
                        {formatYen(r.original_amount)} → {formatYen(r.requested_amount)}
                      </span>
                      <StatusBadge value={r.status} label={REDUCTION_STATUS_LABEL[r.status]} />
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-slate-600">理由: {r.reason}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 減額申請（承認待ち） */}
          {pendingReduction && (
            <div className="mt-4 rounded-none border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-semibold text-amber-900">業者から減額申請が届いています</p>
              <p className="mt-1 text-sm text-amber-800">
                {formatYen(pendingReduction.original_amount)} →{" "}
                <strong>{formatYen(pendingReduction.requested_amount)}</strong>
              </p>
              <p className="mt-2 rounded-none bg-white/70 p-3 text-sm leading-relaxed text-slate-700">
                理由: {pendingReduction.reason}
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    setConfirmState({
                      title: "減額を承認しますか？",
                      message: "減額を承認しますか？確定額が更新されます。",
                      confirmLabel: "承認する",
                      onConfirm: () => {
                        setConfirmState(null);
                        void act(() => decideReduction(txn.id, pendingReduction.id, "approve", token!));
                      },
                    })
                  }
                  className={btnPrimary}
                >
                  承認する
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    setConfirmState({
                      title: "減額申請を却下しますか？",
                      message: "減額申請を却下しますか？この操作は元に戻せません。",
                      confirmLabel: "却下する",
                      danger: true,
                      onConfirm: () => {
                        setConfirmState(null);
                        void act(() => decideReduction(txn.id, pendingReduction.id, "reject", token!));
                      },
                    })
                  }
                  className={btnSecondary}
                >
                  却下する
                </button>
              </div>
            </div>
          )}

          {/* 完了・キャンセル */}
          {(txn.status === "pending" || txn.status === "visiting") && (
            <div className="mt-4 flex flex-wrap gap-2">
              {/* r8-fix-frontend5 対応: 業者退会時は完了確定に進めないため非表示にし、
                  キャンセルボタンのみ残す。 */}
              {!txn.operator_deleted ? (
                <button
                  type="button"
                  disabled={busy || Boolean(pendingReduction)}
                  onClick={() =>
                    setConfirmState({
                      title: "作業完了を確定しますか？",
                      message: "作業の完了を確定しますか？確定後はレビューを投稿できます。",
                      confirmLabel: "確定する",
                      onConfirm: () => {
                        setConfirmState(null);
                        void act(() => completeTransaction(txn.id, token!));
                      },
                    })
                  }
                  className={btnPrimary}
                >
                  作業完了を確定する
                </button>
              ) : null}
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const reason = window.prompt("キャンセル理由（任意）") ?? null;
                  setConfirmState({
                    title: "本当にキャンセルしますか？",
                    message: "本当にキャンセルしますか？案件ごと終了し、入札は戻せません。理由は業者に共有されます。",
                    confirmLabel: "キャンセルする",
                    danger: true,
                    onConfirm: () => {
                      setConfirmState(null);
                      void act(() => cancelTransaction(txn.id, reason, token!));
                    },
                  });
                }}
                className={btnDanger}
              >
                キャンセル
              </button>
            </div>
          )}
          {pendingReduction ? (
            <p className="mt-2 text-xs text-slate-400">
              ※ 減額申請への回答後に完了確定できます。
            </p>
          ) : null}

          {/* レビュー */}
          {txn.status === "completed" &&
            (myReview ? (
              <Notice tone="success">
                レビュー投稿済み（★{myReview.rating}）ありがとうございました。
              </Notice>
            ) : (
              <div className="mt-4 rounded-none border border-slate-200 p-4">
                <p className="font-normal text-slate-900">業者を評価する</p>
                <div className="mt-2 flex gap-1">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setRating(n)}
                      aria-label={`星${n}`}
                      className={`text-2xl ${n <= rating ? "text-amber-400" : "text-slate-300"}`}
                    >
                      ★
                    </button>
                  ))}
                </div>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  className={`${inputBase} mt-3`}
                  rows={3}
                  placeholder="対応の感想（任意）"
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    act(() =>
                      createReview(
                        {
                          transaction_id: txn.id,
                          rating,
                          comment: comment.trim() || undefined,
                        },
                        token!,
                      ),
                    )
                  }
                  className={`${btnPrimary} mt-3`}
                >
                  レビューを投稿
                </button>
                <Link
                  href={`/review?transaction_id=${txn.id}`}
                  className="mt-2 inline-block text-sm font-semibold text-brand-700 hover:underline"
                >
                  詳しく評価する →
                </Link>
              </div>
            ))}
        </Card>
      )}

      <Link href="/cases" className="inline-block text-sm font-semibold text-brand-700 hover:underline">
        ← マイ案件一覧へ
      </Link>
    </div>
    {confirmState ? (
      <ConfirmModal
        title={confirmState.title}
        message={confirmState.message}
        confirmLabel={confirmState.confirmLabel}
        danger={confirmState.danger}
        busy={busy}
        onCancel={() => setConfirmState(null)}
        onConfirm={confirmState.onConfirm}
      />
    ) : null}
    </>
  );
}
