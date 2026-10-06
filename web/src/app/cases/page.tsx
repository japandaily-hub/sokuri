"use client";

/** ユーザー: 自分の案件一覧。 */

import { useCallback, useEffect, useState } from "react";
import { Spinner } from "@/components/Icon";
import { AppHeader } from "@/components/kdz/AppHeader";
import { resolveListViewState } from "@/lib/list-state";
import { formatJstDateLong } from "@/lib/datetime";
import { formatPurposeLabel } from "@/lib/case-labels";
import {
  Card,
  Notice,
  PageShell,
  StatusBadge,
  btnPrimary,
  useToken,
} from "@/components/kdz/Ui";
import {
  CASE_STATUS_LABEL,
  listMyCases,
  photoSrc,
  toDisplayMessage,
  type CaseOut,
} from "@/lib/katadzuke-api";

export default function MyCasesPage() {
  const { token, loading } = useToken();
  const [cases, setCases] = useState<CaseOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!token) return;
    setError(null);
    listMyCases(token)
      .then(setCases)
      .catch((e) => setError(toDisplayMessage(e, "取得に失敗しました")));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const viewState = resolveListViewState({ pending: loading, failed: Boolean(error), items: cases });
  if (viewState === "loading") {
    return (
      <>
        <AppHeader />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </>
    );
  }

  return (
    <>
      <AppHeader />
      <PageShell
      title="マイ案件"
      description="出品した片付け案件の一覧です。"
      actions={
        <a href="/create" className={btnPrimary}>
          新しく出品する
        </a>
      }
    >
      {viewState === "failed" ? (
        <div className="space-y-3">
          <Notice tone="error">{error}</Notice>
          {/* 取得に失敗したときは「案件がありません」と区別し、再読み込みの導線を出す。 */}
          <button type="button" className={btnPrimary} onClick={load}>
            再読み込み
          </button>
        </div>
      ) : null}
      {viewState === "empty" ? (
        <Card className="text-center">
          <p className="text-sm text-slate-500">まだ案件がありません。</p>
          <a href="/create" className={`${btnPrimary} mt-4`}>
            最初の出品をする
          </a>
        </Card>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {cases?.map((c) => (
          <a key={c.id} href={`/cases/${c.id}`} className="group">
            <Card className="h-full">
              <div className="flex items-start justify-between gap-3">
                <div className="flex gap-3">
                  {c.photos[0] ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={photoSrc(c.photos[0].url)}
                      alt=""
                      className="h-16 w-16 shrink-0 rounded-none border border-slate-200 object-cover"
                    />
                  ) : (
                    <div className="h-16 w-16 shrink-0 rounded-none bg-slate-100" />
                  )}
                  <div className="min-w-0">
                    <p className="font-normal text-slate-900">{formatPurposeLabel(c.purpose)}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {c.prefecture} {c.city} / {c.floor_plan ?? "間取り未設定"}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {formatJstDateLong(c.created_at)}
                    </p>
                  </div>
                </div>
                <StatusBadge value={c.status} label={CASE_STATUS_LABEL[c.status]} />
              </div>
              <p className="mt-3 text-sm font-semibold text-brand-700">
                入札 {c.bid_count} 件
                {c.item_count != null && c.item_count > 0
                  ? ` ・ 品物 ${c.item_count} 点・写真 ${c.photo_count ?? c.photos.length} 枚`
                  : c.photo_count != null
                    ? ` ・ 写真 ${c.photo_count} 枚`
                    : ""}
              </p>
            </Card>
          </a>
        ))}
      </div>
      </PageShell>
    </>
  );
}
