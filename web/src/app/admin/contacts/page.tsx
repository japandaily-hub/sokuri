"use client";

/**
 * 管理画面: お問い合わせの受信箱（role=admin のみ）。
 *
 * r10 O-M6 対応: `/contact` から送られたお問い合わせを運営が読む画面が存在せず、
 * 送信者には「3営業日以内に返信します」と案内しているのに受信箱が無い＝返信不能だった。
 * 既存 /admin 配下（cases・users・identity-documents）と同じ Tailwind/Card/StatusBadge 構成、
 * 検索・絞り込み・ページングの実装パターンを踏襲する。
 *
 * 本文・氏名・メールは第三者が自由入力した値をそのまま描画するため、必ず JSX の
 * テキストノードとして出す（dangerouslySetInnerHTML は使わない）。長文・長語での
 * 横スクロール崩れを防ぐため break-words + whitespace-pre-wrap を付ける。
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Card, Notice, PageShell, StatusBadge, btnPrimary, btnSecondary, useToken } from "@/components/kdz/Ui";
import { AdminPagination } from "../_components/AdminPagination";
import { ConfirmModal } from "../_components/ConfirmModal";
import { StatusFilterBar } from "../_components/StatusFilterBar";
import {
  ADMIN_LIST_DEFAULT_LIMIT,
  adminHandleContact,
  adminListContacts,
  toDisplayMessage,
  type AdminContactListResponse,
  type AdminContactMessage,
} from "@/lib/katadzuke-api";

/** 絞り込みの値。API の handled（true/false/未指定）へ 1:1 で対応させる。 */
type HandledFilter = "unhandled" | "handled" | "all";

const FILTER_OPTIONS: { value: HandledFilter; label: string }[] = [
  { value: "unhandled", label: "未対応" },
  { value: "handled", label: "対応済み" },
  { value: "all", label: "すべて" },
];

function toHandledParam(filter: HandledFilter): boolean | undefined {
  if (filter === "unhandled") return false;
  if (filter === "handled") return true;
  return undefined;
}

export default function AdminContactsPage() {
  const { token, loading } = useToken();
  const [data, setData] = useState<AdminContactListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [filter, setFilter] = useState<HandledFilter>("unhandled");
  const [offset, setOffset] = useState(0);

  const [handleTarget, setHandleTarget] = useState<AdminContactMessage | null>(null);
  // 他の admin 画面と同じく、失敗時はモーダルを閉じず error prop へ出す（画面下部の行を
  // 操作した場合、ページ上部 Notice はモーダル背後に隠れて見落とされるため）。
  const [handleModalError, setHandleModalError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    try {
      const res = await adminListContacts(
        { handled: toHandledParam(filter), limit: ADMIN_LIST_DEFAULT_LIMIT, offset },
        token,
      );
      setData(res);
      setError(null);
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    } finally {
      setBusy(false);
    }
  }, [token, filter, offset]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function changeFilter(next: HandledFilter) {
    setOffset(0);
    setFilter(next);
  }

  async function confirmHandle() {
    if (!handleTarget || !token || busy) return;
    setBusy(true);
    setHandleModalError(null);
    try {
      await adminHandleContact(handleTarget.id, token);
      setHandleTarget(null);
      await reload();
    } catch (e) {
      setHandleModalError(toDisplayMessage(e, "更新に失敗しました"));
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
        title="お問い合わせ"
        description="お問い合わせフォームから届いたメッセージを確認し、返信後に「対応済み」へ切り替えます。返信はメールで行ってください。"
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-normal text-slate-900">受信一覧</h2>
            <StatusFilterBar options={FILTER_OPTIONS} value={filter} onChange={changeFilter} />
          </div>

          <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="お問い合わせ一覧">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-2 pr-4">受信日時</th>
                  <th className="pb-2 pr-4">お名前</th>
                  <th className="pb-2 pr-4">メール</th>
                  <th className="pb-2 pr-4">種別</th>
                  <th className="pb-2 pr-4">本文</th>
                  <th className="pb-2 pr-4">状態</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((m) => (
                  <tr key={m.id} className="align-top">
                    <td className="py-2 pr-4 whitespace-nowrap text-slate-500">
                      {new Date(m.created_at).toLocaleString("ja-JP")}
                    </td>
                    <td className="py-2 pr-4 break-words text-slate-700">{m.name}</td>
                    <td className="py-2 pr-4 break-all text-slate-700">{m.email}</td>
                    <td className="py-2 pr-4 break-words text-slate-700">{m.category}</td>
                    <td className="py-2 pr-4 max-w-md whitespace-pre-wrap break-words text-slate-700">
                      {m.message}
                    </td>
                    <td className="py-2 pr-4">
                      {m.handled_at ? (
                        <StatusBadge value="completed" label="対応済み" />
                      ) : (
                        <StatusBadge value="pending" label="未対応" />
                      )}
                    </td>
                    <td className="py-2 text-right">
                      {m.handled_at ? (
                        <p className="whitespace-nowrap text-xs text-slate-500">
                          {new Date(m.handled_at).toLocaleString("ja-JP")}
                        </p>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setHandleModalError(null);
                            setHandleTarget(m);
                          }}
                          disabled={busy}
                          className={`${btnPrimary} whitespace-nowrap`}
                        >
                          対応済みにする
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && data.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">該当するお問い合わせはありません。</p>
            ) : null}
            {busy && !handleTarget ? (
              <div className="flex items-center gap-2 py-3 text-sm text-slate-600">
                <Spinner className="h-4 w-4" /> 読み込み中…
              </div>
            ) : null}
          </div>

          {data ? (
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

      {handleTarget ? (
        <ConfirmModal
          title={`${handleTarget.email} のお問い合わせを対応済みにします`}
          message="対応済みにすると未対応の一覧・バッジから外れます。返信を送ってから切り替えてください。よろしいですか？"
          confirmLabel="対応済みにする"
          error={handleModalError}
          busy={busy}
          onCancel={() => {
            setHandleModalError(null);
            setHandleTarget(null);
          }}
          onConfirm={() => void confirmHandle()}
        />
      ) : null}
    </div>
  );
}
