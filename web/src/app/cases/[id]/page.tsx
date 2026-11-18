"use client";

/**
 * ユーザー: 案件詳細。
 * - 入札一覧の確認と 1 社選択（落札確定）
 * - 成約後: 減額申請への承認/却下、完了確定、キャンセル、レビュー投稿
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { Icon, Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { ChatPanel } from "@/components/kdz/ChatPanel";
import { ConfirmModal } from "@/components/kdz/ConfirmModal";
import { formatJstDateTime } from "@/lib/datetime";
import { formatVisitSchedule } from "@/lib/categories";
import { jstTodayIso } from "@/lib/visit-slots";
import "./case-detail.css";
import { CASE_PROGRESS_STEPS, buildHousingAttributes, caseProgressStep, caseProgressStepState, isCaseIdFormat, isCompletionBeforeVisit, meaningfulCaseSummary } from "@/lib/case-detail-view";
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
  KdzApiError,
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
  getReductionQuota,
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
import { ReviewComposer } from "@/components/kdz/ReviewComposer";
import { REVIEW_VERDICT_LABEL, formatVerdictCounts } from "@/lib/review-verdict";

/** 編集/削除UIを許可する案件ステータス（それ以外は409になるためバックエンドと同条件でUIも隠す）。 */
const EDITABLE_CASE_STATUSES = new Set(["draft", "open"]);

/** 出品取り下げを許可する案件ステータス（backend の cancel_case と同条件）。 */
const CANCELLABLE_CASE_STATUSES = new Set(["open", "bidding"]);

/** 確認ダイアログの「閉じる」ボタンの語。実行ボタン（「キャンセルする」等）と紛れないよう「キャンセル」は使わない。 */
const CONFIRM_DISMISS_LABEL = "やめる";

/** 品物一覧で最初から見せる件数（見本 v12）。それ以降は「ほか N 点を見る」で開く。 */
const CD_ITEMS_PREVIEW = 4;

/** window.confirm の代わりに表示する ConfirmModal の内容（r8-fix-frontend）。
 *  r10-M8 是正: 取り下げ・キャンセルの理由入力は window.prompt をやめ、withReason/reasonRequired で
 *  ConfirmModal に統合する（onConfirm が入力済みの理由を受け取る）。 */
type ConfirmState = {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  withReason?: boolean;
  reasonRequired?: boolean;
  reasonLabel?: string;
  onConfirm: (reason: string | null) => void;
} | null;

