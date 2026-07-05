"use client";

/** 配信停止ページ（法的要件: CAN-SPAM/特商法 メール配信停止受付）。
 * URLパラメータ ?token=xxx&email=xxx を受け取り、停止申請受付を表示する。
 * Phase 1: 実際の抑制リストは運営者が手動管理。
 *
 * デザインレビュー A-2 対応: 旧 slate 意匠を廃し、完了系画面（signup/create-complete）と
 * 同じ done-circle（green）+ 共通 .form-card/.btn の語彙に統一。ヘッダー/フッターは
 * 他の静的ページ（terms/contact 等）と同様、共通 SiteChrome のマーケ用クロムのままとする。
 */

import "./unsubscribe.css";

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
    <div className="unsub-page">
      <div className="form-card">
        <div className="done-circle">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 12.5l5.5 5.5L20 7" />
          </svg>
        </div>
        <h1>配信停止のご申請を受け付けました</h1>
        <p>
          {email ? (
            <>
              <strong style={{ color: "var(--navy)" }}>{email}</strong> 宛てのカタヅケからのご案内メールの送信を停止いたします。
            </>
          ) : (
            "カタヅケからのご案内メールの送信を停止いたします。"
          )}
        </p>
        <p>すでに送信処理中のメールは届く場合がございます。あらかじめご了承ください。</p>
        <p style={{ fontSize: 12.5 }}>停止処理の完了までに数営業日かかる場合がございます。</p>
        <div style={{ marginTop: 28 }}>
          <a href="/" className="btn btn-primary">
            トップへ戻る
          </a>
        </div>
      </div>
      <p className="unsub-footnote">
        ご不明な点は <a href="mailto:katazuke-support@gmail.com">katazuke-support@gmail.com</a> までお問い合わせください。
      </p>
    </div>
  );
}

export default function UnsubscribePage() {
  return (
    <Suspense fallback={<div style={{ minHeight: "50vh", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "var(--body-soft)" }}>処理中…</div>}>
      <UnsubscribeContent />
    </Suspense>
  );
}
