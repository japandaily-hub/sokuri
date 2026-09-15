"use client";

/**
 * 交渉チャット（/chat/[id]）。
 * デザイン正典: docs/design_handoff_katazuke/chat.html をピクセル忠実に再現。
 * 動的ルート([id])。SiteChrome の BARE_PREFIXES（/chat）対象で共通クロムが付かないため、
 * ページ自身が専用ヘッダー（戻る矢印 + ロゴ + タイトル + ID + 通知ベル）と全画面レイアウトを描く。
 *
 * [id] は transaction_id として扱う（成約後は1業者につき1スレッドのため）。
 * サイドバーは「自分の成約案件一覧」（listTransactions）。
 * メッセージ取得・送信・日程確定・既読化・ポーリング等のロジックとUIは、
 * cases/[id] のインラインチャットとも共用する @/components/kdz/ChatPanel に切り出し済み。
 * このページは専用ヘッダーと成約案件サイドバーのみを担当する。
 */

import "./chat.css";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { ChatPanel } from "@/components/kdz/ChatPanel";
import { KdzLogo } from "@/components/kdz/Logo";
import { useToken } from "@/components/kdz/Ui";
import {
  LIST_MAX_LIMIT,
  listTransactions,
  toDisplayMessage,
  type TransactionDetail,
  type TransactionListItem,
} from "@/lib/katadzuke-api";

export default function ChatPage() {
  // 動的ルートの id は transaction_id。
  const params = useParams<{ id: string }>();
  const transactionId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const router = useRouter();
  const { token } = useToken();

  /* ---- サイドバー: 自分の成約案件一覧 ---- */
  const [transactions, setTransactions] = useState<TransactionListItem[]>([]);
  const [sideLoading, setSideLoading] = useState(true);

  /* ---- 成約詳細（申込ID表示用。本体の取得は ChatPanel が担う） ---- */
  const [detail, setDetail] = useState<TransactionDetail | null>(null);

  /* ---- サイドバー用トースト ---- */
  const [sideToast, setSideToast] = useState<string | null>(null);

  /* ---- サイドバー: 成約一覧取得 ---- */
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listTransactions(token, { limit: LIST_MAX_LIMIT, offset: 0 });
        if (!cancelled) setTransactions(list);
      } catch (e) {
        if (!cancelled) setSideToast(toDisplayMessage(e, "案件一覧の取得に失敗しました"));
      } finally {
        if (!cancelled) setSideLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!sideToast) return;
    const t = window.setTimeout(() => setSideToast(null), 2600);
    return () => window.clearTimeout(t);
  }, [sideToast]);

  function selectTransaction(id: string) {
    if (id === transactionId) return;
    router.push(`/chat/${id}`);
  }

  const appId = detail?.id ? detail.id.slice(0, 8).toUpperCase() : "";

  if (!transactionId) return null;

  return (
    <div className="chat-page">
      {/* 専用ヘッダー（戻る矢印 + ロゴ + タイトル + 申込ID + 通知ベル） */}
      <header className="chat-header">
        <Link href="/cases" className="ch-back" aria-label="マイ案件へ戻る">
          <Ic name="arrow" />
        </Link>
        <Link href="/" className="ch-logo" aria-label="カタヅケ トップへ">
          <KdzLogo size={20} />
        </Link>
        <span className="ch-divider" aria-hidden="true" />
        <span className="ch-title">交渉チャット</span>
        {appId ? <span className="ch-id">{appId}</span> : null}
        <Link href="/notifications" className="ch-bell" aria-label="通知・お知らせ">
          <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 01-3.46 0" />
          </svg>
          <span className="bell-dot" aria-hidden="true" />
        </Link>
      </header>

      <div className="chat-layout">
        {/* 成約案件一覧 */}
        <nav className="biz-sidebar" aria-label="自分の成約案件">
          <div className="biz-sidebar-head">成約案件</div>
          {sideLoading ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>読み込み中…</div>
          ) : transactions.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>成約済みの案件はありません</div>
          ) : (
            transactions.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`biz-item${t.id === transactionId ? " active" : ""}`}
                onClick={() => selectTransaction(t.id)}
                aria-current={t.id === transactionId ? "true" : undefined}
              >
                <div className="biz-meta">
                  <span className="biz-time">{new Date(t.created_at).toLocaleDateString("ja-JP")}</span>
                </div>
                <div className="biz-name">{t.company_name ?? "業者"}</div>
                <div className="biz-preview">
                  {t.prefecture} {t.city}
                </div>
                <span className="biz-bid">
                  {t.final_amount != null ? `¥${t.final_amount.toLocaleString()}` : `¥${t.initial_amount.toLocaleString()}`}
                </span>
              </button>
            ))
          )}
        </nav>

        <ChatPanel transactionId={transactionId} variant="standalone" onDetailChange={setDetail} />
      </div>

      {sideToast ? (
        <div className="kdz-toast side-toast" role="status">
          {sideToast}
        </div>
      ) : null}
    </div>
  );
}
