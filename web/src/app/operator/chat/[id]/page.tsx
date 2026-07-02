"use client";

/**
 * 業者 交渉チャット（/operator/chat/[id]）。
 * デザイン正典: docs/design_handoff_katazuke/業者チャット.html をピクセル忠実に再現。
 * これは業者(operator)側の画面。送信メッセージ（自社）は青バブルで右、相手（ユーザー）は白バブルで左。
 *
 * 動的ルート([id])。/operator は SiteChrome の BARE_PREFIXES 対象で共通クロムが付かないため、
 * ページ自身が専用ヘッダー（戻る矢印 + ロゴ + タイトル + 業者管理バッジ + 会社名 + 通知ベル）と全画面レイアウトを描く。
 *
 * [id] は transaction_id として扱う。サイドバー「交渉中の案件」は listTransactions（業者向け）。
 * メッセージは listMessages のポーリング（表示中5秒間隔・document.hidden 時は停止）+ sendMessage。
 * 日程提示は proposeSchedule に接続する。
 */

import "./chat.css";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { useToken } from "@/components/kdz/Ui";
import {
  TXN_STATUS_LABEL,
  getTransaction,
  listMessages,
  listTransactions,
  markMessagesRead,
  proposeSchedule,
  sendMessage,
  toDisplayMessage,
  type MessageOut,
  type TransactionDetail,
  type TransactionListItem,
} from "@/lib/katadzuke-api";

/* ---- カレンダー線画（スプライト未収録のため inline。絵文字は使わない） ---- */
function CalendarIc({ className }: { className?: string }) {
  return (
    <svg className={`ic${className ? ` ${className}` : ""}`} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M4 9h16M8 3v4M16 3v4" />
    </svg>
  );
}

const POLL_INTERVAL_MS = 5000;

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}
function formatDateSep(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("ja-JP", { month: "long", day: "numeric", weekday: "short" });
}
function yen(n: number): string {
  return `¥${n.toLocaleString()}`;
}

