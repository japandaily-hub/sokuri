"use client";

/**
 * 旧査定ファネル（/analyzing → /condition → /result）の着地ページ。
 * 旧ファネルは新IAから流入ゼロの孤立レガシーのため、/cases へ集約する（2026-07-03）。
 * case_id が付与されていれば該当案件詳細へ、assessment_id 等それ以外は一覧（/cases）へ遷移する。
 */

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Spinner } from "@/components/Icon";

function ResultRedirectInner() {
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

export default function ResultPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      }
    >
      <ResultRedirectInner />
    </Suspense>
  );
}
