"use client";

/**
 * 管理画面: 口コミの管理（削除／元に戻す。role=admin のみ）。
 *
 * ユーザー指示「運営が口コミの削除ができるようにもしておいて」への対応。物理削除はせず、
 * hidden_at・hidden_reason・hidden_by_admin_id による論理削除にする（送信防止措置・
 * 発信者情報開示の申出に応じるため記録を保持し、誤操作も『元に戻す』で戻せるようにする）。
 * デザイン正典: .agent-state/review-verdict/DESIGN-admin.md（段3 web）。
 *
 * 既存 /admin/contacts・/admin/transactions と同じ Tailwind/Card/StatusBadge 構成、
 * 検索・絞り込み・ページングの実装パターンを踏襲する。口コミ本文は依頼者・業者の自由入力を
 * そのまま描画するため、必ずテキストノードとして出す（dangerouslySetInnerHTML は使わない。
 * break-words + whitespace-pre-wrap で長文・長語による横スクロール崩れを防ぐ）。
 *
 * 削除理由: 定型5種＋自由入力の“選択式チップ”は、共有部品 ConfirmModal（改変禁止）が
 * 単一の自由入力欄（reasonLabel + textarea）しか持たないため実装できない。定型文言は
 * reasonLabel に列挙して自由入力欄に反映してもらう運用にする（/admin/transactions の
 * 強制終了ダイアログと同じ「ラベル1つ＋自由記述」の組み方に揃える）。200字上限は
 * ConfirmModal 内蔵の上限（500字）より厳しいため、送信直前に本コンポーネント側でも検査する。
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import {
  Card,
  Notice,
  PageShell,
  StatusBadge,
  btnDanger,
  btnPrimary,
  btnSecondary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import { AdminPagination } from "../_components/AdminPagination";
import { ConfirmModal } from "../_components/ConfirmModal";
import { CopyableId } from "../_components/CopyableId";
import { StatusFilterBar } from "../_components/StatusFilterBar";
import { REVIEW_VERDICT_LABEL } from "@/lib/review-verdict";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  adminListReviews,
  adminSetReviewHidden,
  toDisplayMessage,
  type AdminReviewListItem,
  type AdminReviewListResponse,
  type AdminReviewVisibility,
  type ReviewVerdict,
} from "@/lib/katadzuke-api";

type ReviewerTypeFilter = "all" | "user" | "operator";
type VerdictFilter = "all" | ReviewVerdict;

const VISIBILITY_OPTIONS: { value: AdminReviewVisibility; label: string }[] = [
  { value: "visible", label: "表示中" },
  { value: "hidden", label: "削除済み" },
  { value: "all", label: "すべて" },
];

const REVIEWER_TYPE_OPTIONS: { value: ReviewerTypeFilter; label: string }[] = [
  { value: "all", label: "すべて" },
  { value: "user", label: "依頼者→業者" },
  { value: "operator", label: "業者→依頼者" },
];

const VERDICT_OPTIONS: { value: VerdictFilter; label: string }[] = [
  { value: "all", label: "すべて" },
  { value: "good", label: REVIEW_VERDICT_LABEL.good },
  { value: "improve", label: REVIEW_VERDICT_LABEL.improve },
];

/** 削除理由の上限。backend の _sanitize_free_text（1〜200字）と同じ値。 */
const HIDE_REASON_MAX = 200;
/** 削除理由の定型（ConfirmModal は改変しないため選択式ではなく reasonLabel の例示にする）。 */
const HIDE_REASON_PRESETS = [
  "誹謗中傷・名誉毀損のおそれ",
  "第三者の個人情報",
  "送信防止措置の申出",
  "取引と関係ない内容・宣伝",
  "その他",
];
const HIDE_REASON_LABEL = `削除理由（必須・${HIDE_REASON_MAX}字以内。定型: ${HIDE_REASON_PRESETS.join("／")}）`;

/** 削除確認ダイアログに出す本文の抜粋（80字。対象の取り違え防止）。 */
function excerptComment(comment: string | null, max = 80): string {
  if (!comment) return "（コメントなし）";
  return comment.length > max ? `${comment.slice(0, max)}…` : comment;
}