export default function OperatorChatPage() {
  const params = useParams<{ id: string }>();
  const transactionId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const router = useRouter();
  const { token, loading: tokenLoading } = useToken();

  /* ---- サイドバー: 交渉中の案件一覧（業者向け listTransactions） ---- */
  const [transactions, setTransactions] = useState<TransactionListItem[]>([]);
  const [sideLoading, setSideLoading] = useState(true);

  /* ---- 現在の成約詳細（相手ユーザー情報・合意額・案件） ---- */
  const [detail, setDetail] = useState<TransactionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  /* ---- メッセージ ---- */
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const lastFetchedAtRef = useRef<string | undefined>(undefined);

  /* ---- 日程提案カード（候補日の編集 + 送信） ---- */
  const [slots, setSlots] = useState<string[]>([""]);
  const [scheduleVisible, setScheduleVisible] = useState(false);
  const [proposing, setProposing] = useState(false);

  /* ---- トースト ---- */
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  function showToast(msg: string) {
    setToast(msg);
    if (toastTimer.current !== undefined) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }
  useEffect(
    () => () => {
      if (toastTimer.current !== undefined) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  /* ---- サイドバー: 交渉中の案件取得 ---- */
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listTransactions(token);
        if (!cancelled) setTransactions(list);
      } catch (e) {
        if (!cancelled) showToast(toDisplayMessage(e, "案件一覧の取得に失敗しました"));
      } finally {
        if (!cancelled) setSideLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  /* ---- 成約詳細取得 ---- */
  const reloadDetail = useCallback(async () => {
    if (!token || !transactionId) return;
    try {
      const d = await getTransaction(transactionId, token);
      setDetail(d);
      setDetailError(null);
    } catch (e) {
      setDetailError(toDisplayMessage(e, "成約情報の取得に失敗しました"));
    }
  }, [token, transactionId]);

  useEffect(() => {
    void reloadDetail();
  }, [reloadDetail]);

  /* ---- メッセージ取得（初回全件 + ポーリング差分） ---- */
  const fetchMessages = useCallback(
    async (initial: boolean) => {
      if (!token || !transactionId) return;
      try {
        const after = initial ? undefined : lastFetchedAtRef.current;
        const batch = await listMessages(transactionId, token, after);
        if (batch.length > 0) {
          lastFetchedAtRef.current = batch[batch.length - 1].created_at;
          setMessages((prev) => (initial ? batch : [...prev, ...batch]));
        } else if (initial) {
          setMessages([]);
        }
        setMessagesError(null);
      } catch (e) {
        setMessagesError(toDisplayMessage(e, "メッセージの取得に失敗しました"));
      }
    },
    [token, transactionId],
  );

  useEffect(() => {
    lastFetchedAtRef.current = undefined;
    setMessages([]);
    void fetchMessages(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transactionId, token]);

  /* ---- ポーリング（表示中のみ・document.hidden 時は停止） ---- */
  useEffect(() => {
    if (!token || !transactionId) return;
    let timer: number | undefined;
    function schedule() {
      timer = window.setTimeout(async () => {
        if (!document.hidden) {
          await fetchMessages(false);
        }
        schedule();
      }, POLL_INTERVAL_MS);
    }
    schedule();
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [token, transactionId, fetchMessages]);

  /* ---- 既読化 ---- */
  useEffect(() => {
    if (!token || !transactionId || messages.length === 0) return;
    markMessagesRead(transactionId, token).catch(() => {
      /* 既読更新の失敗は致命的でないため無視する */
    });
  }, [token, transactionId, messages.length]);

  /* ---- 自動スクロール ---- */
  const messagesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, scheduleVisible]);

  function selectTransaction(id: string) {
    if (id === transactionId) return;
    router.push(`/operator/chat/${id}`);
  }

  async function handleSend() {
    const text = draft.trim();
    if (!text || !token || !transactionId || sending) return;
    setSending(true);
    try {
      const sent = await sendMessage(transactionId, text, token);
      setMessages((prev) => [...prev, sent]);
      lastFetchedAtRef.current = sent.created_at;
      setDraft("");
    } catch (e) {
      showToast(toDisplayMessage(e, "メッセージの送信に失敗しました"));
    } finally {
      setSending(false);
    }
  }

  /* ---- 日程提案カード操作 ---- */
  function updateSlot(i: number, value: string) {
    setSlots((prev) => prev.map((s, idx) => (idx === i ? value : s)));
  }
  function removeSlot(i: number) {
    setSlots((prev) => prev.filter((_, idx) => idx !== i));
  }
  function addSlot() {
    setSlots((prev) => [...prev, ""]);
  }
  function toggleScheduleCard() {
    setScheduleVisible((v) => {
      const next = !v;
      if (next) {
        window.setTimeout(() => {
          document.getElementById("schedule-propose")?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 0);
      }
      return next;
    });
  }
  async function handleSendSchedule() {
    const dates = slots.map((s) => s.trim()).filter(Boolean);
    if (dates.length === 0) {
      showToast("候補日を1つ以上入力してください");
      return;
    }
    if (!token || !transactionId || proposing) return;
    setProposing(true);
    try {
      const msg = await proposeSchedule(transactionId, dates, token);
      setMessages((prev) => [...prev, msg]);
      lastFetchedAtRef.current = msg.created_at;
      setScheduleVisible(false);
      setSlots([""]);
      showToast("候補日を送信しました");
    } catch (e) {
      showToast(toDisplayMessage(e, "候補日の送信に失敗しました"));
    } finally {
      setProposing(false);
    }
  }

  const peerInitial = "客";
  const caseIdShort = detail?.case_id ? detail.case_id.slice(0, 8).toUpperCase() : "";
  const statusLabel = detail ? TXN_STATUS_LABEL[detail.status] : "";

  return (
    <div className="opchat-page">
      {/* 専用ヘッダー */}
      <header className="ch-header">
        <Link href="/operator/cases" className="ch-back" aria-label="案件一覧へ戻る">
          <Ic name="arrow" />
        </Link>
        <Link href="/operator" className="ch-logo" aria-label="業者ダッシュボードへ">
          <KdzLogo size={20} />
        </Link>
        <span className="ch-divider" aria-hidden="true" />
        <span className="ch-title">交渉チャット</span>
        <span className="ch-badge">業者管理画面</span>
        <div className="ch-right">
          <Link href="/operator" className="ch-bell" aria-label="通知・お知らせ">
            <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 01-3.46 0" />
            </svg>
            <span className="bell-dot" aria-hidden="true" />
          </Link>
        </div>
      </header>

      <div className="chat-layout">
        {/* 案件リスト（左サイドバー） */}
        <nav className="case-sidebar" aria-label="交渉中の案件">
          <div className="case-sidebar-head">交渉中の案件</div>
          {sideLoading ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>読み込み中…</div>
          ) : transactions.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12.5, color: "var(--body-soft)" }}>落札済みの案件はありません</div>
          ) : (
            transactions.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`case-item${t.id === transactionId ? " active" : ""}`}
                onClick={() => selectTransaction(t.id)}
                aria-current={t.id === transactionId ? "true" : undefined}
              >
                <span className={`case-status status-${t.status === "pending" ? "waiting" : t.status === "visiting" ? "scheduled" : "negotiating"}`}>
                  {TXN_STATUS_LABEL[t.status]}
                </span>
                <div className="case-id">{t.id.slice(0, 8).toUpperCase()}</div>
                <div className="case-preview">
                  {t.prefecture} {t.city}
                </div>
                <div className="case-bid-row">
                  <span className="case-bid">
                    {yen(t.final_amount ?? t.initial_amount)}
                  </span>
                </div>
              </button>
            ))
          )}
        </nav>

        {/* チャット本体 */}
        <div className="chat-main">
          {tokenLoading || (!detail && !detailError) ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--body-soft)" }}>
              読み込み中…
            </div>
          ) : detailError ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--body-soft)" }}>
              {detailError}
            </div>
          ) : (
            <>
              {/* 相手（ユーザー）ヘッダー */}
              <div className="chat-peer-header">
                <div className="peer-avatar">{peerInitial}</div>
                <div className="peer-info">
                  <div className="peer-name">お客様</div>
                  <div className="peer-sub">
                    {detail?.case?.prefecture} {detail?.case?.city}　{caseIdShort}
                  </div>
                </div>
                <div className="amount-chip">
                  <div className="amount-label">合意額</div>
                  <div className="amount-val">{yen(detail?.final_amount ?? detail?.initial_amount ?? 0)}</div>
                </div>
              </div>

              {/* ステータスバー */}
              <div className="status-bar">
                <span className="status-dot" aria-hidden="true" />
                {statusLabel}
              </div>

              {messagesError ? (
                <div style={{ padding: "8px 20px", fontSize: 12.5, color: "#e05c5c" }}>{messagesError}</div>
              ) : null}

              {/* メッセージ */}
              <div className="messages-area" ref={messagesRef}>
                {messages.map((m, i) => {
                  const showDateSep = i === 0 || formatDateSep(m.created_at) !== formatDateSep(messages[i - 1].created_at);
                  return (
                    <div key={m.id}>
                      {showDateSep ? <div className="date-sep">{formatDateSep(m.created_at)}</div> : null}
                      <div className={`msg ${m.mine ? "me" : "them"}`}>
                        <div className="msg-avatar">{m.mine ? "自" : m.sender_type === "system" ? "運" : peerInitial}</div>
                        <div>
                          <div className="msg-time">{formatTime(m.created_at)}</div>
                          <div className="bubble">{m.body}</div>
                        </div>
                      </div>
                    </div>
                  );
                })}

                {scheduleVisible ? (
                  <div className="schedule-propose" id="schedule-propose">
                    <div className="sp-head">
                      <CalendarIc />
                      引き取り候補日を提案する
                    </div>
                    <div className="sp-options">
                      {slots.map((slot, i) => (
                        <div className="sp-opt-row" key={i}>
                          <input
                            type="text"
                            className="sp-date-input"
                            value={slot}
                            placeholder="日程を入力（例：7月13日（日）10:00〜12:00）"
                            onChange={(e) => updateSlot(i, e.target.value)}
                            aria-label={`候補日 ${i + 1}`}
                          />
                          <button type="button" className="sp-remove" onClick={() => removeSlot(i)} aria-label={`候補日 ${i + 1} を削除`}>
                            <Ic name="x" />
                          </button>
                        </div>
                      ))}
                    </div>
                    <button type="button" className="btn-add-slot" onClick={addSlot}>
                      ＋ 候補日を追加
                    </button>
                    <button
                      type="button"
                      className="btn-send-schedule"
                      onClick={() => void handleSendSchedule()}
                      disabled={proposing}
                    >
                      {proposing ? "送信中…" : "候補日を送信する"}
                    </button>
                  </div>
                ) : null}
              </div>

              {/* 入力エリア */}
              <div className="input-area">
                <div className="input-tools">
                  <button type="button" className="tool-btn" title="日程を提案" aria-label="日程を提案" onClick={toggleScheduleCard}>
                    <CalendarIc />
                  </button>
                </div>
                <input
                  type="text"
                  className="msg-input"
                  placeholder="メッセージを入力…"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void handleSend();
                    }
                  }}
                  aria-label="メッセージを入力"
                  disabled={sending}
                />
                <button
                  type="button"
                  className="btn-send"
                  aria-label="送信"
                  disabled={!draft.trim() || sending}
                  onClick={() => void handleSend()}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M22 2L11 13" />
                    <path d="M22 2L15 22l-4-9-9-4 20-7z" />
                  </svg>
                </button>
              </div>
            </>
          )}
        </div>

        {/* 右パネル（出品内容） */}
        <aside className="detail-panel" aria-label="出品内容">
          <div className="dp-head">出品内容</div>
          <div className="dp-case-id">
            <div className="lbl">案件ID</div>
            <div className="val">{caseIdShort}</div>
          </div>
          <div className="dp-info">
            <div className="dp-row">
              <span className="lbl">エリア</span>
              <span className="val">
                {detail?.case?.prefecture} {detail?.case?.city}
              </span>
            </div>
            <div className="dp-row">
              <span className="lbl">合意額</span>
              <span className="val blue">{yen(detail?.final_amount ?? detail?.initial_amount ?? 0)}</span>
            </div>
            <div className="dp-row">
              <span className="lbl">手数料</span>
              <span className="val">{yen(detail?.fee_amount ?? 0)}</span>
            </div>
            <div className="dp-row">
              <span className="lbl">ステータス</span>
              <span className="val green">{statusLabel}</span>
            </div>
          </div>
          <button type="button" className="btn-propose" onClick={toggleScheduleCard}>
            <CalendarIc />
            引き取り日程を提案
          </button>
        </aside>
      </div>

      {toast ? (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
