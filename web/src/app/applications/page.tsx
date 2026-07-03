"use client";

/**
 * 旧「申し込み状況」ページの着地点。
 * バックエンド配線済みの案件詳細（/cases/[id]）へ集約するため、
 * モック UI は全廃しリダイレクタとして薄く保つ（2026-07-03）。
 * case_id が付与されていれば該当案件詳細へ、無ければ一覧（/cases）へ遷移する。
 */

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Spinner } from "@/components/Icon";

function ApplicationsRedirectInner() {
  const router = useRouter();
  const search = useSearchParams();

  useEffect(() => {
    const caseId = search.get("case_id");
    router.replace(caseId ? `/cases/${caseId}` : "/cases");
  }, [router, search]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <Spinner className="h-6 w-6 text-brand-600" />
    </div>
  );
}

export default function ApplicationsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      }
    >
      <ApplicationsRedirectInner />
    </Suspense>
  );
}