function AdminReviewsContent() {
  const { token, loading } = useToken();
  const searchParams = useSearchParams();

  const [data, setData] = useState<AdminReviewListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const initialVisibilityParam = searchParams.get("visibility");
  const [visibility, setVisibility] = useState<AdminReviewVisibility>(
    initialVisibilityParam === "hidden" || initialVisibilityParam === "all" ? initialVisibilityParam : "visible",
  );
  const [reviewerType, setReviewerType] = useState<ReviewerTypeFilter>("all");
  const [verdict, setVerdict] = useState<VerdictFilter>("all");
  const [qInput, setQInput] = useState(searchParams.get("q") ?? "");
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [operatorId, setOperatorId] = useState<string | null>(searchParams.get("operator_id"));
  const [operatorLabel, setOperatorLabel] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const [hideTarget, setHideTarget] = useState<AdminReviewListItem | null>(null);
  const [hideModalError, setHideModalError] = useState<string | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<AdminReviewListItem | null>(null);
  const [restoreModalError, setRestoreModalError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    try {
      const res = await adminListReviews(
        {
          visibility,
          reviewerType: reviewerType === "all" ? undefined : reviewerType,
          verdict: verdict === "all" ? undefined : verdict,
          operatorId: operatorId ?? undefined,
          q,
          limit: ADMIN_LIST_DEFAULT_LIMIT,
          offset,
        },
        token,
      );
      setData(res);
      setError(null);
      // 業者絞込みの解除チップに出す会社名を、実際に返ってきた行から拾う（/admin/reviews への
      // 直リンク時は事前に会社名を知らないため。URL に operator_id はあっても company_name は無い）。
      if (operatorId) {
        const label = res.items.find((it) => it.operator_id === operatorId)?.company_name;
        if (label) setOperatorLabel(label);
      }
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    } finally {
      setBusy(false);
    }
  }, [token, visibility, reviewerType, verdict, operatorId, q, offset]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function changeVisibility(next: AdminReviewVisibility) {
    setOffset(0);
    setVisibility(next);
  }
  function changeReviewerType(next: ReviewerTypeFilter) {
    setOffset(0);
    setReviewerType(next);
  }
  function changeVerdict(next: VerdictFilter) {
    setOffset(0);
    setVerdict(next);
  }
  function runSearch() {
    setOffset(0);
    setQ(qInput.trim());
  }
  function filterByOperator(item: AdminReviewListItem) {
    if (!item.operator_id) return;
    setOffset(0);
    setOperatorId(item.operator_id);
    setOperatorLabel(item.company_name);
  }
  function clearOperatorFilter() {
    setOffset(0);
    setOperatorId(null);
    setOperatorLabel(null);
  }

  function closeHideModal() {
    setHideTarget(null);
    setHideModalError(null);
  }

  async function confirmHide(reason: string | null) {
    if (!hideTarget || !token || busy) return;
    const trimmed = (reason ?? "").trim();
    if (!trimmed) {
      setHideModalError("理由を入力してください。");
      return;
    }
    if (trimmed.length > HIDE_REASON_MAX) {
      setHideModalError(`理由は${HIDE_REASON_MAX}字以内で入力してください（現在${trimmed.length}字）。`);
      return;
    }
    setBusy(true);
    setHideModalError(null);
    try {
      await adminSetReviewHidden(hideTarget.id, { hidden: true, reason: trimmed }, token);
      closeHideModal();
      await reload();
    } catch (e) {
      // r5-fix-frontend M-2 と同型: 失敗時はモーダルを閉じず、error prop に表示する。
      setHideModalError(toDisplayMessage(e, "削除に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  function closeRestoreModal() {
    setRestoreTarget(null);
    setRestoreModalError(null);
  }

  async function confirmRestore() {
    if (!restoreTarget || !token || busy) return;
    setBusy(true);
    setRestoreModalError(null);
    try {
      await adminSetReviewHidden(restoreTarget.id, { hidden: false }, token);
      closeRestoreModal();
      await reload();
    } catch (e) {
      setRestoreModalError(toDisplayMessage(e, "元に戻す処理に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!data && !error)) {
    return (
      <div className="admin-page">
        <AppHeader showBell={false} />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AppHeader showBell={false} />
      <PageShell
        title="口コミの管理"
        description="公開中の口コミを確認し、問題のある口コミを公開画面から削除します。削除した口コミは運営画面に記録として残り、元に戻せます。"
        actions={
          <Link href="/admin" className={btnSecondary}>
            管理画面トップへ
          </Link>
        }
      >
        {error ? (
          <div className="mb-4">
            <Notice tone="error">{error}</Notice>
          </div>
        ) : null}

        <Card>
          <div className="flex flex-col gap-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") runSearch();
                }}
                className={inputBase}
                placeholder="口コミ ID・取引 ID（完全一致）・業者名（部分一致）で検索"
              />
              <button type="button" onClick={runSearch} className={`${btnPrimary} shrink-0`}>
                検索
              </button>
            </div>
            <StatusFilterBar
              options={VISIBILITY_OPTIONS.map((o) => ({ ...o, count: data?.counts[o.value] }))}
              value={visibility}
              onChange={changeVisibility}
            />
            <StatusFilterBar options={REVIEWER_TYPE_OPTIONS} value={reviewerType} onChange={changeReviewerType} />
            <StatusFilterBar options={VERDICT_OPTIONS} value={verdict} onChange={changeVerdict} />
            {operatorId ? (
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span>業者で絞込: {operatorLabel ?? operatorId}</span>
                <button
                  type="button"
                  onClick={clearOperatorFilter}
                  className="text-brand-600 underline"
                  aria-label={`業者「${operatorLabel ?? operatorId}」の絞り込みを解除`}
                >
                  解除
                </button>
              </div>
            ) : null}
          </div>

          <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="口コミ一覧">
            <table className="w-full min-w-[960px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-2 pr-4">投稿日時</th>
                  <th className="pb-2 pr-4">向き</th>
                  <th className="pb-2 pr-4">評価</th>
                  <th className="pb-2 pr-4">口コミ</th>
                  <th className="pb-2 pr-4">業者</th>
                  <th className="pb-2 pr-4">ID</th>
                  <th className="pb-2 pr-4">状態</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((r) => (
                  <tr key={r.id} className="align-top">
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {new Date(r.created_at).toLocaleString("ja-JP")}
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-700">
                      {r.reviewer_type === "user" ? "依頼者→業者" : "業者→依頼者"}
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-700">{REVIEW_VERDICT_LABEL[r.verdict]}</td>
                    <td className="py-2 pr-4 max-w-md whitespace-pre-wrap break-words text-slate-700">
                      {r.comment ?? "（コメントなし）"}
                    </td>
                    <td className="py-2 pr-4 text-slate-700">
                      {r.operator_id ? (
                        <button
                          type="button"
                          onClick={() => filterByOperator(r)}
                          className="underline decoration-dotted hover:text-brand-600"
                        >
                          {r.company_name ?? "—"}
                        </button>
                      ) : (
                        (r.company_name ?? "—")
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-1 text-xs text-slate-400">
                        <span>取引</span>
                        <CopyableId id={r.transaction_id} />
                      </div>
                      <div className="mt-1 flex items-center gap-1 text-xs text-slate-400">
                        <span>口コミ</span>
                        <CopyableId id={r.id} />
                      </div>
                    </td>
                    <td className="py-2 pr-4">
                      {r.hidden_at ? (
                        <div>
                          <StatusBadge value="cancelled" label="削除済み" />
                          <p className="mt-1 whitespace-nowrap text-xs text-slate-500">
                            {new Date(r.hidden_at).toLocaleString("ja-JP")}
                          </p>
                          {r.hidden_reason ? (
                            <p className="mt-1 max-w-[16rem] whitespace-pre-wrap break-words text-xs text-slate-500">
                              理由: {r.hidden_reason}
                            </p>
                          ) : null}
                        </div>
                      ) : (
                        <StatusBadge value="completed" label="表示中" />
                      )}
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {r.hidden_at ? (
                        <button
                          type="button"
                          className={btnSecondary}
                          onClick={() => {
                            setRestoreModalError(null);
                            setRestoreTarget(r);
                          }}
                        >
                          元に戻す
                        </button>
                      ) : (
                        <button
                          type="button"
                          className={btnDanger}
                          onClick={() => {
                            setHideModalError(null);
                            setHideTarget(r);
                          }}
                        >
                          削除する
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && data.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">該当する口コミはありません。</p>
            ) : null}
            {busy && !hideTarget && !restoreTarget ? (
              <div className="flex items-center gap-2 py-3 text-sm text-slate-600">
                <Spinner className="h-4 w-4" /> 読み込み中…
              </div>
            ) : null}
          </div>

          {data && !error ? (
            <AdminPagination
              total={data.total}
              limit={ADMIN_LIST_DEFAULT_LIMIT}
              offset={offset}
              itemCount={data.items.length}
              onPrev={() => setOffset(Math.max(0, offset - ADMIN_LIST_DEFAULT_LIMIT))}
              onNext={() => setOffset(offset + ADMIN_LIST_DEFAULT_LIMIT)}
            />
          ) : null}
        </Card>
      </PageShell>

      {hideTarget ? (
        <ConfirmModal
          title="この口コミを公開画面から削除します"
          message={`${hideTarget.company_name ?? "業者名不明"}宛「${excerptComment(hideTarget.comment)}」\n\n公開プロフィール・口コミの件数・最新の口コミから消えます。記録は運営画面に残り、『元に戻す』で再表示できます。`}
          confirmLabel="削除する"
          danger
          withReason
          reasonLabel={HIDE_REASON_LABEL}
          reasonRequired
          error={hideModalError}
          busy={busy}
          onCancel={closeHideModal}
          onConfirm={(reason) => void confirmHide(reason)}
        />
      ) : null}

      {restoreTarget ? (
        <ConfirmModal
          title="この口コミを元に戻します"
          message="公開プロフィールと件数に再び反映されます。この画面からは削除の理由と実施者の記録が消えます（元に戻した操作は、実施した運営と日時が操作ログに残ります）。"
          confirmLabel="元に戻す"
          error={restoreModalError}
          busy={busy}
          onCancel={closeRestoreModal}
          onConfirm={() => void confirmRestore()}
        />
      ) : null}
    </div>
  );
}

/** useSearchParams（?q=・?visibility=・?operator_id=）を使うため Suspense 境界で包む（他ページと同型）。 */
export default function AdminReviewsPage() {
  return (
    <Suspense fallback={null}>
      <AdminReviewsContent />
    </Suspense>
  );
}
