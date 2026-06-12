"use client";

/** ユーザー: 自分の案件一覧。 */

import { useEffect, useState } from "react";
import { Spinner } from "@/components/Icon";
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
  type CaseOut,
} from "@/lib/katadzuke-api";

export default function MyCasesPage() {
  const { token, loading } = useToken();
  const [cases, setCases] = useState<CaseOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    listMyCases(token)
      .then(setCases)
      .catch((e) => setError(e instanceof Error ? e.message : "取得に失敗しました"));
  }, [token]);

  if (loading || (!cases && !error)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  return (
    <PageShell
      title="マイ案件"
      description="依頼した片付け案件の一覧です。"
      actions={
        <a href="/create" className={btnPrimary}>
          新しく依頼する
        </a>
      }
    >
      {error ? <Notice tone="error">{error}</Notice> : null}
      {cases && cases.length === 0 ? (
        <Card className="text-center">
          <p className="text-sm text-slate-500">まだ案件がありません。</p>
          <a href="/create" className={`${btnPrimary} mt-4`}>
            最初の依頼をつくる
          </a>
        </Card>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {cases?.map((c) => (
          <a key={c.id} href={`/cases/${c.id}`} className="group">
            <Card className="h-full transition-shadow group-hover:shadow-md">
              <div className="flex items-start justify-between gap-3">
                <div className="flex gap-3">
                  {c.photos[0] ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={photoSrc(c.photos[0].url)}
                      alt=""
                      className="h-16 w-16 shrink-0 rounded-xl border border-slate-200 object-cover"
                    />
                  ) : (
                    <div className="h-16 w-16 shrink-0 rounded-xl bg-slate-100" />
                  )}
                  <div>
                    <p className="font-bold text-slate-900">{c.purpose}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {c.prefecture} {c.city} / {c.floor_plan ?? "間取り未設定"}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {new Date(c.created_at).toLocaleDateString("ja-JP")}
                    </p>
                  </div>
                </div>
                <StatusBadge value={c.status} label={CASE_STATUS_LABEL[c.status]} />
              </div>
              <p className="mt-3 text-sm font-semibold text-brand-700">
                入札 {c.bid_count} 件
              </p>
            </Card>
          </a>
        ))}
      </div>
    </PageShell>
  );
}
