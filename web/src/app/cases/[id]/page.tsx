"use client";

/**
 * ユーザー: 案件詳細。
 * - 入札一覧の確認と 1 社選択（落札確定）
 * - 成約後: 減額申請への承認/却下、完了確定、キャンセル、レビュー投稿
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Icon, Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
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
  CASE_ITEM_CONDITION_LABEL,
  CASE_STATUS_LABEL,
  TXN_STATUS_LABEL,
  addCaseItemPhoto,
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
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");

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
  async function resetEditItemToAi(item: CaseItemOut) {
    if (!token || isItemBusy(item.id)) return;
    if (!window.confirm("状態・説明の編集内容を破棄して、AIの推定値に戻しますか？")) return;
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

  async function handleDeleteItem(item: CaseItemOut) {
    if (!token || isItemBusy(item.id)) return;
    if (!window.confirm("この商品を削除しますか？紐づく写真も削除されます。")) return;
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

  async function handleDeletePhoto(photoId: string) {
    if (!token) return;
    const key = `photo:${photoId}:delete`;
    if (busyOps.has(key)) return;
    if (!window.confirm("この写真を削除しますか？")) return;
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

  async function act(fn: () => Promise<unknown>, confirmMsg?: string) {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
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
  const pendingReduction = txn?.reduction_requests.find((r) => r.status === "pending");
  const myReview = txn?.reviews.find((r) => r.reviewer_type === "user");

  return (
    <>
    <AppHeader />
    <div className="container-aw max-w-3xl space-y-6 py-10">
      {search.get("created") ? (
        <Notice tone="success">
          依頼を受け付けました。業者から入札が届くとメールでお知らせします。
        </Notice>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}

      {/* ===== 案件情報 ===== */}
      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-normal text-slate-900">{caseData.purpose}</h1>
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

        {caseData.ai_summary ? (
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
              まだ入札がありません。入札が届くとメールでお知らせします。
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
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-0.5 text-lg font-semibold text-brand-700 tabular-nums">
                      {formatYen(b.amount)}
                    </p>
                    {b.message ? (
                      <p className="mt-1 max-w-md text-sm leading-relaxed text-slate-600">
                        {b.message}
                      </p>
                    ) : null}
                  </div>
                  {/* 一覧は activeBids（pending のみ）だが、多層防御として描画直前にも再確認する。 */}
                  {b.status === "pending" ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        act(
                          () => selectBid(caseId, b.id, token!),
                          `${b.operator?.company_name ?? "この業者"}（${formatYen(b.amount)}）に決定しますか？\n決定後、業者へ住所詳細が開示されます。`,
                        )
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

          {/* 業者とのやり取り導線（チャット/日程調整） */}
          {txn.status !== "cancelled" && (
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
                  訪問予定: {txn.visit_date}
                  {txn.visit_time_slot ? ` ${txn.visit_time_slot}` : ""}
                </p>
              ) : null}
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
                    act(
                      () => decideReduction(txn.id, pendingReduction.id, "approve", token!),
                      "減額を承認しますか？確定額が更新されます。",
                    )
                  }
                  className={btnPrimary}
                >
                  承認する
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    act(() => decideReduction(txn.id, pendingReduction.id, "reject", token!))
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
              <button
                type="button"
                disabled={busy || Boolean(pendingReduction)}
                onClick={() =>
                  act(
                    () => completeTransaction(txn.id, token!),
                    "作業の完了を確定しますか？確定後はレビューを投稿できます。",
                  )
                }
                className={btnPrimary}
              >
                作業完了を確定する
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const reason = window.prompt("キャンセル理由（任意）") ?? null;
                  void act(
                    () => cancelTransaction(txn.id, reason, token!),
                    "本当にキャンセルしますか？",
                  );
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
                <a
                  href={`/review?transaction_id=${txn.id}`}
                  className="mt-2 inline-block text-sm font-semibold text-brand-700 hover:underline"
                >
                  詳しく評価する →
                </a>
              </div>
            ))}
        </Card>
      )}

      <a href="/cases" className="inline-block text-sm font-semibold text-brand-700 hover:underline">
        ← マイ案件一覧へ
      </a>
    </div>
    </>
  );
}
