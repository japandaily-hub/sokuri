"use client";

/** 配信停止ページ（法的要件: CAN-SPAM/特商法 メール配信停止受付）。
 * URLパラメータ ?token=xxx&email=xxx を受け取り、停止申請受付を表示する。
 * Phase 1: 実際の抑制リストは運営者が手動管理。
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

function UnsubscribeContent() {
  const params = useSearchParams();
  const email = params.get("email") ?? "";
  const [submitted, setSubmitted] = useState(false);

  // ページ表示と同時に受付済みとする（Phase1: 手動運用）
  useEffect(() => {
    setSubmitted(true);
  }, []);

  return (
    <div className="mx-auto max-w-lg px-4 py-20 text-center">
      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-green-100">
          <svg
            className="h-7 w-7 text-green-600"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-xl font-bold text-slate-900">配信停止のご申請を受け付けました</h1>
        <p className="mt-4 text-sm leading-relaxed text-slate-600">
          {email ? (
            <>
              <span className="font-semibold text-slate-900">{email}</span>{" "}
              宛てのカタヅケからのご案内メールの送信を停止いたします。
            </>
          ) : (
            "カタヅケからのご案内メールの送信を停止いたします。"
          )}
        </p>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          すでに送信処理中のメールは届く場合がございます。あらかじめご了承ください。
        </p>
        <p className="mt-2 text-xs text-slate-400">
          停止処理の完了までに数営業日かかる場合がございます。
        </p>
        <div className="mt-8">
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-xl bg-brand-600 px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
          >
            トップへ戻る
          </a>
        </div>
      </div>
      <p className="mt-6 text-xs text-slate-400">
        ご不明な点は{" "}
        <a
          href="mailto:katazuke.support@gmail.com"
          className="underline hover:text-slate-600"
        >
          katazuke.support@gmail.com
        </a>{" "}
        までお問い合わせください。
      </p>
    </div>
  );
}

export default function UnsubscribePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center text-sm text-slate-400">
          処理中…
        </div>
      }
    >
      <UnsubscribeContent />
    </Suspense>
  );
}