export default function UserCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const caseId = params.id;
  const { token, loading } = useToken();
  const { data: sessionData } = useSession();
  /** 運営が依頼者の画面を開いているか（代理での誤操作を避けるため帯で明示する）。 */
  const isAdminViewing = sessionData?.role === "admin";

  const [caseData, setCaseData] = useState<CaseOut | null>(null);
  const [bids, setBids] = useState<BidOut[]>([]);
  const [txn, setTxn] = useState<TransactionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** 案件の取得に失敗したときの HTTP ステータス（404=存在しない と 通信失敗等 を区別して表示するため）。 */
  const [loadErrorStatus, setLoadErrorStatus] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  // /cases/abc 等の形式違いは API を叩かず専用表示にする。
  const isCaseIdValid = isCaseIdFormat(caseId);
  /** AI解析ポーリングが打ち切り時間（backend の遅延回収窓=10分）に達したかどうか。 */
  const [aiPollTimedOut, setAiPollTimedOut] = useState(false);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  /** 成約後チャットをこの画面内にインライン展開しているか（既定で開く=別ページ遷移なしで
   *  「業者を選ぶ→そのままチャットで会話開始」を完結させる。r-chat-inline 対応）。 */
  const [chatOpen, setChatOpen] = useState(true);
  /** 品物一覧の「ほか N 点を見る」を開いているか。 */
  const [itemsExpanded, setItemsExpanded] = useState(false);

  // ===== 品物の編集/削除・写真の追加/削除 =====
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
      title: "自動で付けた内容に戻しますか？",
      message: "状態・説明を編集した内容を破棄して、写真から自動で付けた内容に戻しますか？",
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
      title: "品物を削除しますか？",
      message: "紐づく写真もすべて削除されます。この操作は元に戻せません。",
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
      setError(toDisplayMessage(e, "品物の削除に失敗しました"));
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
      message: "この操作は元に戻せません。",
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
    if (!token || !isCaseIdValid) return;
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
      setLoadErrorStatus(e instanceof KdzApiError ? e.status : 0);
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [caseId, token, isCaseIdValid]);

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

  if (!isCaseIdValid) {
    return (
      <>
        <AppHeader />
        <div className="container-aw max-w-3xl space-y-4 py-10">
          <Notice tone="error">このページのアドレスが正しくありません。一覧から開き直してください。</Notice>
          <Link href="/cases" className={btnPrimary}>
            マイ案件一覧へ
          </Link>
        </div>
      </>
    );
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
        <div className="container-aw max-w-3xl space-y-4 py-10">
          <Notice tone="error">
            {loadErrorStatus === 404
              ? "この案件は見つかりませんでした。削除されたか、アドレスが違う可能性があります。"
              : (error ?? "案件が見つかりません。")}
          </Notice>
          <div className="flex flex-wrap gap-2">
            {loadErrorStatus !== 404 ? (
              <button
                type="button"
                className={btnPrimary}
                onClick={() => {
                  setError(null);
                  setLoadErrorStatus(null);
                  void reload();
                }}
              >
                再読み込み
              </button>
            ) : null}
            <Link href="/cases" className={btnSecondary}>
              マイ案件一覧へ
            </Link>
            <Link href="/mypage" className={btnSecondary}>
              マイページへ
            </Link>
          </div>
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
  // r10 M2 是正: 業者側にしか出ていなかった申請上限・残り回数を依頼者側にも表示する。
  const reductionQuota = txn ? getReductionQuota(txn) : null;
  const myReview = txn?.reviews.find((r) => r.reviewer_type === "user");
  // 未入力の項目は出さない（生のダッシュや「EVなし」の断定表示をしない）。
  const housingAttributes = buildHousingAttributes(caseData);
  // 入札は金額の高い順に並べる（同額は元の順＝先着）。
  const sortedActiveBids = [...activeBids].sort((a, b) => b.amount - a.amount);
  // 訪問予定日より前（または日程未定）に完了確定しようとしていないか（日本時間の今日と比較）。
  const completionBeforeVisit = txn != null && isCompletionBeforeVisit(txn.visit_date, jstTodayIso());

  // 品物一覧（見本 v12: 4件まで見せ、残りは「ほか N 点を見る」で開く）。
  const albums = toAlbums(caseData);
  const itemCount = albums.filter((a) => a.id !== null).length || albums.length;
  const hiddenAlbumCount = Math.max(0, albums.length - CD_ITEMS_PREVIEW);
  /** 進み具合（取り下げ・キャンセルは null＝出さない）。 */
  const progressStep = caseProgressStep(caseData.status, txn);
  const showBids = !txn && caseData.status !== "cancelled";

  return (
    <>
    <AppHeader />
    <div className="cd-wrap space-y-6">
      {/* 取り下げ済みの案件に「受け付けました」を残すと矛盾するため、受付中の案件だけに出す。 */}
      {search.get("created") && caseData.status !== "cancelled" ? (
        <Notice tone="success">
          出品を受け付けました。業者から入札が届くと、LINE連携済みの方はLINEで、未連携の方はメールでお知らせします。
        </Notice>
      ) : null}
      {isAdminViewing ? (
        <Notice tone="info">
          運営として、依頼者の画面を表示しています。ここでの操作は依頼者の取引に反映され、当事者に通知される場合があります。必要なときだけ操作してください。ただし、減額の承認・却下と日程の確定は依頼者本人だけが行えます。
        </Notice>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}

      {/* ===== 題目（見本 v12 ② 案件詳細） ===== */}
      <div>
        <nav aria-label="パンくず" className="cd-crumb">
          <Link href="/cases">マイ案件一覧</Link>
          <span aria-hidden="true">／</span>
          <span aria-current="page">{formatPurposeLabel(caseData.purpose)}</span>
        </nav>
        <div className="cd-title">
          <div>
            <h1>{formatPurposeLabel(caseData.purpose)}</h1>
            {housingAttributes.length > 0 ? <p className="cd-housing">{housingAttributes.join(" / ")}</p> : null}
          </div>
          <div className="cd-meta">
            <span>
              {caseData.prefecture} {caseData.city}
              {caseData.address_detail ? ` ${caseData.address_detail}` : ""}
            </span>
            <StatusBadge
              value={caseData.status}
              label={caseData.status === "cancelled" && !txn ? "取り下げ済み" : CASE_STATUS_LABEL[caseData.status]}
            />
          </div>
        </div>
        {caseData.status === "cancelled" ? (
          <div className="cd-notice" role="status">
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

      {progressStep !== null ? (
        <ol className="cd-stepper" aria-label="進み具合">
          {CASE_PROGRESS_STEPS.map((step, index) => {
            const state = caseProgressStepState(index, progressStep);
            return (
              <li key={step.full} className={`cd-stepper__step cd-stepper__step--${state}`} aria-current={state === "now" ? "step" : undefined}>
                {/* 段名は読み上げ用に全幅のものを常に残し、見た目の全幅／短縮は aria-hidden の span を CSS で出し分ける。 */}
                <span className="sr-only">{step.full}</span>
                <span className="cd-stepper__full" aria-hidden="true">{step.full}</span>
                <span className="cd-stepper__short" aria-hidden="true">{step.short}</span>
                {state === "done" ? <span className="sr-only">（済み）</span> : null}
              </li>
            );
          })}
        </ol>
      ) : null}

      <div className={showBids ? "cd-grid" : "cd-grid cd-grid--solo"}>
        {/* ===== 届いた入札（右 7fr。DOM は入札が先＝スマホの表示順・読み上げ順と一致。PC は grid-template-areas で右に置く） ===== */}
        {showBids && (
          <section className="cd-bids-col" aria-labelledby="cd-bids-heading">
            <h2 className="cd-h-sm" id="cd-bids-heading">
              届いた入札
              <span>
                <span className="cd-num">{activeBids.length}</span>件・金額の高い順
              </span>
            </h2>
            {activeBids.length === 0 ? (
              <p className="cd-empty">
                まだ入札がありません。入札が届くと、LINE連携済みの方はLINEで、未連携の方はメールでお知らせします。
              </p>
            ) : (
              <>
                <ol className="cd-bids">
                  {sortedActiveBids.map((b) => {
                    // 最高額の印は入札が2件以上のときだけ。同額が複数あれば全部に付ける。
                    const isTopBid = topBidAmount != null && b.amount === topBidAmount && activeBids.length > 1;
                    return (
                      <li key={b.id} className={isTopBid ? "cd-bid cd-bid--top" : "cd-bid"}>
                        <div className="cd-bid__main">
                          <div className="cd-bid__who">
                            <span className="cd-bid__name">{b.operator?.company_name ?? "業者"}</span>
                            {isTopBid ? (
                              <span className="cd-bid__mark">{topBidCount > 1 ? "同額でいちばん高い入札" : "いちばん高い入札"}</span>
                            ) : null}
                          </div>
                          <dl className="cd-bid__facts">
                            <dt>口コミ</dt>
                            <dd>
                              {b.operator != null && b.operator.review_count > 0 ? (
                                <>
                                  <span className="inline-block whitespace-nowrap">
                                    {formatVerdictCounts(b.operator.good_count, b.operator.improve_count)}
                                  </span>
                                  <span className="cd-bid__soft">（口コミ{b.operator.review_count}件）</span>
                                  {b.operator.latest_review_comment ? (
                                    <span className="cd-bid__voice">最新の口コミ: 「{b.operator.latest_review_comment}」</span>
                                  ) : null}
                                </>
                              ) : (
                                "まだありません"
                              )}
                            </dd>
                          </dl>
                          {b.operator ? (
                            <Link href={`/vendors/${b.operator.id}`} className="cd-bid__link">
                              業者のプロフィール・口コミを見る
                            </Link>
                          ) : null}
                          {b.message ? <p className="cd-bid__message">{b.message}</p> : null}
                          {b.operator_suspended ? (
                            <p className="cd-bid__alert" role="alert">
                              この業者は現在利用停止中です。運営（
                              <Link href="/contact" className="underline">
                                お問い合わせフォーム
                              </Link>
                              ）にお問い合わせください。
                            </p>
                          ) : null}
                        </div>
                        <div className="cd-bid__price">
                          <p className="cd-bid__amount">{formatYen(b.amount)}</p>
                          <p className="cd-bid__basis">{itemCount > 0 ? `品物${itemCount}点の買取総額` : "買取総額"}</p>
                          {b.revision_count > 0 ? (
                            <p className="cd-bid__revised">更新あり（{b.revision_count}回）</p>
                          ) : null}
                        </div>
                        {/* 一覧は activeBids（pending のみ）だが、多層防御として描画直前にも再確認する。 */}
                        {b.status === "pending" ? (
                          <div className="cd-bid__act">
                            <button
                              type="button"
                              disabled={busy || b.operator_suspended}
                              title={b.operator_suspended ? "この業者は現在利用停止中のため選択できません" : undefined}
                              onClick={() =>
                                setConfirmState({
                                  title: "この業者に決定しますか？",
                                  message: `${b.operator?.company_name ?? "この業者"}（${formatYen(b.amount)}）に決定しますか？決定すると、他の業者の入札はすべて無効になり、元に戻せません。業者に伝わるのは住所とご登録のメールアドレスだけです（LINEだけで登録した方はメールが渡らず、LINEでの連絡のご案内になります。氏名・電話番号は伝わりません）。決定後も、取引のキャンセルはできます（理由は業者に共有されます）。`,
                                  confirmLabel: "決定する",
                                  onConfirm: () => {
                                    setConfirmState(null);
                                    void act(() => selectBid(caseId, b.id, token!));
                                  },
                                })
                              }
                              className={
                                // 塗りのボタンは「いちばん高い入札」の行。入札が1件だけならその1件。
                                isTopBid || activeBids.length === 1 ? btnPrimary : btnSecondary
                              }
                            >
                              この業者に決める
                            </button>
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
                <div className="cd-after">
                  <h3>「この業者に決める」を押すと</h3>
                  <ol>
                    <li>確認の画面が出ます。ここではまだ決まりません。</li>
                    <li>確認の画面で決めると、住所とご登録のメールアドレスが、選んだ1社にだけ伝わります（LINEだけで登録した方はメールが渡らず、LINEでの連絡のご案内になります）。</li>
                    <li>ほかの業者には、カタヅケから自動でお断りの連絡が入ります。</li>
                  </ol>
                </div>
                <p className="cd-note">最終的な買取額は、業者が当日に現物を見て決めます。</p>
              </>
            )}
        {canCancelCase ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (!token) return;
                setConfirmState({
                  title: "出品を取り下げますか？",
                  message: "付いている入札はすべて無効になり、元に戻せません。理由の入力は任意です。",
                  confirmLabel: "取り下げる",
                  danger: true,
                  withReason: true,
                  reasonRequired: false,
                  reasonLabel: "取り下げの理由（任意）",
                  onConfirm: (reason) => {
                    setConfirmState(null);
                    void act(() => cancelCase(caseId, reason, token));
                  },
                });
              }}
              className={`mt-4 ${btnDanger}`}
            >
              出品を取り下げる
            </button>
            <p className="mt-2 text-[15px] text-kdz-bodysoft">
              ※ 業者を決めた後の取り消しは、取引の画面の一番下にある「この取引をキャンセルする」から行えます。
            </p>
          </>
        ) : null}
          </section>
        )}

        {/* ===== 品物（左 4fr） ===== */}
        <section className="cd-items-col" aria-labelledby="cd-items-heading">
          <h2 className="cd-h-sm" id="cd-items-heading">
            出品した品物
            <span>
              <span className="cd-num">{itemCount}</span>点
            </span>
          </h2>
          <ul className="cd-items">
            {albums.map((album, albumIndex) => {
              const item = album.id ? (caseData.items?.find((it) => it.id === album.id) ?? null) : null;
              const isEditing = item != null && editingItemId === item.id;
              const isSavingItem = item != null && busyOps.has(`item:${item.id}:save`);
              const isResettingItem = item != null && busyOps.has(`item:${item.id}:reset`);
              const isDeletingItem = item != null && busyOps.has(`item:${item.id}:delete`);
              const isUploadingItem = item != null && busyOps.has(`item:${item.id}:upload`);
              const itemAnyBusy = item != null && isItemBusy(item.id);
              // AI推定値そのものが無ければ「AI推定に戻す」を出しても戻す先が無いため無効化する。
              const hasAiFallback = item != null && (item.ai_condition != null || item.ai_summary != null);
              // 折りたたみ中でも、編集中の品物は隠さない。
              const isFolded = albumIndex >= CD_ITEMS_PREVIEW && !itemsExpanded && !isEditing;
              const summary = meaningfulCaseSummary(album.description);

              return (
                <li key={album.id ?? "unassigned"} className="cd-item" hidden={isFolded}>
                  <div className="cd-item__row">
                    {/* サムネイルは置かない: 写真は下の一覧で常に全件見せる（同じ写真を二重に出さない） */}
                    <span className="cd-item__name">{album.title ?? "写真"}</span>
                    {album.condition ? (
                      <span className="cd-item__cat">{CASE_ITEM_CONDITION_LABEL[album.condition] ?? album.condition}</span>
                    ) : null}
                  </div>
                  {summary ? <p className="cd-item__desc">{summary}</p> : null}

                  {item && canEditCase ? (
                    <div className="cd-item__tools">
                      {!isEditing ? (
                        <button
                          type="button"
                          disabled={itemAnyBusy}
                          onClick={() => startEditItem(item)}
                          className={btnSecondary}
                        >
                          編集
                        </button>
                      ) : null}
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
                        {isDeletingItem ? "削除中…" : "品物を削除"}
                      </button>
                    </div>
                  ) : null}

          {isEditing && item ? (
            <div className="mt-2 space-y-3 rounded-kdz border border-kdz-line bg-kdz-pale p-4">
              {editError ? <p className="text-[15px] font-semibold text-kdz-danger">{editError}</p> : null}
              <div>
                <label className="mb-1 block text-[15px] font-semibold text-kdz-bodysoft">品物名</label>
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
                <label className="mb-1 block text-[15px] font-semibold text-kdz-bodysoft">状態</label>
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
                <label className="mb-1 block text-[15px] font-semibold text-kdz-bodysoft">説明</label>
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
                  編集をやめる
                </button>
                {hasAiFallback ? (
                  <button
                    type="button"
                    disabled={isSavingItem || isResettingItem}
                    onClick={() => resetEditItemToAi(item)}
                    className="inline-flex items-center text-[15px] font-semibold text-kdz-bodysoft hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isResettingItem ? "リセット中…" : "自動で付けた内容に戻す"}
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

                  {/* 写真の一覧は常に出す（行のサムネは先頭1枚だけなので、全件はここで見せる）。削除ボタンは canEditCase のときだけ。 */}
                  {album.photos.length > 0 ? (
          <ul className="mt-3 grid grid-cols-4 gap-2" aria-label={`${album.title ?? "写真"}の写真`}>
            {album.photos.map((p) => {
              const isDeletingPhoto = busyOps.has(`photo:${p.id}:delete`);
              return (
                <li key={p.id} className="group relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={photoSrc(p.url)}
                    alt=""
                    className="aspect-square w-full rounded-kdz border border-kdz-line object-cover"
                  />
                  {canEditCase ? (
                    <button
                      type="button"
                      aria-label="この写真を削除"
                      disabled={isDeletingPhoto}
                      onClick={() => handleDeletePhoto(p.id)}
                      className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-[rgba(var(--deep-rgb),.85)] text-white opacity-0 transition-opacity focus:opacity-100 disabled:opacity-100 group-hover:opacity-100"
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
                  ) : null}
                </li>
              );
            })}
          </ul>
          {hiddenAlbumCount > 0 ? (
            <button
              type="button"
              className="cd-items-more"
              aria-expanded={itemsExpanded}
              onClick={() => setItemsExpanded((v) => !v)}
            >
              {itemsExpanded ? "閉じる" : `ほか ${hiddenAlbumCount} 点を見る`}
            </button>
          ) : null}

          <input
            ref={addPhotoInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            className="hidden"
            onChange={handleAddPhotoFilesSelected}
          />

      {caseData.ai_status === "pending" && aiPollTimedOut ? (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-kdz bg-kdz-pale p-4" role="status">
          <p className="text-[15px] leading-relaxed text-kdz-body">
            説明の作成に時間がかかっています。ページを再読み込みしてください。
          </p>
          <button type="button" onClick={() => window.location.reload()} className={btnSecondary}>
            再読み込み
          </button>
        </div>
      ) : caseData.ai_status === "pending" ? (
        <div className="mt-4 flex items-center gap-2 rounded-kdz bg-kdz-pale p-4" role="status">
          <Spinner className="h-4 w-4 text-brand-600" />
          <p className="text-[15px] leading-relaxed text-kdz-body">
            写真をもとに品物の説明を作っています（通常1〜2分）。この画面は自動で更新されます。
          </p>
        </div>
      ) : caseData.ai_status === "failed" ? (
        <div className="mt-4 rounded-kdz bg-kdz-pale p-4">
          <p className="text-[15px] leading-relaxed text-kdz-body">
            品物の説明を自動で作れませんでした。写真と入力内容で入札を受け付けます。
          </p>
        </div>
      ) : meaningfulCaseSummary(caseData.ai_summary) ? (
        <div className="mt-4 rounded-kdz bg-kdz-pale p-4">
          <p className="text-[15px] font-semibold text-kdz-bodysoft">
            品物の説明（業者に表示されます）
          </p>
          <p className="mt-1.5 text-[15px] leading-relaxed text-kdz-body">
            {meaningfulCaseSummary(caseData.ai_summary)}
          </p>
        </div>
      ) : null}
        </section>
      </div>


      <div className="cd-rest space-y-6">
      {/* ===== 成約パネル ===== */}
      {txn && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-normal text-kdz-ink">
                業者が決まりました: {txn.operator?.company_name ?? "業者"}
              </h2>
              <p className="mt-1 text-[15px] text-kdz-bodysoft">
                決定した金額 {formatYen(txn.initial_amount)}
                {txn.final_amount != null && txn.final_amount !== txn.initial_amount
                  ? ` → 確定額 ${formatYen(txn.final_amount)}`
                  : ""}
              </p>
              {txn.contact_email ? (
                <p className="mt-0.5 text-[15px] text-kdz-bodysoft">
                  業者連絡先: {txn.contact_email}
                </p>
              ) : null}
            </div>
            <StatusBadge value={txn.status} label={TXN_STATUS_LABEL[txn.status]} />
          </div>

          {txn.operator_deleted ? (
            <div className="mt-3 rounded-kdz border border-[var(--danger-border-soft)] bg-[var(--danger-bg-soft)] p-3 text-[15px] leading-relaxed text-kdz-danger" role="alert">
              この業者は退会したため、この取引は進められません。キャンセルして新しく出品してください
            </div>
          ) : txn.operator_suspended ? (
            <div className="mt-3 rounded-kdz border border-[var(--danger-border-soft)] bg-[var(--danger-bg-soft)] p-3 text-[15px] leading-relaxed text-kdz-danger" role="alert">
              この業者は現在利用停止中です。運営（
              <Link href="/contact" className="underline">
                お問い合わせフォーム
              </Link>
              ）にお問い合わせください。
            </div>
          ) : null}

          {/* r8-fix-frontend2 H2 是正: キャンセルの理由が相手方に一切届かなかった問題への対応。
              誰が・なぜ・いつキャンセルしたかを表示する。 */}
          {txn.cancellation ? (
            <div className="mt-3 rounded-kdz border border-kdz-line bg-kdz-pale p-3 text-[15px] leading-relaxed text-kdz-body" role="status">
              <p className="font-semibold text-kdz-ink">
                キャンセル: {CANCELLED_BY_LABEL[txn.cancellation.cancelled_by]}による
              </p>
              <p className="mt-1 text-[15px] text-kdz-bodysoft">
                {formatJstDateTime(txn.cancellation.cancelled_at)}
              </p>
              {txn.cancellation.reason ? (
                <p className="mt-1 break-words">理由: {txn.cancellation.reason}</p>
              ) : (
                <p className="mt-1 text-kdz-bodysoft">理由の記載なし</p>
              )}
            </div>
          ) : null}

          {/* 業者とのやり取り導線（チャット/日程調整）。r8-fix-frontend5 対応:
              業者退会時はチャット送信・日程調整に進めないため導線ごと非表示にする。
              r-chat-inline 対応: チャットは別ページへ遷移せず、この画面内にインライン展開する
              （開閉はトグル。既定で開いた状態にし、そのまま会話を継続できるようにする）。 */}
          {txn.status !== "cancelled" && !txn.operator_deleted && (
            <div className="mt-4">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setChatOpen((v) => !v)}
                  aria-expanded={chatOpen}
                  className={btnPrimary}
                >
                  {chatOpen ? "チャットを閉じる" : "業者とチャット"}
                  {txn.unread_count > 0 ? `（未読${txn.unread_count}）` : ""}
                </button>
                {txn.status === "pending" && txn.visit_date == null ? (
                  <a href={`/schedule?transaction_id=${txn.id}`} className={btnSecondary}>
                    訪問日程を調整する
                  </a>
                ) : null}
                {txn.visit_date ? (
                  <p className="self-center text-[15px] font-semibold text-kdz-body">
                    訪問予定: {formatVisitSchedule(txn.visit_date, txn.visit_time_slot)}
                  </p>
                ) : null}
                {txn.operator_suspended ? (
                  <p className="w-full text-[15px] font-semibold text-kdz-danger">
                    ※ 業者が対応できないため、チャット送信・日程調整の返信が届かない場合があります。
                  </p>
                ) : null}
              </div>
              {chatOpen ? (
                <ChatPanel
                  transactionId={txn.id}
                  variant="embedded"
                  className="mt-3"
                  onDetailChange={setTxn}
                  readOnly={isAdminViewing}
                />
              ) : null}
            </div>
          )}

          {/* r10 M2 是正: 業者側にのみ表示されていた申請上限・残り回数を依頼者側にも明示する
              （成約後・キャンセル前のみ意味を持つため active な状態でのみ表示）。 */}
          {reductionQuota && (txn.status === "pending" || txn.status === "visiting") ? (
            <p className="mt-4 text-[15px] text-kdz-bodysoft">
              業者からの減額の申請は、1つの取引につき{reductionQuota.limit}回までです
              {reductionQuota.remaining !== null ? `（残り${reductionQuota.remaining}回）` : ""}
            </p>
          ) : null}

          {/* 減額申請の履歴（承認・却下済みを含む全件。r6-flow M-4 対応。
              ラベル定義は operator/transactions/[id]/page.tsx と共通の
              REDUCTION_STATUS_LABEL（lib/katadzuke-api.ts）を使う。 */}
          {txn.reduction_requests.length > 0 && (
            <div className="mt-4">
              <p className="text-[15px] font-normal text-kdz-ink">減額申請の履歴</p>
              <ul className="mt-2 space-y-2">
                {txn.reduction_requests.map((r) => (
                  <li
                    key={r.id}
                    className="rounded-kdz border border-kdz-line p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[15px] font-semibold text-kdz-ink">
                        {formatYen(r.original_amount)} → {formatYen(r.requested_amount)}
                      </span>
                      <StatusBadge value={r.status} label={REDUCTION_STATUS_LABEL[r.status]} />
                    </div>
                    <p className="mt-1 text-[15px] leading-relaxed text-kdz-body">理由: {r.reason}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 減額申請（承認待ち） */}
          {pendingReduction && (
            <div className="mt-4 rounded-kdz border border-[var(--gold)] bg-[var(--warm)] p-4">
              <p className="text-[15px] font-semibold text-[var(--gold-text)]">業者から減額申請が届いています</p>
              <p className="mt-1 text-[15px] text-[var(--gold-text)]">
                {formatYen(pendingReduction.original_amount)} →{" "}
                <strong>{formatYen(pendingReduction.requested_amount)}</strong>
              </p>
              <p className="mt-2 rounded-kdz bg-[var(--white)] p-3 text-[15px] leading-relaxed text-kdz-body">
                理由: {pendingReduction.reason}
              </p>
              {/* 減額の承認・却下は依頼者本人だけ（運営の代理閲覧では backend が 403 にするため出さない。security M-1）。 */}
              {isAdminViewing ? (
                <p className="mt-3 text-[15px] text-[var(--gold-text)]" data-testid="reduction-admin-note">
                  減額の承認・却下は依頼者本人だけが行えます（運営は代理で判断できません）。
                </p>
              ) : (
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      setConfirmState({
                        title: "減額を承認しますか？",
                        message: "確定額が更新されます。",
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
                        message: "この操作は元に戻せません。",
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
              )}
            </div>
          )}

          {/* 作業完了の確定（取り消し不能）。取引のキャンセルは押し間違いを避けるため、
              このボタンから離して画面下部の弱いリンクにする（下の「取引のキャンセル」参照）。 */}
          {(txn.status === "pending" || txn.status === "visiting") && !txn.operator_deleted ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy || Boolean(pendingReduction)}
                onClick={() =>
                  setConfirmState({
                    title: completionBeforeVisit
                      ? "まだ訪問日の前です。作業完了を確定しますか？"
                      : "作業完了を確定しますか？",
                    message: (isAdminViewing ? "運営として、依頼者に代わって確定します。" : "") + (completionBeforeVisit
                      ? `${txn.visit_date ? `訪問予定は${formatVisitSchedule(txn.visit_date, txn.visit_time_slot)}です。` : "訪問日がまだ決まっていません。"}作業がまだ終わっていない場合は押さないでください。確定すると取引は完了になり、業者とのチャットも送れなくなります。この操作は元に戻せません。`
                      : "確定すると取引は完了になり、業者とのチャットも送れなくなります。この操作は元に戻せません。確定後は評価を投稿できます。"),
                    confirmLabel: "確定する",
                    danger: completionBeforeVisit,
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
            </div>
          ) : null}
          {pendingReduction ? (
            <p className="mt-2 text-[15px] text-kdz-bodysoft">
              ※ 減額申請への回答後に完了確定できます。
            </p>
          ) : null}

          {/* レビュー */}
          {txn.status === "completed" &&
            (myReview ? (
              <div>
                <Notice tone="success">
                  評価投稿済み（{REVIEW_VERDICT_LABEL[myReview.verdict]}）ありがとうございました。
                </Notice>
                {/* r10-M7 是正: 評価投稿後の導線が「← マイ案件一覧へ」1本しか無く行き止まりだったため、
                    /review と同型の「マイページへ」「また出品する」を並べる。 */}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link href="/mypage" className={btnSecondary}>
                    マイページへ
                  </Link>
                  <Link href="/create" className={btnPrimary}>
                    また出品する
                  </Link>
                </div>
              </div>
            ) : isAdminViewing ? null : (
              // 評価は案件の所有者だけが投稿できる（運営の代理閲覧では backend が 403 にするため出さない）。
              <div className="mt-4 rounded-kdz border border-kdz-line p-4">
                <p className="font-normal text-kdz-ink">業者を評価する</p>
                <ReviewComposer
                  direction="to_operator"
                  submitLabel="評価を投稿する"
                  busy={busy}
                  onSubmit={(value) =>
                    act(() =>
                      createReview(
                        {
                          transaction_id: txn.id,
                          verdict: value.verdict,
                          comment: value.comment,
                        },
                        token!,
                      ),
                    )
                  }
                />
              </div>
            ))}

          {/* 取引のキャンセル（取り消し不能）。作業完了ボタンと並べず、画面下部の弱いリンクにする。 */}
          {/* 運営の代理閲覧では出さない（backend は運営名義のキャンセルを 403 にする。運営の強制終了は /admin/transactions）。 */}
          {(txn.status === "pending" || txn.status === "visiting") && !isAdminViewing ? (
            <div className="mt-10 border-t border-kdz-line pt-4">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setConfirmState({
                    title: "この取引をキャンセルしますか？",
                    message: "案件は終了し、この操作は元に戻せません。理由を書いた場合は業者に共有されます（書かなくても取り消せます）。",
                    confirmLabel: "取引をキャンセルする",
                    danger: true,
                    withReason: true,
                    reasonRequired: false,
                    reasonLabel: "キャンセルの理由（任意・書いた場合は業者に共有されます）",
                    onConfirm: (reason) => {
                      setConfirmState(null);
                      void act(() => cancelTransaction(txn.id, reason, token!));
                    },
                  });
                }}
                className="text-[15px] text-kdz-bodysoft underline underline-offset-2 hover:text-kdz-body disabled:cursor-not-allowed disabled:opacity-50"
              >
                この取引をキャンセルする
              </button>
            </div>
          ) : null}
        </Card>
      )}

      <Link href="/cases" className="inline-block text-[15px] font-semibold text-brand-700 hover:underline">
        ← マイ案件一覧へ
      </Link>
      </div>
    </div>
    {confirmState ? (
      <ConfirmModal
        title={confirmState.title}
        message={confirmState.message}
        confirmLabel={confirmState.confirmLabel}
        danger={confirmState.danger}
        withReason={confirmState.withReason}
        reasonRequired={confirmState.reasonRequired}
        reasonLabel={confirmState.reasonLabel}
        busy={busy}
        cancelLabel={CONFIRM_DISMISS_LABEL}
        onCancel={() => setConfirmState(null)}
        onConfirm={confirmState.onConfirm}
      />
    ) : null}
    </>
  );
}
